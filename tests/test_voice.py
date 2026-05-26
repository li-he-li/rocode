"""Voice controller tests — state machine, VAD simulation, callback mechanism."""

import sys
import time
import pytest
from unittest.mock import MagicMock


# ── VoiceState enum ───────────────────────────────────────────────────


class TestVoiceState:
    def test_all_states_exist(self):
        from robocode.cli.voice import VoiceState

        states = {s.value for s in VoiceState}
        assert "idle" in states
        assert "loading" in states
        assert "ready" in states
        assert "recording" in states
        assert "transcribing" in states
        assert "unavailable" in states

    def test_state_uniqueness(self):
        from robocode.cli.voice import VoiceState

        values = [s.value for s in VoiceState]
        assert len(values) == len(set(values))


# ── VoiceController — without optional deps ───────────────────────────


class TestVoiceControllerNoDeps:
    """VoiceController without sounddevice/faster-whisper/webrtcvad installed."""

    @pytest.fixture(autouse=True)
    def _ensure_no_voice_deps(self, monkeypatch):
        """Patch voice module flags so VoiceController uses the no-dep path."""
        import robocode.cli.voice as voice_mod

        monkeypatch.setattr(voice_mod, "_HAS_SD", False)
        monkeypatch.setattr(voice_mod, "_HAS_FW", False)
        monkeypatch.setattr(voice_mod, "_HAS_VAD", False)

    def test_init_without_deps_is_unavailable(self):
        from robocode.cli.voice import VoiceController, VoiceState

        vc = VoiceController()
        assert vc.state == VoiceState.UNAVAILABLE

    def test_model_info_empty_when_unavailable(self):
        from robocode.cli.voice import VoiceController

        vc = VoiceController()
        assert vc.model_info == {}

    def test_metrics_zero_when_unavailable(self):
        from robocode.cli.voice import VoiceController

        vc = VoiceController()
        m = vc.get_metrics()
        vo = m["voice_operations"]
        assert vo["total"] == 0
        assert vo["success"] == 0
        assert vo["failure"] == 0
        assert vo["avg_latency_ms"] == 0
        assert vo["avg_confidence"] == 0

    def test_start_recording_rejected_when_unavailable(self):
        from robocode.cli.voice import VoiceController

        vc = VoiceController()
        ok = vc.start_recording()
        assert ok is False

    def test_stop_recording_noop_when_not_recording(self):
        from robocode.cli.voice import VoiceController

        vc = VoiceController()
        # Should not raise
        vc.stop_recording(trigger="f2")

    def test_set_on_result_stores_callback(self):
        from robocode.cli.voice import VoiceController

        vc = VoiceController()
        results = []

        def cb(text):
            results.append(text)

        vc.set_on_result(cb)
        # Verify callback is stored (check via _on_result attribute)
        assert vc._on_result is cb

    def test_shutdown_noop_when_no_stream(self):
        from robocode.cli.voice import VoiceController

        vc = VoiceController()
        # Should not raise
        vc.shutdown()


# ── VoiceController — with mocked deps ────────────────────────────────


class MockInputStream:
    """Fake sounddevice InputStream — produces non-zero audio for mic detection."""

    def __init__(self, **kwargs):
        self.samplerate = kwargs.get("samplerate", 16000)
        self.callback = kwargs.get("callback")
        self._active = True

    def start(self):
        self._active = True

    def stop(self):
        self._active = False

    def close(self):
        self._active = False

    @property
    def active(self):
        return self._active

    def __enter__(self):
        self._active = True
        if self.callback:
            import numpy as np

            fake_audio = np.ones((1024, 1), dtype=np.int16)
            for _ in range(5):
                try:
                    self.callback(fake_audio, 1024, None, None)
                except Exception:
                    break
        return self

    def __exit__(self, *args):
        self._active = False


class MockVad:
    """Fake webrtcvad with configurable speech detection."""

    def __init__(self, mode=2):
        self.mode = mode
        self._always_speech = True

    def is_speech(self, buf, sample_rate):
        return self._always_speech


class TestVoiceControllerWithMocks:
    """VoiceController with mocked optional dependencies."""

    @pytest.fixture
    def mock_deps(self):
        """Inject mock sounddevice, webrtcvad, faster_whisper into sys.modules."""

        mock_sd = MagicMock()
        mock_sd.InputStream = MockInputStream
        mock_sd.query_devices = MagicMock(
            return_value=[
                {"name": "fake_mic", "max_input_channels": 1, "default_samplerate": 16000}
            ]
        )

        mock_wvad = MagicMock()
        mock_wvad.Vad = MockVad

        mock_fw = MagicMock()
        mock_fw.WhisperModel = MagicMock()

        # Mock torch with CUDA
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        stored = {}
        for name, mod in [
            ("sounddevice", mock_sd),
            ("webrtcvad", mock_wvad),
            ("faster_whisper", mock_fw),
            ("torch", mock_torch),
        ]:
            if name in sys.modules:
                stored[name] = sys.modules[name]
            sys.modules[name] = mod

        yield {"sd": mock_sd, "vad": mock_wvad, "fw": mock_fw, "torch": mock_torch}

        # Restore
        for name in ("sounddevice", "webrtcvad", "faster_whisper", "torch"):
            if name in stored:
                sys.modules[name] = stored[name]
            elif name in sys.modules:
                del sys.modules[name]

    @pytest.fixture
    def vc_ready(self, mock_deps):
        """VoiceController that finishes model loading (READY state)."""
        from robocode.cli.voice import VoiceController, VoiceState

        # Force reimport to pick up mocked modules
        import robocode.cli.voice as voice_mod

        # Patch the module-level flags
        voice_mod._HAS_SD = True
        voice_mod._HAS_FW = True
        voice_mod._HAS_VAD = True
        voice_mod._sd = mock_deps["sd"]
        voice_mod._wvad = mock_deps["vad"]
        voice_mod._WhisperModel = mock_deps["fw"].WhisperModel

        vc = VoiceController()

        # Model loading runs in background thread — wait briefly
        time.sleep(0.1)
        # Manually set to READY for deterministic testing
        vc._model = object()  # fake model
        vc._state = VoiceState.READY
        return vc

    def test_init_detects_mic_and_starts_loading(self, mock_deps):
        """With deps available, mic detected, model loading starts."""
        import robocode.cli.voice as voice_mod

        voice_mod._HAS_SD = True
        voice_mod._HAS_FW = True
        voice_mod._HAS_VAD = True
        voice_mod._sd = mock_deps["sd"]
        voice_mod._wvad = mock_deps["vad"]
        voice_mod._WhisperModel = mock_deps["fw"].WhisperModel

        from robocode.cli.voice import VoiceController, VoiceState

        vc = VoiceController()
        # Model loading runs in background — LOADING or already READY (mock races fast)
        assert vc.state in (VoiceState.LOADING, VoiceState.READY)
        # Mic should be detected
        assert vc._mic_ok is True

    def test_start_recording_sets_recording_state(self, vc_ready):
        from robocode.cli.voice import VoiceState

        ok = vc_ready.start_recording()
        assert ok is True
        assert vc_ready.state == VoiceState.RECORDING

    def test_stop_recording_changes_state_to_transcribing(self, vc_ready):
        from robocode.cli.voice import VoiceState

        vc_ready.start_recording()
        vc_ready.stop_recording(trigger="f2")
        # After stop_recording, the state is TRANSCRIBING (then transcribe
        # thread sets it back to READY on completion or error).
        # Since model is a MagicMock and transcribe will fail, wait briefly.
        time.sleep(0.2)
        # After failed transcribe, should be back to READY
        assert vc_ready.state == VoiceState.READY

    def test_start_recording_rejected_when_recording(self, vc_ready):
        vc_ready.start_recording()
        # Second start should be rejected
        ok = vc_ready.start_recording()
        assert ok is False

    def test_stop_recording_noop_when_not_recording(self, vc_ready):
        from robocode.cli.voice import VoiceState

        vc_ready.stop_recording(trigger="f2")
        # State should still be READY (start_recording was never called)
        assert vc_ready.state == VoiceState.READY

    def test_callback_fires_on_transcription(self, vc_ready):
        """When transcription completes, the on_result callback is invoked."""
        import numpy as np

        results = []

        def cb(text):
            results.append(text)

        vc_ready.set_on_result(cb)
        vc_ready.start_recording()

        # Feed fake audio
        fake_audio = (np.ones(480, dtype=np.int16) * 100).tobytes()
        vc_ready._audio_chunks = [fake_audio]
        vc_ready._vad = None  # No VAD needed

        # Directly call _transcribe with a mock model
        mock_segment = MagicMock()
        mock_segment.text = "测试指令"
        mock_segment.avg_logprob = -0.5

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            iter([mock_segment]),
            MagicMock(),
        )
        vc_ready._model = mock_model

        vc_ready.stop_recording(trigger="f2")
        time.sleep(0.3)

        assert len(results) == 1
        assert results[0] == "测试指令"

    def test_metrics_updated_on_successful_transcription(self, vc_ready):
        import numpy as np

        vc_ready.start_recording()

        fake_audio = (np.ones(480, dtype=np.int16) * 100).tobytes()
        vc_ready._audio_chunks = [fake_audio]
        vc_ready._vad = None

        mock_segment = MagicMock()
        mock_segment.text = "移动机械臂"
        mock_segment.avg_logprob = -0.3

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_segment]), MagicMock())
        vc_ready._model = mock_model

        vc_ready.stop_recording(trigger="silence")
        time.sleep(0.3)

        m = vc_ready.get_metrics()
        vo = m["voice_operations"]
        assert vo["total"] == 1
        assert vo["success"] == 1
        assert vo["failure"] == 0

    def test_metrics_count_failures(self, vc_ready):
        """When transcription raises, failure is counted."""
        import numpy as np

        vc_ready.start_recording()

        fake_audio = (np.ones(480, dtype=np.int16) * 100).tobytes()
        vc_ready._audio_chunks = [fake_audio]
        vc_ready._vad = None

        # Model that raises on transcribe
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("STT failed")
        vc_ready._model = mock_model

        vc_ready.stop_recording(trigger="f2")
        time.sleep(0.3)

        m = vc_ready.get_metrics()
        vo = m["voice_operations"]
        assert vo["total"] == 1
        assert vo["success"] == 0
        assert vo["failure"] == 1

    def test_shutdown_cleans_up_stream(self, vc_ready):
        from robocode.cli.voice import VoiceState

        vc_ready.start_recording()
        assert vc_ready._stream is not None

        vc_ready.shutdown()
        assert vc_ready.state == VoiceState.IDLE
        assert vc_ready._stream is None
        assert vc_ready._audio_chunks == []

    def test_get_metrics_avg_calculation(self, vc_ready):
        """Verify avg_latency_ms and avg_confidence are correctly computed."""
        vc_ready._latencies = [100.0, 200.0, 300.0]
        vc_ready._confidences = [0.8, 0.9, 0.85]
        vc_ready._op_total = 3
        vc_ready._op_success = 3

        m = vc_ready.get_metrics()
        vo = m["voice_operations"]
        assert vo["avg_latency_ms"] == 200.0
        assert vo["avg_confidence"] == 0.85

    def test_get_metrics_empty_no_division_by_zero(self, vc_ready):
        vc_ready._latencies = []
        vc_ready._confidences = []

        m = vc_ready.get_metrics()
        vo = m["voice_operations"]
        assert vo["avg_latency_ms"] == 0
        assert vo["avg_confidence"] == 0
