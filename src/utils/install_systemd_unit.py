"""Install a systemd unit to launch web app on Pi startup."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

SERVICE_DEFAULT_NAME = "pi-mixer-recorder"


def detect_python(project_root: Path) -> Path:
    # Prefer project venv, otherwise use the interpreter running this script
    venv_python = project_root / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def render_unit(
    name: str, user: str, working_dir: Path, python_exec: Path, env_file: Path | None
) -> str:
    env_line = f"EnvironmentFile=-{env_file}" if env_file else ""
    return f"""[Unit]
Description=Pi Mixer Recorder Web App (Flask)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={user}
Group={user}
WorkingDirectory={working_dir}
Environment=PYTHONUNBUFFERED=1
{env_line}
ExecStart={python_exec} {working_dir}/main.py
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
""".replace("\n\n\n", "\n\n")


def run(cmd: list[str], user_mode: bool = False) -> None:
    if user_mode:
        cmd = ["systemctl", "--user"] + cmd
    subprocess.check_call(cmd)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install systemd service for pi-mixer-recorder"
    )
    parser.add_argument(
        "--name", default=SERVICE_DEFAULT_NAME, help="Service name (without .service)"
    )
    parser.add_argument(
        "--user", default="pi", help="User to run the service as (e.g., pi)"
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Optional EnvironmentFile path (relative or absolute)",
    )
    parser.add_argument(
        "--user-service",
        action="store_true",
        help="Install as a user service (no sudo). Starts after login unless linger is enabled.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    working_dir = project_root
    python_exec = detect_python(project_root)
    env_file_path = Path(args.env_file)
    if not env_file_path.is_absolute():
        env_file_path = project_root / env_file_path
    if not env_file_path.exists():
        # Still include with '-' prefix so it's optional
        env_file_path = env_file_path  # keep as-is, systemd will ignore if missing

    unit_text = render_unit(
        args.name, args.user, working_dir, python_exec, env_file_path
    )

    if args.user_service:
        dest_dir = Path.home() / ".config" / "systemd" / "user"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{args.name}.service"
        dest.write_text(unit_text)
        print(f"Installed user service to {dest}")
        run(["daemon-reload"], user_mode=True)
        run(["enable", "--now", f"{args.name}.service"], user_mode=True)
        print(
            "Tip: to start on boot without login: sudo loginctl enable-linger $(whoami)"
        )
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
