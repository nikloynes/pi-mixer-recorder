"""Main entry point for the Raspberry Pi Audio Recorder."""

import signal
from pathlib import Path
from threading import Event

from loguru import logger

from src.audio_recorder import AudioRecorder
from src.config import get_settings
from src.dropbox_uploader import DropboxUploader

# from src.gpio_controller import GPIOController
from src.web_interface import create_app

settings = get_settings()
uploader = DropboxUploader()
recorder = AudioRecorder(uploader=uploader)

# Global shutdown event
shutdown_event = Event()


def signal_handler(signum: int, frame: object | None) -> None:
    """Handle shutdown signals."""
    logger.info("Received shutdown signal, cleaning up...")
    shutdown_event.set()


def main() -> None:
    """Run web app."""
    recordings_path = settings.recording.local_storage_path
    if recordings_path:
        Path.mkdir(recordings_path, exist_ok=True)

    # # Initialize GPIO controller (if configured)
    # gpio: GPIOController | None = None
    # if config.get("gpio.button_pin") is not None:
    #     try:
    #         gpio = GPIOController(config, recorder)
    #         logger.info("GPIO controller initialized")
    #     except Exception as e:
    #         logger.error(f"Failed to initialize GPIO controller: {e}")
    #         # Continue without GPIO

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
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
    finally:
        # cleanup
        logger.info("Shutting down...")
        if recorder.is_recording:
            recorder.stop_recording()
        # if gpio:
        #     gpio.cleanup()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
