"""Music Wizard — catalog seed, optimal-start detection, roster auto-match.

Provides the top-500 walk-up song seed catalog and helpers for:
  - Seeding the walkup_catalog SQLite table on first run
  - Computing optimal_start_ms from Spotify audio analysis
  - Auto-matching catalog songs to roster players by jersey number or tag
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from announcer_db import _conn  # noqa: F401

log = logging.getLogger("music_wizard")

# ---------------------------------------------------------------------------
# Curated walk-up catalog (top ~50 seed entries)
# Each entry: rank, title, artist, spotify_id, apple_id,
#             optimal_start_ms, duration_ms, energy_score, tags[]
# ---------------------------------------------------------------------------

WALKUP_CATALOG: list[dict] = [
    {"rank": 1,  "title": "Enter Sandman",          "artist": "Metallica",          "spotify_id": "5sICkBXVmaCQk5aISGR3x1", "optimal_start_ms": 0,      "duration_ms": 331000, "energy_score": 0.98, "tags": ["metal","power","classic"]},
    {"rank": 2,  "title": "Seven Nation Army",       "artist": "The White Stripes",  "spotify_id": "7i3skATtSMkVnkW0L3BNKO", "optimal_start_ms": 0,      "duration_ms": 231000, "energy_score": 0.91, "tags": ["rock","riff","stadium"]},
    {"rank": 3,  "title": "Lose Yourself",           "artist": "Eminem",             "spotify_id": "1v7L65Lzy0j0vdpRjdi Dnt", "optimal_start_ms": 22000, "duration_ms": 326000, "energy_score": 0.94, "tags": ["hip-hop","hype","focus"]},
    {"rank": 4,  "title": "Eye of the Tiger",        "artist": "Survivor",           "spotify_id": "2HHtWyy5CgaQbC7XSoOb0e", "optimal_start_ms": 0,      "duration_ms": 244000, "energy_score": 0.92, "tags": ["classic","pump-up","80s"]},
    {"rank": 5,  "title": "Welcome to the Jungle",   "artist": "Guns N' Roses",      "spotify_id": "0o4jSZBxOQUiDKzAuCBOIH", "optimal_start_ms": 14000, "duration_ms": 274000, "energy_score": 0.97, "tags": ["rock","aggressive","classic"]},
    {"rank": 6,  "title": "Thunderstruck",           "artist": "AC/DC",              "spotify_id": "57bgtoPSgt236HzfBOd8kj", "optimal_start_ms": 0,      "duration_ms": 292000, "energy_score": 0.96, "tags": ["rock","electric","stadium"]},
    {"rank": 7,  "title": "All I Do Is Win",         "artist": "DJ Khaled",          "spotify_id": "4kbj5MwxO1bq9wjT5g9HaA", "optimal_start_ms": 7000,  "duration_ms": 226000, "energy_score": 0.93, "tags": ["hip-hop","winning","hype"]},
    {"rank": 8,  "title": "Can't Stop the Feeling", "artist": "Justin Timberlake",  "spotify_id": "1WkMMavIMc4JZ8cfMmxHkI", "optimal_start_ms": 16000, "duration_ms": 234000, "energy_score": 0.87, "tags": ["pop","fun","upbeat"]},
    {"rank": 9,  "title": "Roar",                   "artist": "Katy Perry",          "spotify_id": "2L2unNFaPbDxjg3NqzpqhR", "optimal_start_ms": 24000, "duration_ms": 224000, "energy_score": 0.86, "tags": ["pop","empowerment","girls"]},
    {"rank": 10, "title": "Run the World (Girls)",  "artist": "Beyoncé",             "spotify_id": "3oNbDRXRFILyoTZ7LvzGgq", "optimal_start_ms": 0,      "duration_ms": 236000, "energy_score": 0.90, "tags": ["pop","empowerment","girls","energetic"]},
    {"rank": 11, "title": "Started From the Bottom","artist": "Drake",               "spotify_id": "2SHPG8D10KfHGK0gxFj0Xs", "optimal_start_ms": 0,      "duration_ms": 195000, "energy_score": 0.85, "tags": ["hip-hop","swagger","clutch"]},
    {"rank": 12, "title": "We Will Rock You",       "artist": "Queen",               "spotify_id": "4pbJqGIASGPr0ZpGpnWkDn", "optimal_start_ms": 0,      "duration_ms": 122000, "energy_score": 0.95, "tags": ["classic","stadium","chant","rock"]},
    {"rank": 13, "title": "Hall of Fame",            "artist": "The Script",          "spotify_id": "2RlnZu0p9g0o3pI9IEDhrM", "optimal_start_ms": 38000, "duration_ms": 204000, "energy_score": 0.84, "tags": ["pop","inspirational","big-moment"]},
    {"rank": 14, "title": "Born to Run",             "artist": "Bruce Springsteen",  "spotify_id": "6H0nwjVbPpRFxlAXm8bfQk", "optimal_start_ms": 60000, "duration_ms": 270000, "energy_score": 0.89, "tags": ["rock","classic","hustle"]},
    {"rank": 15, "title": "Till I Collapse",         "artist": "Eminem",             "spotify_id": "0Z3PJTnvKE1clKs2l3GVz5", "optimal_start_ms": 0,      "duration_ms": 298000, "energy_score": 0.96, "tags": ["hip-hop","grit","aggressive"]},
    {"rank": 16, "title": "Jump",                    "artist": "Kris Kross",         "spotify_id": "2y1HX7DGXR5sEi0XbGrNL4", "optimal_start_ms": 0,      "duration_ms": 226000, "energy_score": 0.90, "tags": ["hip-hop","fun","90s"]},
    {"rank": 17, "title": "Power",                   "artist": "Kanye West",         "spotify_id": "2gZUPNdnz5Y45eiGxpHGSc", "optimal_start_ms": 0,      "duration_ms": 292000, "energy_score": 0.94, "tags": ["hip-hop","epic","power"]},
    {"rank": 18, "title": "Berzerk",                 "artist": "Eminem",             "spotify_id": "4GKbqElQa2JLNHE3J7y8pA", "optimal_start_ms": 0,      "duration_ms": 235000, "energy_score": 0.95, "tags": ["hip-hop","aggressive","pump-up"]},
    {"rank": 19, "title": "Stronger",                "artist": "Kanye West",         "spotify_id": "0LyfQWLjkoeXAGiHkAAGFB", "optimal_start_ms": 45000, "duration_ms": 311000, "energy_score": 0.91, "tags": ["hip-hop","electronic","motivation"]},
    {"rank": 20, "title": "Party Rock Anthem",       "artist": "LMFAO",              "spotify_id": "3eBkbGIFX5rrQeyOiilAi9", "optimal_start_ms": 13000, "duration_ms": 227000, "energy_score": 0.92, "tags": ["electronic","fun","upbeat"]},
    {"rank": 21, "title": "Don't Stop Me Now",       "artist": "Queen",              "spotify_id": "5T8EDUDqKcs6OSOwEsfqG7", "optimal_start_ms": 0,      "duration_ms": 209000, "energy_score": 0.88, "tags": ["rock","fun","classic","fast"]},
    {"rank": 22, "title": "Shake It Off",            "artist": "Taylor Swift",       "spotify_id": "0cqRj7pUJDkTCEsJkx8snD", "optimal_start_ms": 0,      "duration_ms": 219000, "energy_score": 0.83, "tags": ["pop","fun","girls","upbeat"]},
    {"rank": 23, "title": "Fighter",                 "artist": "Christina Aguilera", "spotify_id": "2Y3v6DqREbcgPXgNiCT1bV", "optimal_start_ms": 48000, "duration_ms": 249000, "energy_score": 0.88, "tags": ["pop","empowerment","girls","power"]},
    {"rank": 24, "title": "Work B**ch",              "artist": "Britney Spears",     "spotify_id": "3jZ0GKAZiOtQTc7EZFnhBv", "optimal_start_ms": 8000,  "duration_ms": 209000, "energy_score": 0.90, "tags": ["pop","hustle","energetic"]},
    {"rank": 25, "title": "Bad Guy",                 "artist": "Billie Eilish",      "spotify_id": "2Fxmhks0bxGSBdJ92vM42m", "optimal_start_ms": 44000, "duration_ms": 194000, "energy_score": 0.74, "tags": ["pop","attitude","swagger"]},
    {"rank": 26, "title": "God's Plan",              "artist": "Drake",              "spotify_id": "6DCZcSspjsKoFjzjrWoCdn", "optimal_start_ms": 0,      "duration_ms": 198000, "energy_score": 0.79, "tags": ["hip-hop","clutch","confidence"]},
    {"rank": 27, "title": "HUMBLE.",                 "artist": "Kendrick Lamar",     "spotify_id": "7KXjTSCq5nL1LoYtL7XAwS", "optimal_start_ms": 0,      "duration_ms": 177000, "energy_score": 0.93, "tags": ["hip-hop","attitude","focus"]},
    {"rank": 28, "title": "Best Part",               "artist": "Daniel Caesar",      "spotify_id": "3GCdLUSnKSMJhs4Tj6CV3s", "optimal_start_ms": 0,      "duration_ms": 231000, "energy_score": 0.45, "tags": ["r&b","chill","smooth"]},
    {"rank": 29, "title": "Whatever It Takes",       "artist": "Imagine Dragons",    "spotify_id": "7f0vVL3xi4i78Rv5Ptn2s1", "optimal_start_ms": 0,      "duration_ms": 193000, "energy_score": 0.89, "tags": ["pop","motivation","hustle"]},
    {"rank": 30, "title": "Natural",                 "artist": "Imagine Dragons",    "spotify_id": "7h82bLVqJ4aFHQUEuOvpuV", "optimal_start_ms": 0,      "duration_ms": 189000, "energy_score": 0.87, "tags": ["pop","grit","power"]},
    {"rank": 31, "title": "Warriors",                "artist": "Imagine Dragons",    "spotify_id": "1lgN0A2Vki2FTON5PYq42m", "optimal_start_ms": 0,      "duration_ms": 172000, "energy_score": 0.88, "tags": ["pop","epic","team"]},
    {"rank": 32, "title": "Glory",                   "artist": "John Legend",        "spotify_id": "7Hh6FgByEiPLEIcQVMBiAV", "optimal_start_ms": 16000, "duration_ms": 270000, "energy_score": 0.72, "tags": ["r&b","inspirational","big-moment"]},
    {"rank": 33, "title": "Champion",               "artist": "Kanye West",          "spotify_id": "5mFMXGEWx3TFBPpnPniOMF", "optimal_start_ms": 0,      "duration_ms": 188000, "energy_score": 0.88, "tags": ["hip-hop","winner","confidence"]},
    {"rank": 34, "title": "Famous",                  "artist": "Kanye West",         "spotify_id": "3iVcZ5G6tvkXZkZKlMpIUs", "optimal_start_ms": 0,      "duration_ms": 260000, "energy_score": 0.82, "tags": ["hip-hop","swagger","attitude"]},
    {"rank": 35, "title": "Radioactive",             "artist": "Imagine Dragons",    "spotify_id": "69yfbpvmkIaB10msnKT9Q5", "optimal_start_ms": 18000, "duration_ms": 187000, "energy_score": 0.87, "tags": ["pop","dramatic","power"]},
    {"rank": 36, "title": "Nightmare",               "artist": "Halsey",             "spotify_id": "2MTRHaOmzWvdlMYXEq28pf", "optimal_start_ms": 0,      "duration_ms": 211000, "energy_score": 0.89, "tags": ["pop","aggressive","girls"]},
    {"rank": 37, "title": "Confident",               "artist": "Demi Lovato",        "spotify_id": "6jG2YzhxptolDzLHTGLt7S", "optimal_start_ms": 0,      "duration_ms": 186000, "energy_score": 0.90, "tags": ["pop","confidence","girls","power"]},
    {"rank": 38, "title": "Respect",                 "artist": "Aretha Franklin",    "spotify_id": "7s25THrKz86DM225dOYwnr", "optimal_start_ms": 0,      "duration_ms": 147000, "energy_score": 0.86, "tags": ["soul","classic","girls","attitude"]},
    {"rank": 39, "title": "9 to 5",                  "artist": "Dolly Parton",       "spotify_id": "16jOGvBqJJ1GWp1bD1yLVP", "optimal_start_ms": 0,      "duration_ms": 166000, "energy_score": 0.82, "tags": ["country","fun","hustle"]},
    {"rank": 40, "title": "Before He Cheats",        "artist": "Carrie Underwood",   "spotify_id": "78GHTD6BaRqGTdWZ1DXKZQ", "optimal_start_ms": 0,      "duration_ms": 198000, "energy_score": 0.80, "tags": ["country","attitude","girls"]},
    {"rank": 41, "title": "Girl on Fire",            "artist": "Alicia Keys",        "spotify_id": "1bpGOp2VSN7T3R5P6bHfHt", "optimal_start_ms": 0,      "duration_ms": 246000, "energy_score": 0.82, "tags": ["pop","empowerment","girls"]},
    {"rank": 42, "title": "Survival",                "artist": "Eminem",             "spotify_id": "1V4ndtnG2OHbPoMFGiGmKV", "optimal_start_ms": 0,      "duration_ms": 246000, "energy_score": 0.97, "tags": ["hip-hop","aggressive","grit"]},
    {"rank": 43, "title": "Bounce Back",             "artist": "Big Sean",           "spotify_id": "1GbbebMdBBiPfASTCsNFzW", "optimal_start_ms": 0,      "duration_ms": 205000, "energy_score": 0.86, "tags": ["hip-hop","resilience","clutch"]},
    {"rank": 44, "title": "Jackie Chan",             "artist": "Tiësto",             "spotify_id": "1x5sYLZiu9r5E43kMlt9fz", "optimal_start_ms": 40000, "duration_ms": 194000, "energy_score": 0.91, "tags": ["electronic","fun","upbeat"]},
    {"rank": 45, "title": "Levitating",              "artist": "Dua Lipa",           "spotify_id": "463CkQjx2Zfoiqr0zXCoRK", "optimal_start_ms": 14000, "duration_ms": 203000, "energy_score": 0.85, "tags": ["pop","fun","upbeat","girls"]},
    {"rank": 46, "title": "Physical",                "artist": "Dua Lipa",           "spotify_id": "3xnggMpzIQJIQBDNBqUGQm", "optimal_start_ms": 0,      "duration_ms": 194000, "energy_score": 0.93, "tags": ["pop","energetic","hustle","girls"]},
    {"rank": 47, "title": "abcdefu",                 "artist": "GAYLE",              "spotify_id": "5OVGwAqAWgXkD2LteDMPlJ", "optimal_start_ms": 0,      "duration_ms": 163000, "energy_score": 0.81, "tags": ["pop","attitude","fun","girls"]},
    {"rank": 48, "title": "Bet On It",               "artist": "Zac Efron",          "spotify_id": "1V9pyaWP0fWfwZIWDPIuQQ", "optimal_start_ms": 0,      "duration_ms": 194000, "energy_score": 0.77, "tags": ["pop","confidence","fun"]},
    {"rank": 49, "title": "Proud Mary",              "artist": "Tina Turner",        "spotify_id": "4v6ZzLAronoRLnQ5e4GVKK", "optimal_start_ms": 51000, "duration_ms": 255000, "energy_score": 0.91, "tags": ["rock","classic","girls","powerful"]},
    {"rank": 50, "title": "Simply the Best",         "artist": "Tina Turner",        "spotify_id": "1bCBlzkMTKfITIoJnzsxh7", "optimal_start_ms": 0,      "duration_ms": 214000, "energy_score": 0.85, "tags": ["classic","winning","pump-up"]},
]

# Map common jersey numbers to tag hints used by get_catalog_suggestions
_NUMBER_TAGS: dict[str, list[str]] = {
    "1":  ["swagger", "attitude"],
    "2":  ["smart", "focus"],
    "3":  ["classic", "winning"],
    "4":  ["power", "aggressive"],
    "5":  ["hustle", "grit"],
    "6":  ["fun", "upbeat"],
    "7":  ["lucky", "classic"],
    "8":  ["hip-hop", "swagger"],
    "9":  ["aggressive", "pump-up"],
    "10": ["fun", "confidence"],
    "11": ["electric", "fast"],
    "12": ["team", "epic"],
    "13": ["attitude", "aggressive"],
    "14": ["classic", "inspirational"],
    "15": ["grit", "resilience"],
    "16": ["empowerment", "girls"],
    "17": ["hustle", "hip-hop"],
    "18": ["power", "stadium"],
    "19": ["fun", "upbeat"],
    "20": ["winner", "confidence"],
    "21": ["swagger", "hip-hop"],
    "22": ["attitude", "pop"],
    "23": ["rock", "classic"],
    "24": ["aggressive", "metal"],
    "25": ["motivation", "hustle"],
}


def seed_catalog(conn: "sqlite3.Connection") -> int:
    """Insert all WALKUP_CATALOG entries. Returns count of rows upserted."""
    import json as _json
    count = 0
    for entry in WALKUP_CATALOG:
        try:
            conn.execute(
                """INSERT INTO walkup_catalog
                   (rank, title, artist, spotify_id, apple_id,
                    optimal_start_ms, duration_ms, energy_score, tags)
                   VALUES (:rank, :title, :artist, :spotify_id, :apple_id,
                           :optimal_start_ms, :duration_ms, :energy_score, :tags)
                   ON CONFLICT(rank) DO UPDATE SET
                     title=excluded.title, artist=excluded.artist,
                     spotify_id=excluded.spotify_id, apple_id=excluded.apple_id,
                     optimal_start_ms=excluded.optimal_start_ms,
                     duration_ms=excluded.duration_ms,
                     energy_score=excluded.energy_score,
                     tags=excluded.tags""",
                {
                    "rank": entry["rank"],
                    "title": entry["title"],
                    "artist": entry["artist"],
                    "spotify_id": entry.get("spotify_id"),
                    "apple_id": entry.get("apple_id"),
                    "optimal_start_ms": entry.get("optimal_start_ms", 0),
                    "duration_ms": entry.get("duration_ms"),
                    "energy_score": entry.get("energy_score", 0.0),
                    "tags": _json.dumps(entry.get("tags", [])),
                },
            )
            count += 1
        except Exception as exc:
            log.warning("[music_wizard] seed_catalog skip rank=%s: %s", entry.get("rank"), exc)
    return count


def find_optimal_start_ms(audio_analysis: dict) -> int:
    """Compute the best drop point from a Spotify audio-analysis response.

    Strategy: find the highest-energy section that starts after the first 15s
    and before 60% of the track, then align to the nearest beat within that
    section.

    Returns milliseconds (int).
    """
    sections = audio_analysis.get("sections", [])
    beats = audio_analysis.get("beats", [])
    track = audio_analysis.get("track", {})
    duration = track.get("duration", 0)

    if not sections:
        return 0

    # Filter to sections in the sweet spot: 15s–60% of duration
    window_end = duration * 0.60
    candidates = [
        s for s in sections
        if s.get("start", 0) >= 15 and s.get("start", 0) <= window_end
    ]
    if not candidates:
        candidates = sections

    # Pick highest loudness (proxy for energy drop)
    best = max(candidates, key=lambda s: s.get("loudness", -60))
    target_s = best.get("start", 0)

    # Snap to nearest beat
    if beats:
        nearest = min(beats, key=lambda b: abs(b.get("start", 0) - target_s))
        target_s = nearest.get("start", target_s)

    return int(target_s * 1000)


def auto_match_roster(players: list[dict], catalog_rows: list[dict]) -> dict[str, list[dict]]:
    """Return {player_id: [catalog_row, ...]} suggestions for each player.

    Uses jersey number → tag hints from _NUMBER_TAGS. Falls back to
    top energy-score songs when no number match exists.
    """
    results: dict[str, list[dict]] = {}

    for player in players:
        pid = player.get("id", "")
        number = str(player.get("number", "")).strip()
        hints = _NUMBER_TAGS.get(number, [])

        if hints:
            scored = []
            for row in catalog_rows:
                import json as _json
                tags = row["tags"] if isinstance(row["tags"], list) else _json.loads(row.get("tags", "[]"))
                matches = sum(1 for h in hints if h in tags)
                if matches:
                    scored.append((matches, row))
            scored.sort(key=lambda x: (-x[0], -x[1].get("energy_score", 0)))
            results[pid] = [r for _, r in scored[:5]]
        else:
            top = sorted(catalog_rows, key=lambda r: -r.get("energy_score", 0))
            results[pid] = top[:5]

    return results
