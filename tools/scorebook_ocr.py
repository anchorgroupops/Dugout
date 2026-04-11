"""
Scorebook OCR module for the GameChanger CSV ingestion pipeline.

Parses a scorebook file (PDF or image) into at-bat sequence data.

Supported formats:
  - PDF: fully implemented via pdfplumber + parse_scorebook_pdf.py
  - Images (.jpg, .png, etc.): stub — gracefully returns a not_implemented
    response. Full image OCR requires pytesseract + the tesseract system binary.

Usage:
    from scorebook_ocr import process_scorebook
    result = process_scorebook("Scorebooks/game1.pdf")
    if result and "error" not in result and result.get("status") != "not_implemented":
        print(result["sharks_batting"])

    python tools/scorebook_ocr.py <path>  # CLI usage
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
_PDF_EXTENSIONS = {".pdf"}


def process_scorebook(path: str | Path) -> dict:
    """
    Parse a scorebook file into at-bat sequence data.

    Args:
        path: Path to a PDF or image scorebook file.

    Returns:
        For PDF: game data dict with keys: game_id, sharks_batting, opponent_batting, ...
        For image: {"status": "not_implemented", "reason": ..., "at_bats": [], ...}
        On error: {"error": ..., "source": ...}
    """
    path = Path(path)
    ext = path.suffix.lower()

    if ext in _PDF_EXTENSIONS:
        return _parse_pdf(path)
    elif ext in _IMAGE_EXTENSIONS:
        return _stub_image(path)
    else:
        return {"error": f"Unsupported file format: '{ext}'", "source": str(path)}


def _parse_pdf(path: Path) -> dict:
    """Parse a PDF scorebook via parse_scorebook_pdf.parse_pdf()."""
    try:
        from parse_scorebook_pdf import parse_pdf

        result = parse_pdf(path)
        if result is None:
            return {
                "error": "PDF parsed but no game data extracted",
                "source": str(path),
                "method": "pdf",
            }
        result["method"] = "pdf"
        result["source"] = str(path)
        return result
    except Exception as exc:
        return {"error": str(exc), "source": str(path), "method": "pdf"}


def _stub_image(path: Path) -> dict:
    """
    Stub for image-based scorebook OCR.

    Returns a clear not_implemented response so the pipeline can degrade
    gracefully. Full image OCR requires:
      1. pip install pytesseract Pillow
      2. System binary: apt-get install tesseract-ocr  (or brew install tesseract)
    """
    print(
        f"[SCOREBOOK OCR] Image OCR not yet implemented for '{path.name}'. "
        "Full image OCR requires pytesseract + the tesseract system binary. "
        "Use a PDF scorebook or implement image OCR to enable this feature."
    )
    return {
        "status": "not_implemented",
        "reason": (
            "Image OCR requires pytesseract + tesseract system binary. "
            "Not yet installed. Use a PDF scorebook instead."
        ),
        "source": str(path),
        "format": "image",
        "at_bats": [],
        "method": "image_stub",
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/scorebook_ocr.py <path>")
        sys.exit(1)
    result = process_scorebook(sys.argv[1])
    print(json.dumps(result, indent=2))
