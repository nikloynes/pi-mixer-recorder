"""
Install a systemd unit to launch web app on Pi startup.

To install:
python src/utils/install_systemd_unit.py uploader --user pi --user-service
python src/utils/install_systemd_unit.py webapp --user pi --user-service
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_DEFAULT_NAME = "pi-mixer-recorder-daemon"
UPLOADER_SERVICE_DEFAULT_NAME = "pi-mixer-recorder-uploader"
PROJECT_PYTHON_PATH = Path(__file__).parent.parent / ".venv/bin/python"


def detect_python(project_root: Path) -> str:
    """Return full python interpreter path, preferring a local venv."""
    venv_python = project_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        print(f"Found Python executable in virtual environment: {venv_python}")
        return str(venv_python)

    # fallback: sys python
    system_python = shutil.which("python")
    if system_python:
        print(f"Found system Python executable: {system_python}")
        return system_python

    no_python = (
        "Could not find a Python executable in .venv/bin/ or on the system PATH."
    )
    raise FileNotFoundError(no_python)


def render_unit(  # noqa: PLR0913
    user: str,
    working_dir: Path,
    python_exec: Path,
    start_command: str,
    description: str,
    *,
    is_user_service: bool,
) -> str:
    """Produce string for systemd unit to write to file."""
    # User services should use default.target, system services use multi-user.target
    install_target = "default.target" if is_user_service else "multi-user.target"

    # User and Group directives are only needed for system-wide services
    user_config = ""
    if not is_user_service:
        user_config = f"""User={user}
Group={user}"""

    return f"""[Unit]
Description={description}
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
{user_config}
WorkingDirectory={str(working_dir)}
Environment=PYTHONUNBUFFERED=1
ExecStart={str(python_exec)} {start_command}
Restart=on-failure
RestartSec=10
TimeoutStopSec=20
KillSignal=SIGTERM

[Install]
WantedBy={install_target}
""".replace("\n\n\n", "\n\n")


def run(cmd: list[str], *, user_mode: bool = False) -> None:
    """Run shell command."""
    if user_mode:
        cmd = ["systemctl", "--user", *cmd]
    # Add sudo for system-wide commands if not running as root
    elif os.geteuid() != 0:
        cmd = ["sudo", "systemctl", *cmd]
    else:
        cmd = ["systemctl", *cmd]
    subprocess.check_call(cmd)  # noqa: S603


def main() -> None:
    """Run processes sequentially."""
    parser = argparse.ArgumentParser(
        description="Install systemd service for pi-mixer-recorder"
    )
    subparsers = parser.add_subparsers(
        dest="service_type", required=True, help="Type of service to install"
    )

    # --- Web App Service Parser ---
    parser_app = subparsers.add_parser("webapp", help="Install the web app service")
    parser_app.add_argument(
        "--name", default=SERVICE_DEFAULT_NAME, help="Service name (without .service)"
    )
    parser_app.add_argument(
        "--user",
        default=os.environ.get("USER", "pi"),
        help="User to run the service as",
    )
    parser_app.add_argument(
        "--user-service",
        action="store_true",
        help="Install as a user service (no sudo).",
    )

    # --- Uploader Service Parser ---
    parser_uploader = subparsers.add_parser(
        "uploader", help="Install the Dropbox uploader service"
    )
    parser_uploader.add_argument(
        "--name",
        default=UPLOADER_SERVICE_DEFAULT_NAME,
        help="Service name (without .service)",
    )
    parser_uploader.add_argument(
        "--user",
        default=os.environ.get("USER", "pi"),
        help="User to run the service as",
    )
    parser_uploader.add_argument(
        "--user-service",
        action="store_true",
        help="Install as a user service (no sudo).",
    )

    args = parser.parse_args()

    # Project root is two levels up from this script's directory (src/utils -> project_root)
    project_root = Path(__file__).resolve().parents[2]
    # python_exec = detect_python()
    python_exec = detect_python(project_root)
    unit_text = ""
    start_cmd = ""

    if args.service_type == "webapp":
        start_cmd = "main.py"
        unit_text = render_unit(
            user=args.user,
            working_dir=project_root,
            python_exec=Path(python_exec),
            start_command=start_cmd,
            description="Pi Mixer Recorder Web App",
            is_user_service=args.user_service,
        )
    elif args.service_type == "uploader":
        start_cmd = "src/utils/recording_uploading_poller.py"
        unit_text = render_unit(
            user=args.user,
            working_dir=project_root,
            python_exec=Path(python_exec),
            start_command=start_cmd,
            description="Pi Mixer Recorder Dropbox Uploader",
            is_user_service=args.user_service,
        )

    if args.user_service:
        dest_dir = Path.home() / ".config" / "systemd" / "user"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{args.name}.service"
        dest.write_text(unit_text)
        print(f"Installed user service to {dest}")
        run(["daemon-reload"], user_mode=True)
        run(["enable", "--now", f"{args.name}.service"], user_mode=True)
        print("To start on boot without login: sudo loginctl enable-linger $(whoami)")
    else:
        if os.geteuid() != 0:
            print("Re-running with sudo for system-wide install.", file=sys.stderr)
            # Re-execute the script with sudo
            subprocess.check_call(["sudo", sys.executable, *sys.argv])  # noqa: S607 S603
            sys.exit(0)

        dest = Path("/etc/systemd/system") / f"{args.name}.service"
        dest.write_text(unit_text)
        print(f"Installed system service to {dest}")
        run(["daemon-reload"])
        run(["enable", "--now", f"{args.name}.service"])
        print("Service enabled and started.")


if __name__ == "__main__":
    main()
