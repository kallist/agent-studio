from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

OSV_VULNERABILITY_URL = "https://api.osv.dev/v1/vulns/"
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH"}


def _severity(vulnerability_ids: set[str]) -> str:
    ordered = sorted(vulnerability_ids, key=lambda value: (not value.startswith("GHSA-"), value))
    for vulnerability_id in ordered:
        url = OSV_VULNERABILITY_URL + urllib.parse.quote(vulnerability_id, safe="-")
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                advisory = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError):
            continue
        database_specific = advisory.get("database_specific", {})
        severity = database_specific.get("severity")
        if isinstance(severity, str) and severity.upper() in {
            "LOW",
            "MODERATE",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }:
            return "MEDIUM" if severity.upper() == "MODERATE" else severity.upper()
    return "UNKNOWN"


def _load_exceptions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    exceptions = payload.get("exceptions")
    if not isinstance(exceptions, list):
        raise ValueError("dependency audit exceptions must contain an exceptions list")
    return [item for item in exceptions if isinstance(item, dict)]


def _exception_for(
    package: str, vulnerability_ids: set[str], exceptions: list[dict[str, Any]]
) -> dict[str, Any] | None:
    today = date.today()
    for exception in exceptions:
        if exception.get("package") != package:
            continue
        if exception.get("id") not in vulnerability_ids:
            continue
        expires = exception.get("expires")
        reason = exception.get("reason")
        classification = exception.get("classification")
        if not isinstance(expires, str) or date.fromisoformat(expires) < today:
            continue
        if not isinstance(reason, str) or len(reason.strip()) < 12:
            continue
        if classification not in {"dev-only", "build-only", "false-positive", "unreachable"}:
            continue
        return exception
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=Path("docs/dependency-audit-exceptions.json"),
    )
    args = parser.parse_args()
    payload = json.loads(args.audit_json.read_text(encoding="utf-8"))
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else None
    if not isinstance(dependencies, list):
        raise ValueError("pip-audit JSON must contain a dependency list")
    exceptions = _load_exceptions(args.exceptions)

    blocked: list[str] = []
    reported: list[str] = []
    for dependency in dependencies:
        package = str(dependency.get("name", "unknown"))
        skip_reason = dependency.get("skip_reason")
        if skip_reason and package != "agent-studio-api":
            blocked.append(f"{package}: dependency audit skipped")
            continue
        for vulnerability in dependency.get("vulns", []):
            vulnerability_ids = {
                str(vulnerability.get("id", "unknown")),
                *(str(value) for value in vulnerability.get("aliases", [])),
            }
            exception = _exception_for(package, vulnerability_ids, exceptions)
            primary_id = sorted(vulnerability_ids)[0]
            if exception is not None:
                reported.append(
                    f"EXCEPTED {package} {primary_id}: {exception['classification']}"
                )
                continue
            severity = _severity(vulnerability_ids)
            finding = f"{package} {primary_id}: severity={severity}"
            if severity in BLOCKING_SEVERITIES or severity == "UNKNOWN":
                blocked.append(finding)
            else:
                reported.append(f"REPORT {finding}")

    for finding in reported:
        print(finding)
    for finding in blocked:
        print(f"BLOCK {finding}", file=sys.stderr)
    if blocked:
        print(
            "High/Critical runtime advisories and unclassified advisories require a fix or "
            "a reviewed, expiring exception.",
            file=sys.stderr,
        )
        return 1
    print("Python runtime dependency severity policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
