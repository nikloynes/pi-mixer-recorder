"""
Audio recording functionality
"""

import logging
import os
import wave
from datetime import datetime
from threading import Event, Thread
from typing import TYPE_CHECKING, Optional

import pyaudio

from config_manager import ConfigManager

if TYPE_CHECKING:
    from dropbox_uploader import DropboxUploader

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Handles audio recording from USB audio interface"""

    def __init__(self, config: ConfigManager, uploader: Optional["DropboxUploader"] = None) -> None:
        """
        Initialize audio recorder

        Args:
            config: ConfigManager instance
            uploader: DropboxUploader instance (optional)
        """
        self.config = config
        self.uploader = uploader
        self.is_recording = False
        self.recording_thread: Optional[Thread] = None
        self.stop_event = Event()

        # Audio configuration
        self.sample_rate: int = config.get("audio.sample_rate", 48000)
        self.channels: int = config.get("audio.channels", 2)
        self.chunk_size: int = config.get("audio.chunk_size", 1024)
        self.format = pyaudio.paInt16
        self.device_index: Optional[int] = config.get("audio.device_index")

        # Recording configuration
        self.output_path: str = config.get("recording.local_storage_path")
        self.filename_format: str = config.get("recording.filename_format")

        # Initialize PyAudio
        self.audio = pyaudio.PyAudio()
        self._log_audio_devices()

    def _log_audio_devices(self) -> None:
        """Log available audio devices for debugging"""
        logger.info("Available audio devices:")
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            logger.info(
                f"  [{i}] {info['name']} - "
                f"Inputs: {info['maxInputChannels']}, "
                f"Outputs: {info['maxOutputChannels']}"
            )

    def start_recording(self) -> bool:
        """Start recording audio"""
        if self.is_recording:
            logger.warning("Already recording")
            return False

        self.is_recording = True
        self.stop_event.clear()

        # Generate filename
        timestamp = datetime.now().strftime(self.filename_format)
        filename = f"{timestamp}.wav"
        filepath = os.path.join(self.output_path, filename)

        logger.info(f"Starting recording to {filepath}")

        # Start recording in separate thread
        self.recording_thread = Thread(
            target=self._record_audio, args=(filepath,), daemon=True
        )
        self.recording_thread.start()

        return True

    def stop_recording(self) -> bool:
        """Stop recording audio"""
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
        Internal method to record audio to file

        Args:
            filepath: Path to save recording
        """
        frames: list[bytes] = []
        stream = None

        try:
            # Open audio stream
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size,
            )

            logger.info("Recording started")

            # Record until stop event is set
            while not self.stop_event.is_set():
                try:
                    data = stream.read(self.chunk_size, exception_on_overflow=False)
                    frames.append(data)
                except Exception as e:
                    logger.error(f"Error reading audio stream: {e}")
                    break

            logger.info(f"Recording stopped, captured {len(frames)} frames")

        except Exception as e:
            logger.error(f"Error during recording: {e}")
            return
        finally:
            if stream:
                stream.stop_stream()
                stream.close()

        # Save to WAV file
        try:
            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.audio.get_sample_size(self.format))
                wf.setframerate(self.sample_rate)
                wf.writeframes(b"".join(frames))

            logger.info(f"Recording saved to {filepath}")

            # Upload to Dropbox if configured
            if self.uploader and self.config.get("dropbox.enabled"):
                upload_in_background = self.config.get(
                    "dropbox.upload_in_background", True
                )

                if upload_in_background:
                    # Upload in separate thread
                    Thread(target=self._upload_file, args=(filepath,), daemon=True).start()
                else:
                    self._upload_file(filepath)

        except Exception as e:
            logger.error(f"Error saving recording: {e}")

    def _upload_file(self, filepath: str) -> None:
        """
        Upload file to Dropbox

        Args:
            filepath: Path to file to upload
        """
        try:
            logger.info(f"Uploading {filepath} to Dropbox")
            if self.uploader:
                self.uploader.upload_file(filepath)

            # Delete local file if configured
            if self.config.get("dropbox.delete_local_after_upload", False):
                os.remove(filepath)
                logger.info(f"Deleted local file {filepath}")

        except Exception as e:
            logger.error(f"Error uploading file: {e}")

    def cleanup(self) -> None:
        """Cleanup audio resources"""
        if self.is_recording:
            self.stop_recording()
        self.audio.terminate()