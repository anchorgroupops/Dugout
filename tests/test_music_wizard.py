"""Tests for music_wizard.py — find_optimal_start_ms, auto_match_roster,
WALKUP_CATALOG structure, and seed_catalog."""

import sys
import sqlite3
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from music_wizard import find_optimal_start_ms, auto_match_roster, WALKUP_CATALOG, seed_catalog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn():
    """Return a fresh in-memory SQLite connection with the walkup_catalog table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE walkup_catalog (
        rank INTEGER PRIMARY KEY, title TEXT, artist TEXT,
        spotify_id TEXT, apple_id TEXT, optimal_start_ms INTEGER,
        duration_ms INTEGER, energy_score REAL, tags TEXT
    )""")
    conn.commit()
    return conn


def _catalog_rows():
    """Return a small subset of WALKUP_CATALOG with tags as lists (in-memory form)."""
    return [dict(r) for r in WALKUP_CATALOG]


# ---------------------------------------------------------------------------
# TestFindOptimalStartMs
# ---------------------------------------------------------------------------

class TestFindOptimalStartMs:

    def test_empty_sections_returns_zero(self):
        analysis = {"sections": [], "beats": [], "track": {"duration": 300}}
        assert find_optimal_start_ms(analysis) == 0

    def test_picks_highest_loudness_in_window(self):
        # Duration 200 s → window_end = 120 s.  Section at 60 s is loudest in
        # the 15 s–120 s window, so it should win over the louder-but-too-late
        # section at 150 s.
        analysis = {
            "sections": [
                {"start": 5,   "loudness": -3.0},   # before 15 s → excluded from window
                {"start": 60,  "loudness": -4.0},   # in window
                {"start": 90,  "loudness": -6.0},   # in window, quieter
                {"start": 150, "loudness": -1.0},   # after 60% → excluded from window
            ],
            "beats": [],
            "track": {"duration": 200},
        }
        result = find_optimal_start_ms(analysis)
        assert result == 60_000  # 60 s * 1000

    def test_snaps_to_nearest_beat(self):
        # Best section starts at 60 s.  Two beats at 59 s and 62 s → 59 is nearer.
        analysis = {
            "sections": [{"start": 60, "loudness": -2.0}],
            "beats": [{"start": 59}, {"start": 62}],
            "track": {"duration": 200},
        }
        result = find_optimal_start_ms(analysis)
        assert result == 59_000

    def test_snaps_to_nearer_later_beat(self):
        # Beat at 61 s is nearer to 60 s than the one at 57 s.
        analysis = {
            "sections": [{"start": 60, "loudness": -2.0}],
            "beats": [{"start": 57}, {"start": 61}],
            "track": {"duration": 200},
        }
        result = find_optimal_start_ms(analysis)
        assert result == 61_000

    def test_fallback_to_all_sections_when_no_candidates_in_window(self):
        # Duration 20 s → window is 15 s–12 s, which is empty.
        # Only section is at 5 s (before 15 s), so fallback fires and picks it.
        analysis = {
            "sections": [{"start": 5, "loudness": -3.0}],
            "beats": [],
            "track": {"duration": 20},
        }
        result = find_optimal_start_ms(analysis)
        assert result == 5_000

    def test_no_beats_uses_raw_section_start(self):
        analysis = {
            "sections": [
                {"start": 30, "loudness": -5.0},
                {"start": 45, "loudness": -3.0},
            ],
            "beats": [],
            "track": {"duration": 200},
        }
        result = find_optimal_start_ms(analysis)
        assert result == 45_000

    def test_returns_int_not_float(self):
        analysis = {
            "sections": [{"start": 30.7, "loudness": -4.0}],
            "beats": [{"start": 30.5}],
            "track": {"duration": 200},
        }
        result = find_optimal_start_ms(analysis)
        assert isinstance(result, int)

    def test_missing_track_key_treated_as_zero_duration(self):
        # With duration=0, window_end=0, so no section passes the window filter
        # (section at 20 s is after 15 s but also after 0 s which is the end).
        # Fallback fires; the single section is selected.
        analysis = {
            "sections": [{"start": 20, "loudness": -5.0}],
            "beats": [],
        }
        result = find_optimal_start_ms(analysis)
        assert result == 20_000


# ---------------------------------------------------------------------------
# TestAutoMatchRoster
# ---------------------------------------------------------------------------

class TestAutoMatchRoster:

    def test_empty_players_returns_empty_dict(self):
        assert auto_match_roster([], _catalog_rows()) == {}

    def test_player_with_no_number_gets_top_5_by_energy(self):
        players = [{"id": "p1", "name": "Alice"}]  # no 'number' key
        result = auto_match_roster(players, _catalog_rows())
        assert "p1" in result
        suggestions = result["p1"]
        assert len(suggestions) == 5
        # Verify they are ordered by energy_score descending
        scores = [s["energy_score"] for s in suggestions]
        assert scores == sorted(scores, reverse=True)

    def test_player_with_number_zero_falls_back_to_top_energy(self):
        # "0" is not in _NUMBER_TAGS, so hints is [] → energy fallback
        players = [{"id": "p2", "number": 0}]
        result = auto_match_roster(players, _catalog_rows())
        suggestions = result["p2"]
        assert len(suggestions) <= 5
        scores = [s["energy_score"] for s in suggestions]
        assert scores == sorted(scores, reverse=True)

    def test_player_with_number_that_has_hints_gets_tag_matched_songs(self):
        # Jersey "4" → hints ["power", "aggressive"]
        players = [{"id": "p3", "number": 4}]
        result = auto_match_roster(players, _catalog_rows())
        suggestions = result["p3"]
        assert len(suggestions) >= 1
        # Every returned song must contain at least one hint tag
        for song in suggestions:
            tags = song["tags"] if isinstance(song["tags"], list) else json.loads(song["tags"])
            assert any(h in tags for h in ["power", "aggressive"]), (
                f"Song '{song['title']}' lacks required tags; got {tags}"
            )

    def test_result_values_are_lists(self):
        players = [{"id": "p4", "number": 7}]
        result = auto_match_roster(players, _catalog_rows())
        for pid, val in result.items():
            assert isinstance(val, list), f"Expected list for {pid}, got {type(val)}"

    def test_result_capped_at_5_suggestions_per_player(self):
        # Use multiple players with different numbers
        players = [
            {"id": "pA", "number": 1},
            {"id": "pB", "number": 5},
            {"id": "pC"},   # no number → top-energy fallback
        ]
        result = auto_match_roster(players, _catalog_rows())
        for pid, suggestions in result.items():
            assert len(suggestions) <= 5, f"{pid} has {len(suggestions)} suggestions (max 5)"

    def test_multiple_players_all_present_in_result(self):
        players = [
            {"id": "x1", "number": 10},
            {"id": "x2", "number": 99},  # not in _NUMBER_TAGS → fallback
            {"id": "x3"},
        ]
        result = auto_match_roster(players, _catalog_rows())
        assert set(result.keys()) == {"x1", "x2", "x3"}

    def test_empty_catalog_returns_empty_suggestions(self):
        players = [{"id": "p5", "number": 6}]
        result = auto_match_roster(players, [])
        assert result["p5"] == []

    def test_player_id_defaults_to_empty_string_when_missing(self):
        players = [{"number": 3}]  # no 'id' key
        result = auto_match_roster(players, _catalog_rows())
        assert "" in result


# ---------------------------------------------------------------------------
# TestWalkupCatalog
# ---------------------------------------------------------------------------

class TestWalkupCatalog:

    def test_has_at_least_10_entries(self):
        assert len(WALKUP_CATALOG) >= 10

    def test_each_entry_has_required_keys(self):
        for entry in WALKUP_CATALOG:
            for key in ("rank", "title", "artist"):
                assert key in entry, f"Missing '{key}' in entry: {entry}"

    def test_ranks_are_unique(self):
        ranks = [e["rank"] for e in WALKUP_CATALOG]
        assert len(ranks) == len(set(ranks)), "Duplicate rank values found"

    def test_energy_score_between_0_and_1(self):
        for entry in WALKUP_CATALOG:
            score = entry.get("energy_score")
            assert score is not None, f"Missing energy_score in rank {entry['rank']}"
            assert 0.0 <= score <= 1.0, (
                f"energy_score {score} out of range [0,1] for rank {entry['rank']}"
            )

    def test_tags_is_list(self):
        for entry in WALKUP_CATALOG:
            assert isinstance(entry.get("tags"), list), (
                f"tags is not a list for rank {entry['rank']}"
            )

    def test_titles_are_non_empty_strings(self):
        for entry in WALKUP_CATALOG:
            assert isinstance(entry["title"], str) and entry["title"].strip(), (
                f"Empty/invalid title at rank {entry['rank']}"
            )

    def test_artists_are_non_empty_strings(self):
        for entry in WALKUP_CATALOG:
            assert isinstance(entry["artist"], str) and entry["artist"].strip(), (
                f"Empty/invalid artist at rank {entry['rank']}"
            )


# ---------------------------------------------------------------------------
# TestSeedCatalog
# ---------------------------------------------------------------------------

class TestSeedCatalog:

    def test_returns_count_equal_to_catalog_length(self):
        conn = _make_conn()
        count = seed_catalog(conn)
        assert count == len(WALKUP_CATALOG)

    def test_calling_twice_does_not_error(self):
        conn = _make_conn()
        seed_catalog(conn)
        count2 = seed_catalog(conn)
        # ON CONFLICT DO UPDATE still counts each row
        assert count2 == len(WALKUP_CATALOG)

    def test_data_is_readable_back_from_db(self):
        conn = _make_conn()
        seed_catalog(conn)
        conn.commit()

        rows = conn.execute(
            "SELECT rank, title, artist FROM walkup_catalog ORDER BY rank"
        ).fetchall()
        assert len(rows) == len(WALKUP_CATALOG)

        catalog_by_rank = {e["rank"]: e for e in WALKUP_CATALOG}
        for rank, title, artist in rows:
            expected = catalog_by_rank[rank]
            assert title == expected["title"], f"Title mismatch at rank {rank}"
            assert artist == expected["artist"], f"Artist mismatch at rank {rank}"

    def test_energy_score_persisted_correctly(self):
        conn = _make_conn()
        seed_catalog(conn)
        conn.commit()

        rows = conn.execute(
            "SELECT rank, energy_score FROM walkup_catalog"
        ).fetchall()
        catalog_by_rank = {e["rank"]: e for e in WALKUP_CATALOG}
        for rank, energy_score in rows:
            expected_score = catalog_by_rank[rank].get("energy_score", 0.0)
            assert abs(energy_score - expected_score) < 1e-9, (
                f"energy_score mismatch at rank {rank}: got {energy_score}, "
                f"expected {expected_score}"
            )

    def test_tags_stored_as_json_string(self):
        conn = _make_conn()
        seed_catalog(conn)
        conn.commit()

        row = conn.execute(
            "SELECT tags FROM walkup_catalog WHERE rank = 1"
        ).fetchone()
        assert row is not None
        tags = json.loads(row[0])
        assert isinstance(tags, list)
        expected_tags = next(e["tags"] for e in WALKUP_CATALOG if e["rank"] == 1)
        assert tags == expected_tags

    def test_upsert_updates_existing_row(self):
        conn = _make_conn()
        seed_catalog(conn)
        conn.commit()

        # Manually corrupt rank=1's title, then re-seed; upsert should fix it
        conn.execute("UPDATE walkup_catalog SET title='CORRUPTED' WHERE rank=1")
        conn.commit()

        seed_catalog(conn)
        conn.commit()

        title = conn.execute(
            "SELECT title FROM walkup_catalog WHERE rank=1"
        ).fetchone()[0]
        expected_title = next(e["title"] for e in WALKUP_CATALOG if e["rank"] == 1)
        assert title == expected_title

    def test_total_row_count_matches_after_double_seed(self):
        conn = _make_conn()
        seed_catalog(conn)
        seed_catalog(conn)
        conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM walkup_catalog").fetchone()[0]
        assert total == len(WALKUP_CATALOG)
