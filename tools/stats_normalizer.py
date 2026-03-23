"""
Canonical stat normalization helpers.

Maps mixed GameChanger web/app/PDF schemas into a single shape used by
matchup, SWOT, lineup optimization, and pipeline health checks.
"""

from __future__ import annotations

from typing import Any, Callable


CANONICAL_BATTING_FIELDS = ["pa", "ab", "h", "1b", "2b", "3b", "hr", "bb", "hbp", "so", "rbi", "sb", "r"]
CANONICAL_PITCHING_FIELDS = ["ip", "er", "bb", "h", "so", "whip", "era"]
CANONICAL_FIELDING_FIELDS = ["po", "a", "e", "fpct"]


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s in ("", "-", "—", "N/A"):
        return default
    if s.startswith("."):
        s = f"0{s}"
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(round(safe_float(val, float(default))))
    except (TypeError, ValueError):
        return default


def innings_to_float(val: Any) -> float:
    """Convert softball innings notation (e.g. 4.2 => 4 and 2 outs) to float innings."""
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s:
        return 0.0
    if "." in s:
        try:
            whole, frac = s.split(".", 1)
            outs = int(whole) * 3 + int(frac)
            return outs / 3.0
        except Exception:
            return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _source(row: dict) -> dict:
    if isinstance(row.get("batting"), dict):
        return row["batting"]
    return row


def _pick(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d.get(k) not in (None, "", "-", "—"):
            return d.get(k)
    return None


def normalize_batting_row(row: dict) -> dict:
    src = _source(row or {})
    ab = safe_int(_pick(src, "ab"))
    h = safe_int(_pick(src, "h"))
    bb = safe_int(_pick(src, "bb"))
    hbp = safe_int(_pick(src, "hbp"))
    so = safe_int(_pick(src, "so", "k"))
    hr = safe_int(_pick(src, "hr"))
    doubles = safe_int(_pick(src, "2b", "doubles"))
    triples = safe_int(_pick(src, "3b", "triples"))
    one_b = safe_int(_pick(src, "1b", "singles"))
    if one_b == 0 and h > 0:
        one_b = max(0, h - doubles - triples - hr)
    sac = safe_int(_pick(src, "sac", "sf"))
    r = safe_int(_pick(src, "r"))
    rbi = safe_int(_pick(src, "rbi"))
    sb = safe_int(_pick(src, "sb"))

    pa = safe_int(_pick(src, "pa"))
    if pa == 0:
        pa = ab + bb + hbp + sac

    tb = one_b + 2 * doubles + 3 * triples + 4 * hr
    avg = safe_float(_pick(src, "avg"), (h / ab) if ab > 0 else 0.0)
    obp = safe_float(_pick(src, "obp"), ((h + bb + hbp) / pa) if pa > 0 else 0.0)
    slg = safe_float(_pick(src, "slg"), (tb / ab) if ab > 0 else 0.0)
    ops = safe_float(_pick(src, "ops"), obp + slg)

    return {
        "pa": pa,
        "ab": ab,
        "h": h,
        "1b": one_b,
        "2b": doubles,
        "3b": triples,
        "hr": hr,
        "bb": bb,
        "hbp": hbp,
        "so": so,
        "rbi": rbi,
        "sb": sb,
        "r": r,
        "sac": sac,
        # compatibility aliases used throughout current code
        "singles": one_b,
        "doubles": doubles,
        "triples": triples,
        "avg": round(avg, 3),
        "obp": round(obp, 3),
        "slg": round(slg, 3),
        "ops": round(ops, 3),
    }


def normalize_pitching_row(row: dict) -> dict:
    src = row.get("pitching", row or {})
    ip = innings_to_float(_pick(src, "ip"))
    er = safe_int(_pick(src, "er"))
    bb = safe_int(_pick(src, "bb"))
    h = safe_int(_pick(src, "h"))
    so = safe_int(_pick(src, "so", "k"))
    whip = safe_float(_pick(src, "whip"), ((bb + h) / ip) if ip > 0 else 0.0)
    era = safe_float(_pick(src, "era"), ((er * 7) / ip) if ip > 0 else 0.0)
    return {
        "ip": round(ip, 2),
        "er": er,
        "bb": bb,
        "h": h,
        "so": so,
        "whip": round(whip, 2),
        "era": round(era, 2),
    }


def normalize_fielding_row(row: dict) -> dict:
    src = row.get("fielding", row or {})
    po = safe_int(_pick(src, "po"))
    a = safe_int(_pick(src, "a"))
    e = safe_int(_pick(src, "e"))
    fpct = safe_float(_pick(src, "fpct"), ((po + a) / (po + a + e)) if (po + a + e) > 0 else 0.0)
    return {"po": po, "a": a, "e": e, "fpct": round(fpct, 3)}


def normalize_player_batting(player: dict) -> dict:
    """Preferred player batting source order: batting -> stats.hitting -> legacy flat keys."""
    batting = player.get("batting")
    if isinstance(batting, dict) and batting:
        return normalize_batting_row(batting)
    hitting = (player.get("stats") or {}).get("hitting")
    if isinstance(hitting, dict) and hitting:
        return normalize_batting_row(hitting)
    return normalize_batting_row(player)


def count_populated_fields(rows: list[dict], fields: list[str], normalizer: Callable[[dict], dict]) -> dict:
    counts = {field: 0 for field in fields}
    for row in rows:
        normalized = normalizer(row or {})
        for field in fields:
            val = normalized.get(field)
            if isinstance(val, (int, float)):
                if val > 0:
                    counts[field] += 1
            elif val not in (None, "", "-", "—"):
                counts[field] += 1
    return counts
