#!/usr/bin/env python3
"""
Main entry point for the Raspberry Pi Audio Recorder
"""

import logging
import os
import signal
import sys
from threading import Event
from typing import Optional

from src.audio_recorder import AudioRecorder
from src.config_manager import ConfigManager
from src.dropbox_uploader import DropboxUploader
from src.gpio_controller import GPIOController
from src.web_interface import create_app

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global shutdown event
shutdown_event = Event()


def signal_handler(signum: int, frame: Optional[object]) -> None:
    """Handle shutdown signals"""
    logger.info("Received shutdown signal, cleaning up...")
    shutdown_event.set()


def main() -> None:
    """Main application entry point"""
    # Load configuration
    try:
        config = ConfigManager("config.yaml")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Create recordings directory
    recordings_path = config.get("recording.local_storage_path")
    if recordings_path:
        os.makedirs(recordings_path, exist_ok=True)

    # Initialize components
    uploader: Optional[DropboxUploader] = None
    if config.get("dropbox.enabled"):
        try:
            uploader = DropboxUploader(config)
            logger.info("Dropbox uploader initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Dropbox uploader: {e}")
            uploader = None

    # Initialize audio recorder
    try:
        recorder = AudioRecorder(config, uploader)
        logger.info("Audio recorder initialized")
    except Exception as e:
        logger.error(f"Failed to initialize audio recorder: {e}")
        sys.exit(1)

    # Initialize GPIO controller (if configured)
    gpio: Optional[GPIOController] = None
    if config.get("gpio.button_pin") is not None:
        try:
            gpio = GPIOController(config, recorder)
            logger.info("GPIO controller initialized")
        except Exception as e:
            logger.error(f"Failed to initialize GPIO controller: {e}")
            # Continue without GPIO

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and start web interface
    try:
        app = create_app(recorder, config)
        host = config.get("web.host", "0.0.0.0")
        port = config.get("web.port", 5000)
        debug = config.get("web.debug", False)

        logger.info(f"Starting web interface on {host}:{port}")

        # Run the Flask app
        app.run(
            host=host,
            port=port,
            debug=debug,
            use_reloader=False,  # Important: avoid starting GPIO twice
        )
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        # Cleanup
        logger.info("Shutting down...")
        if recorder.is_recording:
            recorder.stop_recording()
        if gpio:
            gpio.cleanup()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
