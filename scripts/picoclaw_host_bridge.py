#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path("/Users/Tim/Documents/picoclaw")
DATA_DIR = ROOT / "docker" / "data"
REQUESTS_DIR = DATA_DIR / "hostexec" / "requests"
STATE_DIR = DATA_DIR / "hostexec"
PID_FILE = STATE_DIR / "bridge.pid"
LOG_FILE = STATE_DIR / "bridge.log"
POLL_SECONDS = 1.0
CONTAINER_NAME = "picoclaw"


def now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now()}] {message}\n")


def write_request(payload: dict) -> None:
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    target = REQUESTS_DIR / f"{payload['id']}.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)


def docker_env() -> dict[str, str]:
    env = os.environ.copy()
    if env.get("DOCKER_HOST"):
        env.pop("DOCKER_CONTEXT", None)
        return env

    colima_socket = Path.home() / ".colima" / "default" / "docker.sock"
    if colima_socket.exists():
        env["DOCKER_HOST"] = f"unix://{colima_socket}"
        env.pop("DOCKER_CONTEXT", None)
        return env

    return env


def run_payload(payload: dict, timeout: int):
    target = payload.get("target") or "host"
    command = payload.get("command", "")
    cwd = payload.get("working_dir") or None
    if cwd in {"<nil>", "nil", "null", "None"}:
        cwd = None

    if target == "container_root":
        cmd = ["docker", "exec", "-u", "0"]
        if cwd:
            cmd.extend(["-w", cwd])
        cmd.extend([CONTAINER_NAME, "sh", "-lc", command])
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=docker_env(),
        )

    return subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def handle_request(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "approved":
      return

    payload["status"] = "running"
    payload["updated_at"] = now()
    write_request(payload)

    command = payload.get("command", "")
    timeout = int(payload.get("timeout_seconds") or 120)
    log(f"running {payload['id']} ({payload.get('target', 'host')}): {command}")

    exit_code = 0
    stdout = ""
    stderr = ""
    error = ""
    try:
        completed = run_payload(payload, timeout)
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        error = f"command timed out after {timeout} seconds"
    except Exception as exc:  # noqa: BLE001
        exit_code = 1
        error = str(exc)

    payload["exit_code"] = exit_code
    payload["stdout"] = stdout
    payload["stderr"] = stderr
    payload["error"] = error
    payload["completed_at"] = now()
    payload["updated_at"] = payload["completed_at"]
    payload["status"] = "completed" if exit_code == 0 and not error else "failed"
    write_request(payload)
    log(f"finished {payload['id']} with status {payload['status']}")


def loop() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log("host bridge started")

    def _shutdown(signum, _frame):
        log(f"host bridge stopping on signal {signum}")
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        for path in sorted(REQUESTS_DIR.glob("*.json")):
            try:
                handle_request(path)
            except Exception as exc:  # noqa: BLE001
                log(f"error while handling {path.name}: {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(loop())
