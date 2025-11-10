"""Audio recording functionality."""

import traceback
import wave
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Optional

import pyaudio
from loguru import logger

from src.config import get_settings
from src.dropbox_uploader import DropboxUploader

settings = get_settings()


class AudioRecorder:
    """Handles audio recording from USB audio interface."""

    def __init__(self, uploader: DropboxUploader | None = None) -> None:
        """
        Initialize audio recorder.

        Args:
            config: ConfigManager instance
            uploader: DropboxUploader instance (optional)

        """
        self.uploader = uploader
        self.is_recording = False
        self.recording_thread: Thread | None = None
        self.stop_event = Event()

        # config
        self.sample_rate: int = settings.audio.sample_rate
        self.channels: int = settings.audio.channels
        self.chunk_size: int = settings.audio.chunk_size
        self.format = pyaudio.paInt16
        self.device_index: int | None = settings.audio.device_index

        self.output_path: Path = settings.recording.local_storage_path
        self.filename_format: str = settings.recording.filename_format

        # init pyaudio
        self.audio = pyaudio.PyAudio()
        self._log_audio_devices()

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
            logger.warning("Already recording")
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
        stream = None
        wf = None

        try:
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size,
            )

            wf = wave.open(str(filepath), "wb")  # noqa: SIM115
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.sample_rate)

            logger.info("Recording started")
            frame_count = 0

            while not self.stop_event.is_set():
                try:
                    data = stream.read(self.chunk_size, exception_on_overflow=False)
                    wf.writeframes(
                        data
                    )  # don't cache to memory, write straight to disk
                    frame_count += 1
                except Exception as e:  # noqa: BLE001
                    logger.error("Encountered error while recording.")
                    logger.error(f"Error type: {type(e).__name__}")
                    logger.error(f"Error message: {e}")
                    logger.error("Stack trace:")
                    logger.error(traceback.format_exc())
                    break

            logger.info(f"Recording stopped, captured {frame_count} frames")

        except Exception as e:  # noqa: BLE001
            logger.error("Encountered error while recording.")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {e}")
            logger.error("Stack trace:")
            logger.error(traceback.format_exc())
            return
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            if wf:
                wf.close()

        logger.info(f"Recording saved to {filepath}")

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
