"""Main entry point for the Raspberry Pi Audio Recorder."""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Event

from src.audio_recorder import AudioRecorder
from src.config import get_settings
from src.dropbox_uploader import DropboxUploader
from src.logger import logger

# from src.gpio_controller import GPIOController # noqa: ERA001
from src.web_interface import create_app

settings = get_settings()
uploader = DropboxUploader()
recorder = AudioRecorder(uploader=uploader)

# Global shutdown event
shutdown_event = Event()


def check_network_connectivity(max_retries: int = 30, retry_delay: int = 2) -> bool:
    """Check if network is available by attempting to resolve a hostname.

    Args:
        max_retries: Maximum number of connection attempts
        retry_delay: Seconds to wait between retries

    Returns:
        True if network is available, False otherwise
    """
    logger.info("Checking network connectivity...")

    for attempt in range(1, max_retries + 1):
        try:
            # Try to resolve a reliable hostname
            socket.gethostbyname("www.google.com")
            logger.debug(f"Network is available (attempt {attempt}/{max_retries})")
            return True
        except socket.gaierror:
            if attempt < max_retries:
                logger.warning(
                    f"Network not ready yet (attempt {attempt}/{max_retries}), "
                    f"retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                logger.error(
                    f"Network still unavailable after {max_retries} attempts. "
                    "Proceeding anyway, but external services may not work."
                )
                return False
    return False


def log_system_info() -> None:
    """Log detailed system and network information for debugging."""
    logger.debug("=" * 60)
    logger.debug("SYSTEM STARTUP DIAGNOSTICS")
    logger.debug("=" * 60)

    logger.debug(f"Python executable: {sys.executable}")
    logger.debug(f"Python version: {sys.version}")
    logger.debug(f"Working directory: {Path.cwd()}")

    # network info
    try:
        hostname = socket.gethostname()
        logger.info(f"Hostname: {hostname}")

        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            ips = result.stdout.strip()
            logger.info(f"IP addresses: {ips if ips else 'None found'}")
        else:
            logger.warning("Could not retrieve IP addresses")

    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not retrieve network info: {e}")

    # check if running in SSH session
    ssh_client = os.environ.get("SSH_CLIENT")
    ssh_tty = os.environ.get("SSH_TTY")
    if ssh_client or ssh_tty:
        logger.info(f"Running in SSH session (SSH_CLIENT={ssh_client})")
    else:
        logger.info("Running outside SSH session (likely systemd service)")

    logger.info("=" * 60)


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
    # Log system diagnostics first
    log_system_info()

    # Check network connectivity
    check_network_connectivity()

    # Log configuration
    logger.info("Loading configuration...")
    logger.info(f"Web server will run on {settings.web.host}:{settings.web.port}")
    logger.info(f"Debug mode: {settings.web.debug}")
    logger.info(f"Recordings path: {settings.recording.local_storage_path}")
    logger.info(f"Dropbox enabled: {settings.dropbox.enabled}")

    recordings_path = settings.recording.local_storage_path
    if recordings_path:
        Path.mkdir(recordings_path, exist_ok=True)
        logger.debug(f"Ensured recordings directory exists: {recordings_path}")

    # init GPIO if required!

    # setup signal handlers
    # let Flask handle Ctrl+C (SIGINT)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("Signal handlers registered")

    # create and start web interface
    try:
        logger.info("Creating Flask application...")
        app = create_app(recorder)
        logger.info("Flask app created successfully")

        logger.info(
            f"Starting web interface on {settings.web.host}:{settings.web.port}"
        )
        logger.info(
            f"Access the web interface at: http://{settings.web.host}:{settings.web.port}"
        )
        logger.info("Flask app is about to start...")

        app.run(
            host=settings.web.host,
            port=settings.web.port,
            debug=settings.web.debug,
            use_reloader=False,  # important: avoid starting GPIO twice
        )
        logger.info(f"Flask app running...")
    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt received")
        return
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to start Flask app: {e}")
        logger.exception("Full traceback:")
        raise
    finally:
        cleanup()


if __name__ == "__main__":
    main()
