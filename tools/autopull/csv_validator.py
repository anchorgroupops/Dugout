"""Post-download CSV validation and quarantine.

A "valid" CSV:
  - has .csv extension
  - parses without error
  - has at least one data row
  - shares >= 80% column-name overlap with the last known schema (if provided)
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
        with path.open("r", encoding="utf-8", newline="") as fh:
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

    columns = [c.strip() for c in header if c.strip()]
    if not columns:
        return ValidationResult(accepted=False, reason="No columns in header")

    if not rows:
        return ValidationResult(
            accepted=False, reason="No data rows", columns=columns, row_count=0
        )

    result = ValidationResult(
        accepted=True, columns=columns, row_count=len(rows), drift_severity="none"
    )

    if known_columns:
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
