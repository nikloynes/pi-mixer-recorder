"""Audio recording functionality."""

import queue
import subprocess
import time
import traceback
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread

import pyaudio
from loguru import logger

from pi_rec.config import get_settings
from pi_rec.dropbox_uploader import DropboxUploader

settings = get_settings()

# Monitoring constants
STATS_LOG_INTERVAL_SECONDS = 10
HEALTH_CHECK_INTERVAL_SECONDS = 30
CALLBACK_TIMEOUT_SECONDS = 5
QUEUE_SIZE_WARNING_THRESHOLD = 100


@dataclass
class RecordingStats:
    """Statistics for the current recording session."""

    start_time: float = 0.0
    frames_recorded: int = 0
    bytes_written: int = 0
    callback_count: int = 0
    overflow_count: int = 0
    underflow_count: int = 0
    queue_max_size: int = 0
    last_callback_time: float = 0.0
    errors: list[str] = field(default_factory=list)
    current_file: Path | None = None

    def get_duration_seconds(self) -> float:
        """Get recording duration in seconds."""
        if self.start_time == 0:
            return 0.0
        return time.time() - self.start_time

    def get_recording_info(self) -> dict:
        """Get recording information as dict."""
        return {
            "duration_seconds": self.get_duration_seconds(),
            "frames_recorded": self.frames_recorded,
            "bytes_written": self.bytes_written,
            "callback_count": self.callback_count,
            "overflow_count": self.overflow_count,
            "underflow_count": self.underflow_count,
            "queue_max_size": self.queue_max_size,
            "current_file": str(self.current_file) if self.current_file else None,
            "file_size_mb": (
                round(self.current_file.stat().st_size / (1024 * 1024), 2)
                if self.current_file and self.current_file.exists()
                else 0
            ),
            "errors": self.errors[-5:],  # Last 5 errors
        }


class DeviceIndexError(Exception):
    """Raise when missing a device index in config/settings."""


class AudioRecorder:
    """Handles audio recording from USB audio interface."""

    def __init__(self, uploader: DropboxUploader | None = None) -> None:
        """
        Initialise audio recorder.

        Args:
            uploader: DropboxUploader instance (optional)

        """
        self.uploader = uploader
        self.is_recording = False
        self.recording_thread: Thread | None = None
        self.monitoring_thread: Thread | None = None
        self.stop_event = Event()
        self.stats = RecordingStats()
        self.stats_lock = Lock()

        # init pyaudio
        self.audio = pyaudio.PyAudio()
        self._log_audio_devices()

        # query device info for defaults
        self.device_index: int | None = settings.audio.device_index
        self.device_name: str | None = settings.audio.device_name
        self.device_info: dict | None = None

        if self.device_index is None:
            logger.error("No audio device index is specified in the config.")
            idx_missing = (
                "No device index found. Run `aplay -l` and "
                " add your device's index to `config.yaml`."
            )
            raise DeviceIndexError(idx_missing)

        ready = False
        while not ready:
            ready = self._wait_for_device()
            if not ready:
                logger.warning("unable to find the right usb device, rescanning.")
                self._rescan_usb_devices()
        try:
            device_info = self.audio.get_device_info_by_index(
                self.device_index if self.device_index is not None else -1
            )
            self.device_info = device_info
            queried_sample_rate = int(
                device_info.get("defaultSampleRate", settings.audio.sample_rate)
            )
            if queried_sample_rate != settings.audio.sample_rate:
                logger.warning(
                    f"Config sample rate is {settings.audio.sample_rate}, but device "
                    f"default is {queried_sample_rate}. Using device default."
                )
            self.sample_rate: int = queried_sample_rate
        except (OSError, TypeError):
            logger.warning(
                f"Could not query device {self.device_index}. Falling back to config sample rate."
            )
            self.sample_rate: int = settings.audio.sample_rate  # type: ignore[no-redef]

        # config
        self.channels: int = settings.audio.channels
        self.chunk_size: int = settings.audio.chunk_size
        self.format = pyaudio.paInt16

        self.output_path: Path = settings.recording.local_storage_path
        self.filename_format: str = settings.recording.filename_format

    def _log_audio_devices(self) -> None:
        """Log available audio devices for debugging."""
        logger.info("Available audio devices:")
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            logger.info(
                f"  [{i}] {info['name']} - "
                f"Inputs: {info['maxInputChannels']}, "
                f"Outputs: {info['maxOutputChannels']}, "
                f"Sample Rate: {info.get('defaultSampleRate', 'Unknown')}, "
                f"Low Latency: {info.get('defaultLowInputLatency', 0) * 1000:.1f}ms, "
                f"High Latency: {info.get('defaultHighInputLatency', 0) * 1000:.1f}ms"
            )

    def _rescan_usb_devices(self) -> None:
        """Force Linux to re-scan USB devices."""
        # unbind and rebind USB devices
        subprocess.run(
            ["/usr/bin/sudo", "sh", "-c", "echo '1' > /sys/bus/usb/drivers/usb/unbind"],
            check=False,
            timeout=2,
        )
        time.sleep(1)
        subprocess.run(
            ["/usr/bin/sudo", "sh", "-c", "echo '1' > /sys/bus/usb/drivers/usb/bind"],
            check=False,
            timeout=2,
        )
        logger.info("USB devices rescanned")

    def _wait_for_device(self, max_retries: int = 30, retry_delay: int = 2) -> bool:
        """
        Wait for the target audio device to become available.
        This is achieved by re-initialising the list of audio
        devices in PyAudio.

        Args:
            max_retries: Maximum number of attempts
            retry_delay: Seconds between retries

        Returns:
            True if device found, False otherwise

        """
        logger.info(f"Waiting for audio device {self.device_index}...")

        tries = 0
        while tries < max_retries:
            tries += 1
            try:
                # re-initialise
                self.audio.terminate()
                self.audio = pyaudio.PyAudio()

                # check for device
                device_info = self.audio.get_device_info_by_index(self.device_index)
                if (
                    self.device_name is not None
                    and device_info.get("name") != self.device_name
                ):
                    logger.warning(
                        f"retrieved name for device with index {self.device_index}"
                        f"is {device_info.get('name')}. we want: {self.device_name}"
                    )
                    continue

                # check n channels
                if device_info.get("maxInputChannels", 0) > 0:
                    logger.info(f"Device found:  {device_info['name']}")
                    return True
                logger.warning(f"Device {self.device_index} has no input channels")

            except OSError as e:
                logger.warning(
                    f"Device {self.device_index} not ready "
                    f"(attempt {tries}/{max_retries}): {e}. "
                    f"Retrying in {retry_delay}s..."
                )
            finally:
                time.sleep(retry_delay)

        logger.error(
            f"Device {self.device_index} not found after {max_retries} attempts"
        )
        return False

    def get_recording_stats(self) -> dict:
        """
        Get current recording statistics.

        Returns:
            Dictionary with recording stats

        """
        with self.stats_lock:
            return self.stats.get_recording_info()

    def check_usb_device_health(self) -> bool:
        """
        Check if USB audio device is still connected and healthy.

        Returns:
            True if device is healthy, False otherwise

        """
        try:
            # Check if we can still query the device
            device_info = self.audio.get_device_info_by_index(self.device_index)

            # Verify device name matches if configured
            if self.device_name and device_info.get("name") != self.device_name:
                logger.error(
                    f"USB device name mismatch! Expected '{self.device_name}', "
                    f"got '{device_info.get('name')}'"
                )
                return False

            # Check USB device still exists in system
            # /proc/asound/cards uses different naming than PyAudio
            proc_cards = Path("/proc/asound/cards")
            if proc_cards.exists():
                cards_info = proc_cards.read_text()

                # Extract the core device name from PyAudio's format
                # PyAudio: "Soundcraft 2-channel Audio Driv: USB Audio (hw:1,0)"
                # proc: "Soundcraft 2-channel Audio Driv"
                if self.device_name:
                    # Extract name before the colon (if present)
                    core_name = self.device_name.split(":")[0].strip()

                    # Also handle the card index from (hw:X,Y) format
                    if "(hw:" in self.device_name:
                        hw_index = self.device_name.split("(hw:")[1].split(",")[0]
                        # Check if card index exists
                        if f" {hw_index} [" not in cards_info:
                            logger.error(
                                f"USB device card index {hw_index} not found in /proc/asound/cards"
                            )
                            return False

                    # Check if core device name exists in proc
                    if core_name not in cards_info:
                        logger.error(
                            f"USB device '{core_name}' not found in /proc/asound/cards. "
                            f"Available: {cards_info}"
                        )
                        return False

        except OSError as e:
            logger.error(f"USB device health check failed: {e}")
            return False
        else:
            return True

    def _monitor_recording(self, audio_queue: queue.Queue) -> None:
        """
        Monitor recording health in a separate thread.

        Args:
            audio_queue: The audio data queue to monitor

        """
        logger.info("Recording monitoring thread started")
        last_stats_log = time.time()
        last_health_check = time.time()

        while not self.stop_event.is_set():
            time.sleep(1)  # Check every second

            current_time = time.time()

            # Log stats periodically
            if current_time - last_stats_log >= STATS_LOG_INTERVAL_SECONDS:
                with self.stats_lock:
                    duration = self.stats.get_duration_seconds()
                    queue_size = audio_queue.qsize()

                    logger.info(
                        f"Recording stats: "
                        f"Duration: {duration:.1f}s, "
                        f"Frames: {self.stats.frames_recorded:,}, "
                        f"Bytes: {self.stats.bytes_written:,} ({self.stats.bytes_written / (1024 * 1024):.2f} MB), "
                        f"Callbacks: {self.stats.callback_count:,}, "
                        f"Queue: {queue_size}, "
                        f"Max Queue: {self.stats.queue_max_size}, "
                        f"Overflows: {self.stats.overflow_count}, "
                        f"Underflows: {self.stats.underflow_count}"
                    )

                    # Check for issues
                    if self.stats.overflow_count > 0:
                        logger.warning(
                            f"Detected {self.stats.overflow_count} buffer overflows! "
                            "Consider increasing chunk_size or reducing CPU load."
                        )

                    if queue_size > QUEUE_SIZE_WARNING_THRESHOLD:
                        logger.warning(
                            f"Audio queue is large ({queue_size} items). "
                            "Disk write may be falling behind."
                        )

                    # Check if callbacks have stopped
                    if (
                        current_time - self.stats.last_callback_time
                        > CALLBACK_TIMEOUT_SECONDS
                    ):
                        logger.error(
                            f"No audio callbacks received for {CALLBACK_TIMEOUT_SECONDS} seconds! "
                            "Recording may have stopped."
                        )
                        with self.stats_lock:
                            self.stats.errors.append(
                                f"No callbacks for {CALLBACK_TIMEOUT_SECONDS}s at {datetime.now(tz=UTC).isoformat()}"
                            )

                last_stats_log = current_time

            # Health check periodically
            if current_time - last_health_check >= HEALTH_CHECK_INTERVAL_SECONDS:
                if not self.check_usb_device_health():
                    logger.error("USB device health check failed during recording!")
                    with self.stats_lock:
                        self.stats.errors.append(
                            f"USB health check failed at {datetime.now(tz=UTC).isoformat()}"
                        )
                last_health_check = current_time

        logger.info("Recording monitoring thread stopped")

    def start_recording(self) -> bool:
        """Start recording audio."""
        if self.is_recording:
            logger.warning("Already recording!")
            return False

        self.is_recording = True
        self.stop_event.clear()

        # Reset stats
        with self.stats_lock:
            self.stats = RecordingStats()
            self.stats.start_time = time.time()

        timestamp = datetime.now(tz=UTC).strftime(self.filename_format)
        filename = f"{timestamp}.wav"
        filepath = Path(self.output_path) / filename

        with self.stats_lock:
            self.stats.current_file = filepath

        logger.info(f"Starting recording to {filepath}...")
        logger.info(
            f"Audio config: {self.sample_rate}Hz, {self.channels}ch, "
            f"chunk_size={self.chunk_size} (~{self.chunk_size / self.sample_rate * 1000:.1f}ms)"
        )

        # open thread
        self.recording_thread = Thread(
            target=self._record_audio, args=(filepath,), daemon=True
        )
        self.recording_thread.start()

        return True

    def stop_recording(self) -> bool:
        """Stop recording audio."""
        if not self.is_recording:
            logger.warning("Not currently recording")
            return False

        logger.info("Stopping recording")
        self.stop_event.set()

        if self.recording_thread:
            self.recording_thread.join(timeout=5)

        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)

        # Log final stats
        with self.stats_lock:
            logger.info(
                f"Recording completed: "
                f"Duration: {self.stats.get_duration_seconds():.1f}s, "
                f"Total bytes: {self.stats.bytes_written:,} ({self.stats.bytes_written / (1024 * 1024):.2f} MB), "
                f"Total callbacks: {self.stats.callback_count:,}, "
                f"Overflows: {self.stats.overflow_count}, "
                f"Errors: {len(self.stats.errors)}"
            )

        self.is_recording = False
        return True

    def _log_stream_info(self, stream: pyaudio.Stream) -> None:
        """
        Log comprehensive information about the PyAudio stream.

        Args:
            stream: The PyAudio Stream object

        """
        try:
            # Stream configuration
            logger.info("=" * 60)
            logger.info("STREAM CONFIGURATION")
            logger.info("=" * 60)
            logger.info(f"Sample Rate: {self.sample_rate} Hz")
            logger.info(f"Channels: {self.channels}")
            logger.info(f"Format: {self.format}")
            logger.info(f"Frames per buffer: {self.chunk_size}")
            logger.info(
                f"Buffer duration: ~{(self.chunk_size / self.sample_rate) * 1000:.1f}ms"
            )

            # Stream latency information
            logger.info("-" * 60)
            logger.info("STREAM LATENCY")
            logger.info("-" * 60)
            input_latency = stream.get_input_latency()
            output_latency = stream.get_output_latency()
            logger.info(f"Input latency: {input_latency * 1000:.2f}ms")
            logger.info(f"Output latency: {output_latency * 1000:.2f}ms")

            # Stream state
            logger.info("-" * 60)
            logger.info("STREAM STATE")
            logger.info("-" * 60)
            logger.info(f"Is active: {stream.is_active()}")
            logger.info(f"Is stopped: {stream.is_stopped()}")
            logger.info(f"Stream time: {stream.get_time():.3f}s")
            logger.info(f"CPU load: {stream.get_cpu_load() * 100:.2f}%")

            # Buffer availability (for blocking mode)
            if hasattr(stream, "get_read_available"):
                try:
                    read_available = stream.get_read_available()
                    logger.info(f"Read available frames: {read_available}")
                except OSError:
                    # Not available in callback mode
                    logger.debug("Read available: N/A (callback mode)")

            if hasattr(stream, "get_write_available"):
                try:
                    write_available = stream.get_write_available()
                    logger.info(f"Write available frames: {write_available}")
                except OSError:
                    # Not available in callback mode
                    logger.debug("Write available: N/A (callback mode)")

            logger.info("=" * 60)

        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not log complete stream info: {e}")

    def _record_audio(self, filepath: str) -> None:  # noqa: PLR0915 (for now)
        """
        Private method to record audio to file.

        Args:
            filepath: Path to save recording

        """
        audio_queue: queue.Queue = queue.Queue()
        wf = None
        stream = None

        try:
            wf = wave.open(str(filepath), "wb")  # noqa: SIM115
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.sample_rate)

            def callback(
                in_data: bytes | None,
                _frame_count: int,
                _time_info: dict[str, float],
                status: int,
            ) -> tuple[bytes | None, int]:
                with self.stats_lock:
                    self.stats.callback_count += 1
                    self.stats.last_callback_time = time.time()

                if status:
                    # Decode PyAudio status flags
                    status_msg = []
                    if status & pyaudio.paInputOverflow:
                        status_msg.append("INPUT_OVERFLOW")
                        with self.stats_lock:
                            self.stats.overflow_count += 1
                    if status & pyaudio.paInputUnderflow:
                        status_msg.append("INPUT_UNDERFLOW")
                        with self.stats_lock:
                            self.stats.underflow_count += 1
                    if status & pyaudio.paOutputOverflow:
                        status_msg.append("OUTPUT_OVERFLOW")
                    if status & pyaudio.paOutputUnderflow:
                        status_msg.append("OUTPUT_UNDERFLOW")

                    logger.warning(
                        f"PyAudio callback status: {' | '.join(status_msg)} (code: {status})"
                    )
                    with self.stats_lock:
                        self.stats.errors.append(
                            f"{' | '.join(status_msg)} at {datetime.now(tz=UTC).isoformat()}"
                        )

                if in_data:
                    audio_queue.put(in_data)
                    with self.stats_lock:
                        self.stats.frames_recorded += _frame_count
                        # Track queue size
                        queue_size = audio_queue.qsize()
                        self.stats.queue_max_size = max(
                            self.stats.queue_max_size, queue_size
                        )

                return (None, pyaudio.paContinue)

            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size,
                stream_callback=callback,
            )

            logger.info(
                f"Recording started at {self.sample_rate} Hz (using queue pattern)"
            )

            # Log stream info
            self._log_stream_info(stream=stream)

            stream.start_stream()

            # Start monitoring thread
            self.monitoring_thread = Thread(
                target=self._monitor_recording, args=(audio_queue,), daemon=True
            )
            self.monitoring_thread.start()

            while not self.stop_event.is_set() or not audio_queue.empty():
                try:
                    chunk = audio_queue.get(timeout=0.1)
                    wf.writeframes(chunk)
                    with self.stats_lock:
                        self.stats.bytes_written += len(chunk)
                except queue.Empty:
                    if self.stop_event.is_set():
                        break
                    continue

            logger.info("Recording stopped")

        except Exception as e:  # noqa: BLE001
            logger.error("An error occurred during recording setup or execution.")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {e}")
            logger.error("Stack trace:", traceback.format_exc())
            with self.stats_lock:
                self.stats.errors.append(
                    f"Exception: {type(e).__name__}: {e} at {datetime.now(tz=UTC).isoformat()}"
                )
        finally:
            if stream and stream.is_active():
                stream.stop_stream()
            if stream:
                stream.close()
            if wf:
                wf.close()
            while not audio_queue.empty():
                try:
                    audio_queue.get_nowait()
                except queue.Empty:
                    break

        logger.info(f"Recording saved to {filepath}")

    def _upload_file(self, filepath: Path) -> None:
        """
        Upload file to Dropbox.

        Args:
            filepath: Path to file to upload

        """
        try:
            logger.info(f"Uploading {filepath} to Dropbox")
            if self.uploader:
                self.uploader.upload_file(filepath)

            # Delete local file if configured
            if settings.dropbox.delete_local_after_upload:
                Path.unlink(filepath)
                logger.info(f"Deleted local file {filepath}")

        except Exception as e:
            logger.error("Encountered error while recording.")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {e}")
            logger.error("Stack trace:")
            logger.error(traceback.format_exc())
            raise

    def cleanup(self) -> None:
        """Cleanup audio resources."""
        if self.is_recording:
            self.stop_recording()
        self.audio.terminate()
