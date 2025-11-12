"""Main entry point for the Raspberry Pi Audio Recorder."""

import signal
import sys
from pathlib import Path
from threading import Event

from loguru import logger

from src.audio_recorder import AudioRecorder
from src.config import get_settings
from src.dropbox_uploader import DropboxUploader

# from src.gpio_controller import GPIOController # noqa: ERA001
from src.web_interface import create_app

settings = get_settings()
uploader = DropboxUploader()
recorder = AudioRecorder(uploader=uploader)

# Global shutdown event
shutdown_event = Event()


def signal_handler(signum: int, frame: object | None) -> None:  # noqa: ARG001
    """Handle shutdown signals."""
    logger.info("Received shutdown signal, cleaning up...")
    cleanup()
    shutdown_event.set()
    # Exit cleanly on TERM (e.g., from systemd/docker)
    sys.exit(0)


def cleanup() -> None:
    """Clean up resources."""
    logger.info("Shutting down...")
    if recorder.is_recording:
        recorder.stop_recording()
    recorder.cleanup()
    logger.info("Shutdown complete")


def main() -> None:
    """Run web app."""
    recordings_path = settings.recording.local_storage_path
    if recordings_path:
        Path.mkdir(recordings_path, exist_ok=True)

    # init GPIO if required!

    # setup signal handlers
    # let Flask handle Ctrl+C (SIGINT)
    signal.signal(signal.SIGTERM, signal_handler)

    # create and start web interface
    try:
        app = create_app(recorder)
        logger.info(
            f"Starting web interface on {settings.web.host}:{settings.web.port}"
        )

        app.run(
            host=settings.web.host,
            port=settings.web.port,
            debug=settings.web.debug,
            use_reloader=False,  # important: avoid starting GPIO twice
        )
    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt received")
        return
    finally:
        cleanup()


if __name__ == "__main__":
    main()
