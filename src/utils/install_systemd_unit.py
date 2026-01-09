"""
Install a systemd USER unit to launch services on Pi startup.

To install:
python src/utils/install_systemd_unit.py webapp
python src/utils/install_systemd_unit.py uploader

To check status:
systemctl --user status pi-mixer-recorder-daemon
systemctl --user status pi-mixer-recorder-uploader
"""

import argparse
import subprocess
import sys
from pathlib import Path

# --- Configuration ---
SERVICE_CONFIG = {
    "webapp": {
        "name": "pi-mixer-recorder-daemon",
        "description": "Pi Mixer Recorder Web App",
        "start_script": "main.py",
    },
    "uploader": {
        "name": "pi-mixer-recorder-uploader",
        "description": "Pi Mixer Recorder Dropbox Uploader",
        "start_script": "src/utils/recording_uploading_poller.py",
    },
}


def get_project_root() -> Path:
    """Get the project's root directory."""
    # This script is in src/utils, so root is two levels up.
    return Path(__file__).resolve().parents[2]


def get_python_executable(root: Path) -> str:
    """Find the python executable, preferring the virtual environment."""
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    raise FileNotFoundError(f"Python not found in virtual environment: {venv_python}")


def generate_unit_file(
    description: str, working_dir: str, python_exec: str, start_script: str
) -> str:
    """Generate the content for the .service file."""
    # Create a unique log file name in /tmp based on the script name
    log_file = f"/tmp/{Path(start_script).stem}.log"

    return f"""[Unit]
Description={description}
# Wait for network to be fully online
Wants=network-online.target
After=network-online.target
# Add a small delay to ensure network stack is fully initialized
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory={working_dir}
# Ensure Python output isn't buffered so logs appear immediately
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
# Add timestamp prefix to all log output
ExecStartPre=/bin/sh -c 'echo "=== Service starting at $(date) ===" >> {log_file}'
ExecStart={python_exec} {start_script}
# Separate output and error logs for easier debugging
StandardOutput=append:{log_file}
StandardError=append:{log_file}
# Restart on failure with exponential backoff
Restart=on-failure
RestartSec=10
KillSignal=SIGTERM
# Give service time to shut down gracefully
TimeoutStopSec=30
# Log service state changes
ExecStopPost=/bin/sh -c 'echo "=== Service stopped at $(date) with status ${{SERVICE_RESULT}} ===" >> {log_file}'

[Install]
WantedBy=default.target
"""


def run_command(cmd: list[str]) -> None:
    """Runs a systemctl command for the current user."""
    full_cmd = ["systemctl", "--user", *cmd]
    print(f"Running: {' '.join(full_cmd)}")
    subprocess.check_call(full_cmd)


def main() -> None:
    """Main installation logic."""
    parser = argparse.ArgumentParser(description="Install systemd user service.")
    parser.add_argument(
        "service_type",
        choices=SERVICE_CONFIG.keys(),
        help="The service to install.",
    )
    args = parser.parse_args()

    config = SERVICE_CONFIG[args.service_type]
    service_name = f"{config['name']}.service"

    try:
        project_root = get_project_root()
        python_exec = get_python_executable(project_root)

        print(f"Project Root: {project_root}")
        print(f"Python Executable: {python_exec}")

        # Stop and disable the service first to ensure a clean state
        try:
            run_command(["stop", service_name])
            run_command(["disable", service_name])
        except subprocess.CalledProcessError:
            print(f"Could not stop/disable {service_name}. It might not exist yet.")

        # Generate and write the new service file
        unit_content = generate_unit_file(
            description=config["description"],
            working_dir=str(project_root),
            python_exec=python_exec,
            start_script=config["start_script"],
        )

        dest_dir = Path.home() / ".config" / "systemd" / "user"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / service_name
        dest_path.write_text(unit_content)

        print(f"\n--- Contents of {dest_path} ---")
        print(unit_content)
        print("-------------------------------------\n")

        # Reload, enable, and start the service
        run_command(["daemon-reload"])
        run_command(["enable", service_name])
        run_command(["start", service_name])

        print(f"\nSuccessfully installed and started {service_name}.")
        print("Run the following command to check its status:")
        print(f"systemctl --user status {service_name}")

    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"\nAn error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
