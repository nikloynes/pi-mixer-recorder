"""Flask web interface for controlling the audio recorder."""

from datetime import UTC, datetime
from typing import Any

from flask import Flask, jsonify, render_template
from flask.wrappers import Response
from loguru import logger

from src.audio_recorder import AudioRecorder
from src.config import get_settings

settings = get_settings()


def create_app(recorder: AudioRecorder) -> Flask:
    """
    Create Flask application.

    Args:
        recorder: AudioRecorder instance
        settings: Settings instance

    Returns:
        Flask app instance

    """
    app = Flask(__name__)

    @app.route("/")
    def index() -> str:
        """Render main page."""
        return render_template("index.html")

    @app.route("/api/status")
    def status() -> Response:
        """Get current recording status."""
        return jsonify(
            {
                "is_recording": recorder.is_recording,
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
        )

    @app.route("/api/start", methods=["POST"])
    def start() -> Response:
        """Start recording."""
        success = recorder.start_recording()
        return jsonify({"success": success, "is_recording": recorder.is_recording})

    @app.route("/api/stop", methods=["POST"])
    def stop() -> Response:
        """Stop recording."""
        success = recorder.stop_recording()
        return jsonify({"success": success, "is_recording": recorder.is_recording})

    @app.route("/api/recordings")
    def recordings() -> Response:
        """List local recordings."""
        recordings_path = settings.recording.local_storage_path
        files: list[dict[str, Any]] = []

        try:
            if not recordings_path.exists():
                logger.warning(f"Recordings path does not exist: {recordings_path}")
                return jsonify({"recordings": []})

            for file_path in recordings_path.glob("*.wav"):
                if file_path.is_file():
                    stat = file_path.stat()
                    files.append(
                        {
                            "filename": file_path.name,
                            "size": stat.st_size,
                            "created": datetime.fromtimestamp(
                                stat.st_ctime, tz=UTC
                            ).isoformat(),
                        }
                    )

            files.sort(key=lambda x: x["created"], reverse=True)

        except Exception:
            logger.exception("Error listing recordings")
            return jsonify({"recordings": [], "error": "Failed to list recordings"})

        return jsonify({"recordings": files})

    return app
