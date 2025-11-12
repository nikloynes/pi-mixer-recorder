"""Install a systemd unit to launch web app on Pi startup."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_DEFAULT_NAME = "pi-mixer-recorder-daemon"


def detect_python() -> str:
    """Return full python interpreter path."""
    return shutil.which("python")  # type: ignore[return-value]


def render_unit(
    user: str = "pi",
    working_dir: Path = Path("home/pi/pi-mixer-recorder"),
    python_exec: Path = Path("/home/pi/pi-mixer-recorder/.venv/bin/python"),
) -> str:
    """Produce string for systemd unit to write to file."""
    return f"""[Unit]
Description=Pi Mixer Recorder Web App (Flask)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={user}
Group={user}
WorkingDirectory={str(working_dir)}
Environment=PYTHONUNBUFFERED=1
ExecStart={str(python_exec)} {str(working_dir)}/main.py
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
""".replace("\n\n\n", "\n\n")


def run(cmd: list[str], user_mode: bool = False) -> None:
    """Run shell command."""
    if user_mode:
        cmd = ["systemctl", "--user", *cmd]
    subprocess.check_call(cmd)  # noqa: S603


def main() -> None:
    """Run processes sequentially."""
    parser = argparse.ArgumentParser(
        description="Install systemd service for pi-mixer-recorder"
    )
    parser.add_argument(
        "--name", default=SERVICE_DEFAULT_NAME, help="Service name (without .service)"
    )
    parser.add_argument(
        "--user",
        default=os.environ["USER"],
        help="User to run the service as (e.g., pi)",
    )
    parser.add_argument(
        "--user-service",
        action="store_true",
        help="Install as a user service (no sudo). Starts after login unless linger is enabled.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    python_exec = detect_python()

    unit_text = render_unit(args.user, project_root, Path(python_exec))

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
            print("Please re-run with sudo for system-wide install.", file=sys.stderr)
            print(
                f"Suggested: sudo {sys.executable} {Path(__file__).resolve()} --name {args.name} --user {args.user}",
                file=sys.stderr,
            )
            sys.exit(1)
        dest = Path("/etc/systemd/system") / f"{args.name}.service"
        dest.write_text(unit_text)
        print(f"Installed system service to {dest}")
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", f"{args.name}.service"])
        print("Service enabled and started.")


if __name__ == "__main__":
    main()
