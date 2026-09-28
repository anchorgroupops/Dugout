"""Post-download CSV validation and quarantine.

A "valid" CSV:
  - has .csv extension
  - parses without error
  - has at least one data row (a player row, not Totals/Glossary/blank)
  - shares >= 80% column-name overlap with the last known schema (if provided)

GC's season-stats export starts with a BOM and a section-label row
("Batting", "Pitching", "Fielding") above the real column header, and ends
with a Totals row, a blank row and a Glossary row. A header-only export
(the stats table was empty when Export was clicked) therefore still has
three lines — it must be rejected, not ingested as a 0-player roster.
"""
from __future__ import annotations
import csv
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

ADVISORY_THRESHOLD = 0.80  # >=80% but <95%
HEALTHY_THRESHOLD = 0.95

# Labels GC puts in the row above the real header.
GC_SECTION_LABELS = {"Batting", "Pitching", "Fielding", "Catching", "Innings Played"}
# First-column markers of GC's non-player trailer rows.
GC_TRAILER_MARKERS = {"Totals", "Glossary"}


@dataclass
class ValidationResult:
    accepted: bool
    reason: str = ""
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    drift_severity: str = "none"  # 'none', 'advisory', 'critical'


def validate(path: Path, known_columns: list[str] | None) -> ValidationResult:
    if path.suffix.lower() != ".csv":
        return ValidationResult(accepted=False, reason=f"Not a .csv extension: {path.suffix}")

    if not path.exists() or path.stat().st_size == 0:
        return ValidationResult(accepted=False, reason="File is empty")

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return ValidationResult(accepted=False, reason="File is empty (no header)")
            rows = list(reader)
    except UnicodeDecodeError as e:
        return ValidationResult(accepted=False, reason=f"UTF-8 decode failed: {e}")
    except csv.Error as e:
        return ValidationResult(accepted=False, reason=f"CSV parse error: {e}")

    if _is_section_row(header) and rows:
        header, rows = rows[0], rows[1:]

    columns = [c.strip() for c in header if c.strip()]
    if not columns:
        return ValidationResult(accepted=False, reason="No columns in header")

    data_rows = [r for r in rows if _is_data_row(r)]
    if not data_rows:
        return ValidationResult(
            accepted=False,
            reason="No data rows (export had headers but no player rows)",
            columns=columns, row_count=0,
        )

    result = ValidationResult(
        accepted=True, columns=columns, row_count=len(data_rows),
        drift_severity="none",
    )

    if known_columns and not _is_legacy_baseline(known_columns):
        overlap = _overlap(columns, known_columns)
        if overlap < ADVISORY_THRESHOLD:
            result.accepted = False
            result.reason = (
                f"Schema drift critical: {overlap:.0%} column overlap "
                f"(expected >= {ADVISORY_THRESHOLD:.0%})"
            )
            result.drift_severity = "critical"
        elif overlap < HEALTHY_THRESHOLD:
            result.drift_severity = "advisory"

    return result


def _is_section_row(row: list[str]) -> bool:
    cells = {c.strip() for c in row if c.strip()}
    return bool(cells) and cells <= GC_SECTION_LABELS


def _is_data_row(row: list[str]) -> bool:
    if not any(c.strip() for c in row):
        return False
    return row[0].strip() not in GC_TRAILER_MARKERS


def _is_legacy_baseline(known_cols: list[str]) -> bool:
    """True for schemas recorded before the section-row fix.

    Those stored GC's section labels plus the BOM-mangled first cell
    ('\\ufeff""') as "columns". Comparing a real header against them is
    0% overlap, which would quarantine every good CSV forever (quarantine
    never records a new baseline), so treat them as no baseline.
    """
    return all(c in GC_SECTION_LABELS or not c.strip('\ufeff"').strip()
               for c in known_cols)


def quarantine(path: Path, result: ValidationResult, *,
               quarantine_root: Path) -> Path:
    ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
    dest_dir = quarantine_root / ts
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), str(dest))
    (dest_dir / "reason.txt").write_text(
        f"reason: {result.reason}\ndrift: {result.drift_severity}\n",
        encoding="utf-8",
    )
    return dest


def _overlap(csv_cols: list[str], known_cols: list[str]) -> float:
    """Fraction of the known columns present in the CSV (asymmetric).

    Denominator is the known-columns set, so adding new columns does not
    reduce overlap. Only missing known columns drives drift.
    """
    sa, sb = set(csv_cols), set(known_cols)
    if not sb:
        return 1.0
    return len(sa & sb) / len(sb)
