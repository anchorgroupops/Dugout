"""Tests for tools/scorebook_ocr.py — file routing and stub responses."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import unittest.mock as mock
sys.modules.setdefault("pdfplumber", mock.MagicMock())

from scorebook_ocr import process_scorebook, _stub_image


# ─── Image routing ──────────────────────────────────────────────────────────

class TestImageRouting:
    @pytest.mark.parametrize("ext", [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"])
    def test_image_extensions_return_not_implemented(self, ext, tmp_path):
        f = tmp_path / f"game{ext}"
        f.touch()
        result = process_scorebook(f)
        assert result["status"] == "not_implemented"

    def test_image_result_has_required_keys(self, tmp_path):
        f = tmp_path / "game.jpg"
        f.touch()
        result = process_scorebook(f)
        for key in ("status", "reason", "source", "format", "at_bats", "method"):
            assert key in result

    def test_image_at_bats_is_empty_list(self, tmp_path):
        f = tmp_path / "game.png"
        f.touch()
        result = process_scorebook(f)
        assert result["at_bats"] == []

    def test_image_method_is_image_stub(self, tmp_path):
        f = tmp_path / "game.png"
        f.touch()
        result = process_scorebook(f)
        assert result["method"] == "image_stub"

    def test_image_source_is_path_string(self, tmp_path):
        f = tmp_path / "game.jpg"
        f.touch()
        result = process_scorebook(f)
        assert str(f) == result["source"]

    def test_accepts_string_path(self, tmp_path):
        f = tmp_path / "game.jpg"
        f.touch()
        result = process_scorebook(str(f))
        assert result["status"] == "not_implemented"

    def test_image_prints_warning(self, tmp_path, capsys):
        f = tmp_path / "game.png"
        f.touch()
        process_scorebook(f)
        out = capsys.readouterr().out
        assert "not yet implemented" in out.lower() or "ocr" in out.lower()


# ─── Unknown extension ───────────────────────────────────────────────────────

class TestUnknownExtension:
    @pytest.mark.parametrize("ext", [".txt", ".csv", ".docx", ".mp4", ""])
    def test_unsupported_extension_returns_error(self, tmp_path, ext):
        f = tmp_path / f"game{ext}"
        f.touch()
        result = process_scorebook(f)
        assert "error" in result

    def test_error_message_contains_extension(self, tmp_path):
        f = tmp_path / "game.xyz"
        f.touch()
        result = process_scorebook(f)
        assert ".xyz" in result["error"]

    def test_error_result_has_source(self, tmp_path):
        f = tmp_path / "game.xlsx"
        f.touch()
        result = process_scorebook(f)
        assert "source" in result
        assert str(f) == result["source"]


# ─── PDF routing ─────────────────────────────────────────────────────────────

class TestPdfRouting:
    def test_pdf_calls_parse_pdf(self, tmp_path):
        f = tmp_path / "game.pdf"
        f.touch()
        fake_result = {"game_id": "test", "sharks_batting": []}
        with patch("scorebook_ocr._parse_pdf", return_value=fake_result) as mock_parse:
            result = process_scorebook(f)
            mock_parse.assert_called_once_with(f)
            assert result == fake_result

    def test_pdf_internal_exception_returns_error_dict(self, tmp_path):
        f = tmp_path / "game.pdf"
        f.touch()
        with patch("parse_scorebook_pdf.parse_pdf", side_effect=RuntimeError("bad pdf")):
            result = process_scorebook(f)
            assert "error" in result
            assert "bad pdf" in result["error"]

    def test_pdf_parse_pdf_none_returns_error(self, tmp_path):
        f = tmp_path / "game.pdf"
        f.touch()
        with patch("parse_scorebook_pdf.parse_pdf", return_value=None):
            result = process_scorebook(f)
            assert "error" in result

    def test_pdf_method_field_added(self, tmp_path):
        f = tmp_path / "game.pdf"
        f.touch()
        fake_game = {"game_id": "abc", "sharks_batting": [], "opponent_batting": []}
        with patch("parse_scorebook_pdf.parse_pdf", return_value=fake_game):
            result = process_scorebook(f)
            assert result.get("method") == "pdf"

    def test_pdf_source_field_added(self, tmp_path):
        f = tmp_path / "game.pdf"
        f.touch()
        fake_game = {"game_id": "abc"}
        with patch("parse_scorebook_pdf.parse_pdf", return_value=fake_game):
            result = process_scorebook(f)
            assert result.get("source") == str(f)

    def test_pdf_uppercase_extension(self, tmp_path):
        f = tmp_path / "game.PDF"
        f.touch()
        with patch("scorebook_ocr._parse_pdf", return_value={"ok": True}) as mock_parse:
            result = process_scorebook(f)
            mock_parse.assert_called_once()


# ─── stub_image direct ───────────────────────────────────────────────────────

class TestStubImage:
    def test_returns_dict(self, tmp_path):
        f = tmp_path / "img.jpg"
        result = _stub_image(f)
        assert isinstance(result, dict)

    def test_status_not_implemented(self, tmp_path):
        result = _stub_image(tmp_path / "img.png")
        assert result["status"] == "not_implemented"

    def test_reason_is_string(self, tmp_path):
        result = _stub_image(tmp_path / "img.png")
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0


# ─── sys.path.insert branch (line 27) ───────────────────────────────────────

class TestSysPathInsert:
    def test_sys_path_insert_branch_covered(self):
        """Line 27: when _TOOLS_DIR is absent from sys.path, it gets inserted."""
        import importlib
        import tools.scorebook_ocr as soc_tools

        tools_dir = str(soc_tools._TOOLS_DIR)

        # Save original sys.path and sys.modules entries
        original_path = sys.path[:]
        keys_to_remove = [k for k in sys.modules if k in ("tools.scorebook_ocr", "scorebook_ocr")]
        saved_modules = {k: sys.modules.pop(k) for k in keys_to_remove}

        # Remove tools_dir so the insert branch fires
        sys.path[:] = [p for p in sys.path if p != tools_dir]
        try:
            import tools.scorebook_ocr  # noqa: F401 — triggers line 27
            assert tools_dir in sys.path
        finally:
            sys.path[:] = original_path
            sys.modules.update(saved_modules)
