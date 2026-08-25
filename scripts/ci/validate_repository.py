from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MAX_SCANNED_FILE_BYTES = 2 * 1024 * 1024
SECRET_PATTERNS = {
    "provider key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "authorization credential": re.compile(
        r"(?i)authorization\s*[:=]\s*(?:bearer|basic)\s+"
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_.=-]{20,}|[A-Za-z0-9+/=]{32,})"
    ),
}
CONFLICT_PATTERN = re.compile(r"^(?:<<<<<<<|=======|>>>>>>>)", re.MULTILINE)
FORBIDDEN_WORKFLOW_PATTERNS = {
    "pull_request_target exposes a high-risk PR trust boundary": re.compile(
        r"(?m)^\s*pull_request_target\s*:"
    ),
    "write-all permission is forbidden": re.compile(r"(?m)^\s*permissions\s*:\s*write-all"),
    "contents write is forbidden": re.compile(r"(?m)^\s*contents\s*:\s*write"),
    "global environment dump is forbidden": re.compile(
        r"(?m)^\s*(?:run:\s*)?(?:env|printenv|set)\s*$"
    ),
    "global Docker prune is forbidden": re.compile(
        r"docker\s+(?:system|volume|network)\s+prune"
    ),
}
FORBIDDEN_ARTIFACT_KEYS = {
    "authorization",
    "cookie",
    "database_url",
    "db_password",
    "deepseek_api_key",
    "document_body",
    "memory_content",
    "openai_api_key",
    "password",
    "provider_trace",
    "secret",
    "set_cookie",
    "token",
}


def _tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).decode(errors="surrogateescape")
    return [ROOT / value for value in output.split("\0") if value]


def _read_text(path: Path) -> str | None:
    if path.stat().st_size > MAX_SCANNED_FILE_BYTES:
        return None
    data = path.read_bytes()
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="replace")


def validate_tracked_repository() -> list[str]:
    failures: list[str] = []
    for path in _tracked_files():
        if not path.exists():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.name.startswith(".env") and path.name != ".env.example":
            failures.append(f"tracked environment file: {relative}")
        if path.suffix.casefold() in {".pem", ".key", ".p12", ".pfx"}:
            failures.append(f"tracked private credential file: {relative}")
        text_content = _read_text(path)
        if text_content is None:
            continue
        if CONFLICT_PATTERN.search(text_content):
            failures.append(f"merge conflict marker: {relative}")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text_content):
                failures.append(f"possible {label}: {relative}")

    workflow_directory = ROOT / ".github" / "workflows"
    workflow_files = sorted(workflow_directory.glob("*.y*ml"))
    if not workflow_files:
        failures.append("no GitHub Actions workflows found")
    for workflow_path in workflow_files:
        relative = workflow_path.relative_to(ROOT).as_posix()
        content = workflow_path.read_text(encoding="utf-8")
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            failures.append(f"invalid YAML in {relative}: {exc}")
            continue
        if not isinstance(parsed, dict) or not isinstance(parsed.get("jobs"), dict):
            failures.append(f"workflow has no jobs mapping: {relative}")
            continue
        for label, pattern in FORBIDDEN_WORKFLOW_PATTERNS.items():
            if pattern.search(content):
                failures.append(f"{label}: {relative}")
        if parsed.get("permissions") != {"contents": "read"}:
            failures.append(f"workflow permissions are not contents: read: {relative}")
        for job_name, job in parsed["jobs"].items():
            if not isinstance(job, dict) or "timeout-minutes" not in job:
                failures.append(f"job lacks timeout-minutes: {relative}:{job_name}")
    return failures


def _walk_artifact(value: Any, path: str, failures: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
            if normalized in FORBIDDEN_ARTIFACT_KEYS:
                failures.append(f"forbidden artifact key: {path}.{key}")
            _walk_artifact(nested, f"{path}.{key}", failures)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_artifact(nested, f"{path}[{index}]", failures)
    elif isinstance(value, str):
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(value):
                failures.append(f"possible {label} in artifact value: {path}")


def validate_artifacts(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(ROOT):
            failures.append(f"artifact is outside repository: {path}")
            continue
        if not resolved.is_file() or resolved.suffix != ".json":
            failures.append(f"artifact must be an existing JSON file: {path}")
            continue
        if resolved.stat().st_size > 1024 * 1024:
            failures.append(f"artifact exceeds 1 MiB: {path}")
            continue
        try:
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"invalid artifact JSON {path}: {type(exc).__name__}")
            continue
        _walk_artifact(value, path.as_posix(), failures)
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="*", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures = validate_tracked_repository()
    if args.artifacts:
        failures.extend(validate_artifacts(args.artifacts))
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("Repository and artifact safety validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
