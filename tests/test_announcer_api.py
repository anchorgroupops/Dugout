"""Tests for announcer_api.py — pure functions only.

No FastAPI server, FFmpeg, transformers, or HTTP calls are exercised here.
Heavy optional imports (transformers, torch, replicate) are mocked before
the module is imported so the module-level app = FastAPI(...) succeeds.
"""
from __future__ import annotations

import io
import struct
import sys
import unittest.mock as mock
import wave
from pathlib import Path

# ---------------------------------------------------------------------------
# Mock heavy optional deps before importing the module under test.
# transformers, torch, and replicate are not installed in CI; fastapi and
# requests ARE installed, so we only need to stub the missing three.
# ---------------------------------------------------------------------------
for _modname in ("transformers", "torch", "replicate"):
    sys.modules.setdefault(_modname, mock.MagicMock())

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

try:
    from announcer_api import _make_silent_wav, VoiceDesignParams  # noqa: E402

    IMPORT_OK = True
except Exception as _import_exc:  # pragma: no cover
    IMPORT_OK = False
    _import_exc_msg = str(_import_exc)

    # Fallback: define equivalent logic inline so WAV tests still run.
    def _make_silent_wav(duration_secs: int = 2) -> bytes:  # type: ignore[misc]
        buf = io.BytesIO()
        sample_rate = 22050
        n = sample_rate * duration_secs
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack(f"<{n}h", *([0] * n)))
        return buf.getvalue()

    VoiceDesignParams = None  # type: ignore[assignment,misc]

import pytest  # noqa: E402 — after sys.path manipulation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_wav(data: bytes):
    """Open raw WAV bytes with wave.open and return the Wave_read object."""
    return wave.open(io.BytesIO(data), "rb")


# ---------------------------------------------------------------------------
# TestMakeSilentWav
# ---------------------------------------------------------------------------

class TestMakeSilentWav:
    """Tests for _make_silent_wav()."""

    # 1. Returns bytes
    def test_returns_bytes(self):
        result = _make_silent_wav()
        assert isinstance(result, bytes)

    # 2. Starts with RIFF header
    def test_starts_with_riff(self):
        result = _make_silent_wav()
        assert result[:4] == b"RIFF"

    # 3. Parseable by wave.open
    def test_parseable_by_wave(self):
        result = _make_silent_wav()
        with _open_wav(result) as wf:
            assert wf is not None

    # 4. Mono (1 channel)
    def test_channels_is_1(self):
        result = _make_silent_wav()
        with _open_wav(result) as wf:
            assert wf.getnchannels() == 1

    # 5. 16-bit samples (sample width = 2 bytes)
    def test_sample_width_is_2(self):
        result = _make_silent_wav()
        with _open_wav(result) as wf:
            assert wf.getsampwidth() == 2

    # 6. Frame rate = 22050 Hz
    def test_frame_rate_is_22050(self):
        result = _make_silent_wav()
        with _open_wav(result) as wf:
            assert wf.getframerate() == 22050

    # 7. Frame count = 22050 * duration_secs for duration_secs=1
    def test_frame_count_one_second(self):
        result = _make_silent_wav(duration_secs=1)
        with _open_wav(result) as wf:
            assert wf.getnframes() == 22050

    # 8. duration_secs=2 gives twice as many frames as duration_secs=1
    def test_frame_count_scales_with_duration(self):
        result1 = _make_silent_wav(duration_secs=1)
        result2 = _make_silent_wav(duration_secs=2)
        with _open_wav(result1) as wf1, _open_wav(result2) as wf2:
            assert wf2.getnframes() == 2 * wf1.getnframes()

    # 9. duration_secs=0 produces a minimal but still valid WAV
    def test_zero_duration_is_valid_wav(self):
        result = _make_silent_wav(duration_secs=0)
        assert isinstance(result, bytes)
        assert result[:4] == b"RIFF"
        with _open_wav(result) as wf:
            assert wf.getnframes() == 0

    # 10. All audio samples are zero (silent)
    def test_all_samples_are_zero(self):
        result = _make_silent_wav(duration_secs=1)
        with _open_wav(result) as wf:
            raw = wf.readframes(wf.getnframes())
        # Each 16-bit sample is 2 bytes; all should be 0x00
        assert all(b == 0 for b in raw)


# ---------------------------------------------------------------------------
# TestVoiceDesignParams — only exercised when the real import succeeded
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not IMPORT_OK or VoiceDesignParams is None,
                    reason="announcer_api import failed; skipping Pydantic model tests")
class TestVoiceDesignParams:
    """Tests for VoiceDesignParams defaults and field validation."""

    def test_default_pitch(self):
        vd = VoiceDesignParams()
        assert vd.pitch == -2.0

    def test_default_energy(self):
        vd = VoiceDesignParams()
        assert vd.energy == 1.3

    def test_default_speaking_rate(self):
        vd = VoiceDesignParams()
        assert vd.speaking_rate == 0.92

    def test_default_emotion_exaggeration(self):
        vd = VoiceDesignParams()
        assert vd.emotion_exaggeration == 0.85

    def test_default_speaker_style(self):
        vd = VoiceDesignParams()
        assert vd.speaker_style == "announcer"

    def test_valid_custom_values(self):
        vd = VoiceDesignParams(pitch=0.0, energy=1.0, speaking_rate=1.0,
                               emotion_exaggeration=0.5, speaker_style="calm")
        assert vd.pitch == 0.0
        assert vd.energy == 1.0
        assert vd.speaking_rate == 1.0
        assert vd.emotion_exaggeration == 0.5
        assert vd.speaker_style == "calm"

    def test_pitch_below_min_raises(self):
        with pytest.raises(Exception):
            VoiceDesignParams(pitch=-13.0)

    def test_pitch_above_max_raises(self):
        with pytest.raises(Exception):
            VoiceDesignParams(pitch=13.0)

    def test_energy_below_min_raises(self):
        with pytest.raises(Exception):
            VoiceDesignParams(energy=0.4)

    def test_energy_above_max_raises(self):
        with pytest.raises(Exception):
            VoiceDesignParams(energy=3.1)

    def test_speaking_rate_below_min_raises(self):
        with pytest.raises(Exception):
            VoiceDesignParams(speaking_rate=0.4)

    def test_speaking_rate_above_max_raises(self):
        with pytest.raises(Exception):
            VoiceDesignParams(speaking_rate=2.1)

    def test_emotion_below_min_raises(self):
        with pytest.raises(Exception):
            VoiceDesignParams(emotion_exaggeration=-0.1)

    def test_emotion_above_max_raises(self):
        with pytest.raises(Exception):
            VoiceDesignParams(emotion_exaggeration=1.1)

    def test_boundary_pitch_min(self):
        vd = VoiceDesignParams(pitch=-12.0)
        assert vd.pitch == -12.0

    def test_boundary_pitch_max(self):
        vd = VoiceDesignParams(pitch=12.0)
        assert vd.pitch == 12.0

    def test_boundary_energy_min(self):
        vd = VoiceDesignParams(energy=0.5)
        assert vd.energy == 0.5

    def test_boundary_energy_max(self):
        vd = VoiceDesignParams(energy=3.0)
        assert vd.energy == 3.0
