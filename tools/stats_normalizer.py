"""
Canonical stat normalization helpers.

Maps mixed GameChanger web/app/PDF schemas into a single shape used by
matchup, SWOT, lineup optimization, and pipeline health checks.
"""

from __future__ import annotations

import statistics
from typing import Any, Callable


CANONICAL_BATTING_FIELDS = ["pa", "ab", "h", "1b", "2b", "3b", "hr", "bb", "hbp", "so", "rbi", "sb", "r", "sac"]
CANONICAL_BATTING_ADV_FIELDS = [
    "qab",
    "qab_pct",
    "pa_per_bb",
    "bb_per_k",
    "c_pct",
    "hhb",
    "ld_pct",
    "fb_pct",
    "gb_pct",
    "babip",
    "ba_risp",
]
CANONICAL_PITCHING_FIELDS = ["ip", "er", "bb", "h", "so", "whip", "era"]
CANONICAL_PITCHING_ADV_FIELDS = [
    "bf",
    "np",
    "k_bf",
    "k_bb",
    "bb_inn",
    "fip",
    "babip",
    "ba_risp",
    "ld_pct",
    "fb_pct",
    "gb_pct",
    "hhb_pct",
]
CANONICAL_FIELDING_FIELDS = ["po", "a", "e", "fpct"]
CANONICAL_CATCHING_FIELDS = ["inn", "sb", "cs", "cs_pct", "pb", "pik", "ci"]
CANONICAL_INNINGS_FIELDS = ["total", "p", "c", "first_base", "second_base", "third_base", "ss", "lf", "cf", "rf", "sf"]


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


def safe_pct_ratio(val: Any, default: float = 0.0) -> float:
    """
    Normalize percentage-like values to ratio format [0..1+] when possible.
    Examples:
      44.44 -> 0.4444
      "80.0" -> 0.8
      0.8 -> 0.8
    """
    raw = safe_float(val, default)
    if raw > 1.0:
        return raw / 100.0
    return raw


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
            frac_int = int(frac)
            if frac_int > 2:
                # Invalid innings notation (outs must be 0-2); treat as plain float
                return float(s)
            outs = int(whole) * 3 + frac_int
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


def normalize_batting_advanced_row(row: dict) -> dict:
    src = row or {}
    if isinstance(src.get("batting_advanced"), dict):
        src = src["batting_advanced"]
    elif isinstance(src.get("batting"), dict):
        batting = src["batting"]
        adv_keys = {"qab", "qab_pct", "pa_per_bb", "bb_per_k", "c_pct", "hhb", "ld_pct", "fb_pct", "gb_pct"}
        if any(k in batting for k in adv_keys):
            src = batting

    qab = safe_int(_pick(src, "qab"))
    pa = safe_int(_pick(src, "pa"))
    ab = safe_int(_pick(src, "ab"))
    bb = safe_int(_pick(src, "bb"))
    so = safe_int(_pick(src, "so", "k"))

    qab_pct = safe_pct_ratio(_pick(src, "qab_pct", "qab%"))
    if qab_pct == 0 and qab > 0 and pa > 0:
        qab_pct = qab / pa

    pa_per_bb = safe_float(_pick(src, "pa_per_bb", "pa/bb"))
    if pa_per_bb == 0 and pa > 0 and bb > 0:
        pa_per_bb = pa / bb

    bb_per_k = safe_float(_pick(src, "bb_per_k", "bb_k", "bb/k"))
    if bb_per_k == 0 and bb > 0 and so > 0:
        bb_per_k = bb / so

    c_pct = safe_pct_ratio(_pick(src, "c_pct", "c%"))
    ld_pct = safe_pct_ratio(_pick(src, "ld_pct", "ld%"))
    fb_pct = safe_pct_ratio(_pick(src, "fb_pct", "fb%"))
    gb_pct = safe_pct_ratio(_pick(src, "gb_pct", "gb%"))

    return {
        "pa": pa,
        "ab": ab,
        "bb": bb,
        "so": so,
        "qab": qab,
        "qab_pct": round(qab_pct, 4),
        "pa_per_bb": round(pa_per_bb, 3),
        "bb_per_k": round(bb_per_k, 3),
        "c_pct": round(c_pct, 4),
        "hhb": safe_int(_pick(src, "hhb")),
        "ld_pct": round(ld_pct, 4),
        "fb_pct": round(fb_pct, 4),
        "gb_pct": round(gb_pct, 4),
        "babip": round(safe_float(_pick(src, "babip")), 3),
        "ba_risp": round(safe_float(_pick(src, "ba_risp")), 3),
        "ps": round(safe_float(_pick(src, "ps")), 2),
        "ps_pa": round(safe_float(_pick(src, "ps_pa", "ps/pa")), 3),
        "tb": safe_int(_pick(src, "tb")),
        "xbh": safe_int(_pick(src, "xbh")),
        "two_out_rbi": safe_int(_pick(src, "two_out_rbi")),
        "gidp": safe_int(_pick(src, "gidp")),
        "gitp": safe_int(_pick(src, "gitp")),
        "six_plus": safe_int(_pick(src, "six_plus")),
        "six_plus_pct": round(safe_pct_ratio(_pick(src, "six_plus_pct")), 4),
        "two_s_three": safe_int(_pick(src, "two_s_three")),
        "two_s_three_pct": round(safe_pct_ratio(_pick(src, "two_s_three_pct")), 4),
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


def normalize_pitching_advanced_row(row: dict) -> dict:
    src = row or {}
    if isinstance(src.get("pitching_advanced"), dict):
        src = src["pitching_advanced"]
    elif isinstance(src.get("pitching"), dict):
        pitching = src["pitching"]
        adv_keys = {"k_bf", "bb_inn", "fip", "babip", "ba_risp", "ld_pct", "fb_pct", "gb_pct", "hhb_pct"}
        if any(k in pitching for k in adv_keys):
            src = pitching

    ip = innings_to_float(_pick(src, "ip"))
    bf = safe_int(_pick(src, "bf"))
    so = safe_int(_pick(src, "so", "k"))
    bb = safe_int(_pick(src, "bb"))

    k_bf = safe_float(_pick(src, "k_bf"))
    if k_bf == 0 and bf > 0 and so > 0:
        k_bf = so / bf

    k_bb = safe_float(_pick(src, "k_bb"))
    if k_bb == 0 and bb > 0 and so > 0:
        k_bb = so / bb

    bb_inn = safe_float(_pick(src, "bb_inn"))
    if bb_inn == 0 and ip > 0 and bb > 0:
        bb_inn = bb / ip

    return {
        "bf": bf,
        "np": safe_int(_pick(src, "np", "pitches", "#p")),
        "k_bf": round(k_bf, 4),
        "k_bb": round(k_bb, 3),
        "bb_inn": round(bb_inn, 3),
        "fip": round(safe_float(_pick(src, "fip")), 2),
        "babip": round(safe_float(_pick(src, "babip")), 3),
        "ba_risp": round(safe_float(_pick(src, "ba_risp")), 3),
        "ld_pct": round(safe_pct_ratio(_pick(src, "ld_pct", "ld%")), 4),
        "fb_pct": round(safe_pct_ratio(_pick(src, "fb_pct", "fb%")), 4),
        "gb_pct": round(safe_pct_ratio(_pick(src, "gb_pct", "gb%")), 4),
        "hhb_pct": round(safe_pct_ratio(_pick(src, "hhb_pct", "hhb%")), 4),
    }


def normalize_fielding_row(row: dict) -> dict:
    src = row.get("fielding", row or {})
    po = safe_int(_pick(src, "po"))
    a = safe_int(_pick(src, "a"))
    e = safe_int(_pick(src, "e"))
    fpct = safe_float(_pick(src, "fpct"), ((po + a) / (po + a + e)) if (po + a + e) > 0 else 0.0)
    return {"po": po, "a": a, "e": e, "fpct": round(fpct, 3)}


def normalize_catching_row(row: dict) -> dict:
    src = row or {}
    if isinstance(src.get("catching"), dict):
        src = src["catching"]
    inn = innings_to_float(_pick(src, "inn"))
    sb = safe_int(_pick(src, "sb"))
    cs = safe_int(_pick(src, "cs"))
    cs_pct = safe_pct_ratio(_pick(src, "cs_pct"))
    if cs_pct == 0 and (sb + cs) > 0:
        cs_pct = cs / (sb + cs)
    return {
        "inn": round(inn, 2),
        "sb": sb,
        "cs": cs,
        "cs_pct": round(cs_pct, 4),
        "pb": safe_int(_pick(src, "pb")),
        "pik": safe_int(_pick(src, "pik")),
        "ci": safe_int(_pick(src, "ci")),
    }


def normalize_innings_played_row(row: dict) -> dict:
    src = row or {}
    if isinstance(src.get("innings_played"), dict):
        src = src["innings_played"]
    return {
        "total": round(innings_to_float(_pick(src, "total", "ip:f")), 2),
        "p": round(innings_to_float(_pick(src, "p", "ip:p")), 2),
        "c": round(innings_to_float(_pick(src, "c", "ip:c")), 2),
        "first_base": round(innings_to_float(_pick(src, "first_base", "ip:1b")), 2),
        "second_base": round(innings_to_float(_pick(src, "second_base", "ip:2b")), 2),
        "third_base": round(innings_to_float(_pick(src, "third_base", "ip:3b")), 2),
        "ss": round(innings_to_float(_pick(src, "ss", "ip:ss")), 2),
        "lf": round(innings_to_float(_pick(src, "lf", "ip:lf")), 2),
        "cf": round(innings_to_float(_pick(src, "cf", "ip:cf")), 2),
        "rf": round(innings_to_float(_pick(src, "rf", "ip:rf")), 2),
        "sf": round(innings_to_float(_pick(src, "sf", "ip:sf")), 2),
    }


def normalize_player_batting(player: dict) -> dict:
    """Preferred player batting source order: batting -> stats.hitting -> legacy flat keys."""
    batting = player.get("batting")
    if isinstance(batting, dict) and batting:
        return normalize_batting_row(batting)
    hitting = (player.get("stats") or {}).get("hitting")
    if isinstance(hitting, dict) and hitting:
        return normalize_batting_row(hitting)
    return normalize_batting_row(player)


def normalize_player_batting_advanced(player: dict) -> dict:
    """Preferred source order: batting_advanced -> batting (app adv keys) -> legacy flat keys."""
    batting_adv = player.get("batting_advanced")
    if isinstance(batting_adv, dict) and batting_adv:
        return normalize_batting_advanced_row(batting_adv)

    batting = player.get("batting")
    if isinstance(batting, dict) and batting:
        adv_keys = {"qab", "qab_pct", "pa_per_bb", "bb_per_k", "c_pct", "hhb", "ld_pct", "fb_pct", "gb_pct"}
        if any(k in batting for k in adv_keys):
            return normalize_batting_advanced_row(batting)

    hitting_adv = (player.get("stats") or {}).get("hitting_advanced")
    if isinstance(hitting_adv, dict) and hitting_adv:
        return normalize_batting_advanced_row(hitting_adv)

    return normalize_batting_advanced_row(player)


def player_identity_key(player: dict) -> str:
    number = str(player.get("number", "")).strip()
    first = str(player.get("first", "")).strip().lower()
    last = str(player.get("last", "")).strip().lower()
    name = str(player.get("name", "")).strip().lower()
    if number:
        return f"#{number}"
    if first or last:
        return f"{first}|{last}".strip("|")
    return name or "unknown"


def build_player_metric_profile(player: dict) -> dict[str, float]:
    batting = normalize_player_batting(player)
    pitching = normalize_pitching_row(player)
    fielding = normalize_fielding_row(player)

    pa = float(batting.get("pa", 0))
    so = float(batting.get("so", 0))
    bb = float(batting.get("bb", 0))
    ip = float(pitching.get("ip", 0))

    return {
        "batting_avg": float(batting.get("avg", 0.0)),
        "batting_obp": float(batting.get("obp", 0.0)),
        "batting_slg": float(batting.get("slg", 0.0)),
        "batting_ops": float(batting.get("ops", 0.0)),
        "batting_k_rate": (so / pa) if pa > 0 else 0.0,
        "batting_bb_rate": (bb / pa) if pa > 0 else 0.0,
        "pitching_era": float(pitching.get("era", 0.0)),
        "pitching_whip": float(pitching.get("whip", 0.0)),
        "pitching_bb_per_ip": (float(pitching.get("bb", 0.0)) / ip) if ip > 0 else 0.0,
        "pitching_k_per_ip": (float(pitching.get("so", 0.0)) / ip) if ip > 0 else 0.0,
        "fielding_fpct": float(fielding.get("fpct", 0.0)),
        "fielding_errors": float(fielding.get("e", 0)),
    }


def detect_player_outlier_stats(
    player: dict,
    history_profiles: list[dict[str, float]],
    z_threshold: float = 3.0,
    min_history_samples: int = 5,
) -> list[dict[str, float | str]]:
    """
    Flag current player stats that are > z_threshold SD away from historical mean.
    Returns anomaly records with metric/current/mean/stddev/z_score.
    """
    current = build_player_metric_profile(player)
    outliers: list[dict[str, float | str]] = []

    for metric, current_val in current.items():
        values = [float(h.get(metric, 0.0)) for h in history_profiles if metric in h]
        if len(values) < min_history_samples:
            continue

        mean_val = statistics.fmean(values)
        stdev = statistics.pstdev(values)
        if stdev <= 1e-9:
            continue

        z_score = abs((current_val - mean_val) / stdev)
        if z_score > z_threshold:
            outliers.append(
                {
                    "metric": metric,
                    "current": round(current_val, 4),
                    "mean": round(mean_val, 4),
                    "stddev": round(stdev, 4),
                    "z_score": round(z_score, 4),
                }
            )

    return outliers


def validate_team_outlier_stats(
    team_data: dict,
    historical_profiles_by_player: dict[str, list[dict[str, float]]],
    z_threshold: float = 3.0,
    min_history_samples: int = 5,
) -> list[dict[str, Any]]:
    """
    Validate full roster and return detected anomalies.
    historical_profiles_by_player should be keyed by player_identity_key().
    """
    findings: list[dict[str, Any]] = []
    for player in team_data.get("roster", []):
        identity = player_identity_key(player)
        history = historical_profiles_by_player.get(identity, [])
        if not history:
            continue
        outliers = detect_player_outlier_stats(
            player,
            history_profiles=history,
            z_threshold=z_threshold,
            min_history_samples=min_history_samples,
        )
        if outliers:
            findings.append(
                {
                    "player": {
                        "number": player.get("number"),
                        "name": (player.get("name") or f"{player.get('first', '')} {player.get('last', '')}").strip(),
                        "identity": identity,
                    },
                    "outliers": outliers,
                }
            )
    return findings


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
