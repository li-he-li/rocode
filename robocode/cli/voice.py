"""Voice input engine — F2 toggle recording, VAD silence detection, faster-whisper STT."""

import enum
import logging
import time
import threading
import numpy as np
from robocode.services.analytics.logger import get_logger

# Suppress faster-whisper/ctranslate2 internal INFO logs
logging.getLogger("faster_whisper").setLevel(logging.WARNING)
logging.getLogger("ctranslate2").setLevel(logging.WARNING)


class VoiceState(enum.Enum):
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    UNAVAILABLE = "unavailable"


try:
    import sounddevice as _sd

    _HAS_SD = True
except ImportError:
    _sd = None
    _HAS_SD = False

try:
    import webrtcvad as _wvad

    _HAS_VAD = True
except ImportError:
    _wvad = None
    _HAS_VAD = False

_HAS_FW = True

try:
    import importlib

    importlib.util.find_spec("faster_whisper")
except (ImportError, ModuleNotFoundError):
    _HAS_FW = False


class VoiceController:
    """Manages voice recording, VAD silence detection, and STT transcription lifecycle.

    Recording is done via sounddevice InputStream in callback mode.
    Audio is captured at the hardware device's native sample rate and resampled
    to 16 kHz for VAD and Whisper processing.
    A background monitor thread checks VAD silence counter and auto-stops
    after 3 seconds of silence. Transcription runs on a thread to avoid
    blocking the audio callback.
    """

    TARGET_RATE = 16000
    FRAME_MS = 30
    SILENCE_S = 3

    def __init__(self, metrics=None):
        self._state = VoiceState.LOADING
        self._lock = threading.Lock()
        self._logger = get_logger("voice")

        self._stream = None
        self._audio_chunks: list[bytes] = []
        self._vad = None
        self._silence_frames = 0
        self._silence_max = int(self.SILENCE_S * 1000 / self.FRAME_MS)

        self._model = None
        self._model_info: dict = {}
        self._on_result = None

        # Device info populated by _detect_mic
        self._input_device_index: int | None = None
        self._input_device_rate: int = self.TARGET_RATE
        self._resample_ratio: int = 1

        # Unified metrics collector (optional)
        self._metrics = metrics

        # Local metrics (always available)
        self._latencies: list[float] = []
        self._confidences: list[float] = []
        self._failures = 0
        self._op_total = 0
        self._op_success = 0

        self._detect_mic()
        if self._mic_ok:
            t = threading.Thread(target=self._load_model, daemon=True, name="voice-model-loader")
            t.start()
        else:
            self._state = VoiceState.UNAVAILABLE
            self._logger.warning("voice_unavailable", reason="no_microphone")

    # ── device / model init ──────────────────────────────────────────

    def _detect_mic(self):
        """Find a working hardware input device. Prefer real devices over PipeWire virtual sinks."""
        if not _HAS_SD:
            self._mic_ok = False
            return
        try:
            devices = _sd.query_devices()
            inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
            if not inputs:
                self._mic_ok = False
                return

            # Score devices: prefer hardware (non-pipewire) with standard rates
            def _score(idx_dev):
                _i, d = idx_dev
                name = d["name"].lower()
                sr = d["default_samplerate"]
                score = 0
                if "pipewire" not in name and "default" not in name:
                    score += 100  # real hardware
                if sr in (16000, 32000, 44100, 48000):
                    score += 50  # standard rate
                if d["max_input_channels"] <= 2:
                    score += 30  # mono/stereo
                return score

            inputs.sort(key=_score, reverse=True)
            # Try devices in score order until one delivers non-zero data
            for idx, d in inputs:
                native_sr = int(d["default_samplerate"])
                # webrtcvad needs one of these rates; pick closest >= 16000
                valid_vad_rates = [8000, 16000, 32000, 48000]
                if native_sr not in valid_vad_rates:
                    continue
                if native_sr % self.TARGET_RATE != 0:
                    continue  # resample ratio must be integer
                try:
                    got_data = []
                    warmup_skipped = 0
                    warmup_max = 10

                    def _test_cb(indata, frames, time_info, status):
                        nonlocal warmup_skipped
                        if warmup_skipped < warmup_max and not np.any(indata != 0):
                            warmup_skipped += 1
                            return
                        got_data.append(indata.copy())
                        if len(got_data) >= 3:
                            raise _sd.CallbackStop()

                    block_sz = native_sr * self.FRAME_MS // 1000
                    with _sd.InputStream(
                        device=idx,
                        samplerate=native_sr,
                        channels=1,
                        dtype="int16",
                        blocksize=block_sz,
                        callback=_test_cb,
                    ):
                        import time as _t

                        _t.sleep(1.5)

                    if got_data and any(np.any(c != 0) for c in got_data):
                        self._input_device_index = idx
                        self._input_device_rate = native_sr
                        self._resample_ratio = native_sr // self.TARGET_RATE
                        self._mic_ok = True
                        self._logger.info(
                            "voice_mic_detected",
                            device=d["name"],
                            rate=native_sr,
                            ratio=self._resample_ratio,
                        )
                        return
                except Exception:
                    continue

            self._mic_ok = False
            self._logger.warning("voice_mic_failed", candidates=len(inputs))
        except Exception:
            self._mic_ok = False

    def _load_model(self):
        if not _HAS_FW:
            with self._lock:
                self._state = VoiceState.UNAVAILABLE
            self._logger.warning("voice_unavailable", reason="faster_whisper_not_installed")
            return
        t0 = time.time()
        try:
            try:
                import torch

                device, compute = (
                    ("cuda", "float16") if torch.cuda.is_available() else ("cpu", "int8")
                )
            except ImportError:
                device, compute = "cpu", "int8"

            from faster_whisper import WhisperModel

            self._model = WhisperModel("small", device=device, compute_type=compute)
            load_ms = (time.time() - t0) * 1000
            self._model_info = {
                "model": "small",
                "device": device,
                "compute_type": compute,
                "load_time_ms": load_ms,
            }
            self._logger.info("voice_model_loaded", **self._model_info)
            with self._lock:
                self._state = VoiceState.READY
        except Exception as e:
            self._logger.error("voice_model_load_failed", error=str(e))
            with self._lock:
                self._state = VoiceState.UNAVAILABLE

    # ── public API ───────────────────────────────────────────────────

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def model_info(self) -> dict:
        return dict(self._model_info)

    def get_metrics(self) -> dict:
        lats = self._latencies
        confs = self._confidences
        return {
            "voice_operations": {
                "total": self._op_total,
                "success": self._op_success,
                "failure": self._failures,
                "avg_latency_ms": round(sum(lats) / len(lats), 1) if lats else 0,
                "avg_confidence": round(sum(confs) / len(confs), 3) if confs else 0,
            }
        }

    def set_on_result(self, callback):
        """Register callback(text: str) invoked when transcription completes."""
        self._on_result = callback

    def start_recording(self) -> bool:
        with self._lock:
            if self._state not in (VoiceState.READY, VoiceState.IDLE):
                return False
            self._state = VoiceState.RECORDING

        self._audio_chunks = []
        self._silence_frames = 0
        if _HAS_VAD:
            self._vad = _wvad.Vad(1)  # mode 1: balanced; mode 2 is too aggressive

        self._rec_start = time.time()

        device_rate = self._input_device_rate
        block_size = device_rate * self.FRAME_MS // 1000
        try:
            self._stream = _sd.InputStream(
                device=self._input_device_index,
                samplerate=device_rate,
                channels=1,
                dtype="int16",
                blocksize=block_size,
                latency=0.2,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as e:
            self._logger.error("voice_recording_start_failed", error=str(e))
            with self._lock:
                self._state = VoiceState.READY
            return False

        self._logger.info(
            "voice_recording_started", device_rate=device_rate, resample_ratio=self._resample_ratio
        )
        threading.Thread(target=self._silence_watch, daemon=True).start()
        return True

    def stop_recording(self, trigger: str = "manual"):
        with self._lock:
            if self._state != VoiceState.RECORDING:
                return
            self._state = VoiceState.TRANSCRIBING

        dur_ms = (time.time() - self._rec_start) * 1000
        self._logger.info("voice_recording_stopped", trigger=trigger, duration_ms=dur_ms)

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._vad = None

        threading.Thread(target=self._transcribe, daemon=True).start()

    def shutdown(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._audio_chunks = []
        self._model = None
        with self._lock:
            self._state = VoiceState.IDLE

    # ── audio callback (called from PortAudio C thread) ──────────────

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self._logger.debug("voice_audio_status", status=str(status))

        # Store raw device-rate bytes; resampling is done in _transcribe
        chunk_bytes = indata.tobytes()
        self._audio_chunks.append(chunk_bytes)

        if self._vad is not None:
            try:
                # webrtcvad supports 8k/16k/32k/48k — use device native rate
                if self._vad.is_speech(chunk_bytes, self._input_device_rate):
                    self._silence_frames = 0
                else:
                    self._silence_frames += 1
            except Exception:
                pass

    # ── silence monitor (background thread) ──────────────────────────

    def _silence_watch(self):
        while self._state == VoiceState.RECORDING:
            time.sleep(0.1)
            if self._vad is not None and self._silence_frames >= self._silence_max:
                self.stop_recording(trigger="silence")
                break

    # ── transcription (background thread) ────────────────────────────

    def _transcribe(self):
        t0 = time.time()
        self._op_total += 1

        try:
            raw = b"".join(self._audio_chunks)
            if len(raw) == 0:
                raise RuntimeError("No audio data")

            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)

            # Resample device native rate → 16 kHz for Whisper
            ratio = self._resample_ratio
            if ratio > 1:
                tail = len(audio) % ratio
                if tail:
                    audio = audio[:-tail]
                audio = audio.reshape(-1, ratio).mean(axis=1)

            audio /= 32768.0

            if self._model is None:
                raise RuntimeError("Model not loaded")

            segments, _info = self._model.transcribe(audio, language="zh", beam_size=5)

            texts, scores = [], []
            for seg in segments:
                texts.append(seg.text)
                scores.append(seg.avg_logprob)

            text = "".join(texts).strip()
            conf = sum(scores) / len(scores) if scores else 0.0
            lat_ms = (time.time() - t0) * 1000

            self._latencies.append(lat_ms)
            self._confidences.append(conf)
            self._op_success += 1
            if self._metrics is not None:
                self._metrics.record_stt_result(lat_ms, conf, True)

            self._logger.info(
                "voice_transcription_completed",
                text_length=len(text),
                latency_ms=lat_ms,
                confidence=conf,
            )

            with self._lock:
                self._state = VoiceState.READY

            if self._on_result:
                self._on_result(text or "")

        except Exception as e:
            lat_ms = (time.time() - t0) * 1000
            self._failures += 1
            if self._metrics is not None:
                self._metrics.record_stt_result(lat_ms, 0.0, False)
            self._logger.error("voice_transcription_failed", error=str(e), duration_ms=lat_ms)
            with self._lock:
                self._state = VoiceState.READY
        finally:
            # Chunks persist until next start_recording() for diagnostics
            pass
