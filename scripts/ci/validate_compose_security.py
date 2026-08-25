from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _compose_config() -> dict[str, Any]:
    completed = subprocess.run(
        ["docker", "compose", "-f", "compose.yaml", "config", "--format", "json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-4000:])
    parsed = json.loads(completed.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("Compose config did not render an object.")
    return parsed


def _volume_text(volume: Any) -> str:
    if isinstance(volume, str):
        return volume
    if isinstance(volume, dict):
        return json.dumps(volume, sort_keys=True)
    return repr(volume)


def main() -> int:
    config = _compose_config()
    services = config.get("services")
    if not isinstance(services, dict):
        print("ERROR: Compose config has no services mapping.", file=sys.stderr)
        return 1

    failures: list[str] = []
    database = services.get("db")
    if not isinstance(database, dict):
        failures.append("db service is missing")
    elif database.get("ports"):
        failures.append("db service publishes a host port")

    for name, raw_service in services.items():
        if not isinstance(raw_service, dict):
            failures.append(f"{name} service is not an object")
            continue
        if raw_service.get("privileged") is True:
            failures.append(f"{name} service enables privileged mode")
        for volume in raw_service.get("volumes", []):
            if "docker.sock" in _volume_text(volume).casefold():
                failures.append(f"{name} service mounts the Docker socket")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("Compose security invariants passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
