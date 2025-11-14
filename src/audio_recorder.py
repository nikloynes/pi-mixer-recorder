"""Audio recording functionality."""

import queue
import traceback
import wave
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

import pyaudio
from loguru import logger

from src.config import get_settings
from src.dropbox_uploader import DropboxUploader

settings = get_settings()


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
        self.stop_event = Event()

        # init pyaudio
        self.audio = pyaudio.PyAudio()
        self._log_audio_devices()

        # query device info for defaults
        self.device_index: int | None = settings.audio.device_index
        self.device_info: dict | None = None

        if self.device_index is None:
            logger.error("No audio device index is specified in the config.")
            idx_missing = (
                "No device index found. Run `aplay -l` and "
                " add your device's index to `config.yaml`."
            )
            raise DeviceIndexError(idx_missing)

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
                f"Outputs: {info['maxOutputChannels']}"
            )

    def start_recording(self) -> bool:
        """Start recording audio."""
        if self.is_recording:
            logger.warning("Already recording!")
            return False

        self.is_recording = True
        self.stop_event.clear()

        timestamp = datetime.now(tz=UTC).strftime(self.filename_format)
        filename = f"{timestamp}.wav"
        filepath = Path(self.output_path) / filename

        logger.info(f"Starting recording to {filepath}...")

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

        self.is_recording = False
        return True

    def _record_audio(self, filepath: str) -> None:
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
                if status:
                    logger.warning(f"PyAudio callback status flag set: {status}")
                if in_data:
                    audio_queue.put(in_data)
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
            stream.start_stream()

            while not self.stop_event.is_set() or not audio_queue.empty():
                try:
                    chunk = audio_queue.get(timeout=0.1)
                    wf.writeframes(chunk)
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

        # stream = None
        # wf = None

        # try:
        #     stream = self.audio.open(
        #         format=self.format,
        #         channels=self.channels,
        #         rate=self.sample_rate,
        #         input=True,
        #         input_device_index=self.device_index,
        #         frames_per_buffer=self.chunk_size,
        #     )

        #     wf = wave.open(str(filepath), "wb")
        #     wf.setnchannels(self.channels)
        #     wf.setsampwidth(self.audio.get_sample_size(self.format))
        #     wf.setframerate(self.sample_rate)

        #     logger.info("Recording started")
        #     frame_count = 0

        #     while not self.stop_event.is_set():
        #         try:
        #             data = stream.read(self.chunk_size, exception_on_overflow=False)
        #             wf.writeframes(
        #                 data
        #             )  # don't cache to memory, write straight to disk
        #             frame_count += 1
        #         except Exception as e:
        #             logger.error("Encountered error while recording.")
        #             logger.error(f"Error type: {type(e).__name__}")
        #             logger.error(f"Error message: {e}")
        #             logger.error("Stack trace:")
        #             logger.error(traceback.format_exc())
        #             break

        #     logger.info(f"Recording stopped, captured {frame_count} frames")

        # except Exception as e:
        #     logger.error("Encountered error while recording.")
        #     logger.error(f"Error type: {type(e).__name__}")
        #     logger.error(f"Error message: {e}")
        #     logger.error("Stack trace:")
        #     logger.error(traceback.format_exc())
        #     return
        # finally:
        #     if stream:
        #         stream.stop_stream()
        #         stream.close()
        #     if wf:
        #         wf.close()

        # logger.info(f"Recording saved to {filepath}")

        # # upload to Dropbox if configured
        # if self.uploader and settings.dropbox.enabled:
        #     if settings.dropbox.upload_in_background:
        #         Thread(target=self._upload_file, args=(filepath,), daemon=True).start()
        #     else:
        #         self._upload_file(filepath)

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
