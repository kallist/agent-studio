from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TERMINAL_RUNS = {"completed", "failed", "cancelled"}
TERMINAL_JOBS = {"completed", "failed"}


class ReliabilityFailure(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    capture: bool = False,
    timeout: int = 600,
) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        timeout=timeout,
    )
    if completed.returncode != 0:
        output = (completed.stdout or "").strip()
        raise ReliabilityFailure(
            f"Command failed ({completed.returncode}): {' '.join(command)}"
            + (f"\n{output[-4000:]}" if output else "")
        )
    return (completed.stdout or "").strip()


class ComposeHarness:
    def __init__(
        self,
        project_name: str,
        web_port: int,
        api_port: int,
        artifact_path: Path,
    ) -> None:
        self.project_name = project_name
        self.web_url = f"http://127.0.0.1:{web_port}"
        self.api_url = f"http://127.0.0.1:{api_port}"
        self.artifact_path = artifact_path
        self.env = os.environ.copy()
        self.env.update(
            {
                "API_PORT": str(api_port),
                "WEB_PORT": str(web_port),
                "RUN_REAL_DEEPSEEK_TESTS": "0",
                "RUN_REAL_OPENAI_TESTS": "0",
            }
        )
        for secret_name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            self.env.pop(secret_name, None)
        self.compose = [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "-f",
            "compose.yaml",
        ]
        self.timings: dict[str, float] = {}
        self.results: dict[str, str] = {}

    def compose_run(
        self,
        *arguments: str,
        capture: bool = False,
        timeout: int = 600,
    ) -> str:
        return _run(
            [*self.compose, *arguments],
            env=self.env,
            capture=capture,
            timeout=timeout,
        )

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 10,
    ) -> tuple[int, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{base_url or self.api_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            return exc.code, parsed
        except (OSError, TimeoutError) as exc:
            raise ReliabilityFailure(f"{method} {path} failed safely: {type(exc).__name__}") from exc

    def upload_text(self, knowledge_base_id: str) -> dict[str, Any]:
        boundary = "agent-studio-v1-boundary"
        content = (
            "Agent Studio v1 reliability evidence. The recovery codename is glacier-5192.\n\n"
            "This synthetic document is safe for deterministic pgvector validation."
        ).encode()
        prefix = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="reliability.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        body = prefix + content + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            f"{self.api_url}/knowledge-bases/{knowledge_base_id}/documents",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 202:
                raise ReliabilityFailure("RAG upload was not accepted.")
            return json.loads(response.read().decode())

    def wait_http(
        self,
        url: str,
        expected_status: int,
        *,
        timeout_seconds: float,
    ) -> float:
        started = time.monotonic()
        deadline = started + timeout_seconds
        last_status: int | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    last_status = response.status
            except urllib.error.HTTPError as exc:
                last_status = exc.code
            except (OSError, TimeoutError):
                last_status = None
            if last_status == expected_status:
                return round(time.monotonic() - started, 3)
            time.sleep(0.25)
        raise ReliabilityFailure(
            f"{url} did not reach HTTP {expected_status}; last status was {last_status}."
        )

    def wait_state(
        self,
        path: str,
        key: str,
        terminal: set[str],
        *,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status, body = self.request("GET", path)
            if status == 200 and body[key] in terminal:
                return body
            time.sleep(0.1)
        raise ReliabilityFailure(f"{path} did not reach one of {sorted(terminal)}.")

    def create_product_evidence(self) -> dict[str, str]:
        status, agent = self.request(
            "POST",
            "/agents",
            {
                "name": "V1 Reliability Calculator",
                "instructions": "Use the calculator deterministically.",
                "runtime_mode": "mock",
                "tools": ["calculator"],
            },
        )
        if status != 201:
            raise ReliabilityFailure(f"Agent creation failed with HTTP {status}.")
        status, accepted = self.request(
            "POST",
            f"/agents/{agent['id']}/runs",
            {"input": "Calculate 128 * 37 + 456"},
        )
        if status != 202:
            raise ReliabilityFailure(f"Calculator run failed with HTTP {status}.")
        run = self.wait_state(
            f"/runs/{accepted['id']}", "status", TERMINAL_RUNS
        )
        if run["status"] != "completed" or run["output"] != "5192":
            raise ReliabilityFailure("Calculator did not complete with 5192.")

        status, memory_accepted = self.request(
            "POST",
            f"/agents/{agent['id']}/runs",
            {"input": "Remember that my project codename is glacier-5192"},
        )
        if status != 202:
            raise ReliabilityFailure("Memory run was not accepted.")
        memory_run = self.wait_state(
            f"/runs/{memory_accepted['id']}", "status", TERMINAL_RUNS
        )
        if memory_run["status"] != "completed":
            raise ReliabilityFailure("Memory run did not complete.")
        status, memories = self.request("GET", f"/agents/{agent['id']}/memories")
        if status != 200 or not memories:
            raise ReliabilityFailure("Durable Memory evidence was not persisted.")

        status, knowledge_base = self.request(
            "POST",
            "/knowledge-bases",
            {"name": "V1 Reliability RAG", "description": "Synthetic evidence"},
        )
        if status != 201:
            raise ReliabilityFailure("Knowledge Base creation failed.")
        upload = self.upload_text(knowledge_base["id"])
        ingestion = self.wait_state(
            f"/ingestion-jobs/{upload['ingestion_job']['id']}",
            "state",
            TERMINAL_JOBS,
        )
        if ingestion["state"] != "completed":
            raise ReliabilityFailure("RAG ingestion did not complete.")
        status, search = self.request(
            "POST",
            f"/knowledge-bases/{knowledge_base['id']}/search",
            {"query": "What is the recovery codename?", "top_k": 3, "hybrid": True},
        )
        if status != 200 or not search["results"]:
            raise ReliabilityFailure("pgvector RAG search returned no evidence.")

        status, suite = self.request(
            "POST",
            "/evaluation-suites",
            {
                "name": "V1 Reliability Evaluation",
                "agent_id": agent["id"],
                "cases": [
                    {
                        "name": "Calculator remains deterministic",
                        "input": "Calculate 128 * 37 + 456",
                        "graders": [
                            {"type": "run_status"},
                            {"type": "exact_match", "value": "5192"},
                            {"type": "tool_selected", "tool_name": "calculator"},
                        ],
                    }
                ],
            },
        )
        if status != 201:
            raise ReliabilityFailure("Evaluation Suite creation failed.")
        status, evaluation_accepted = self.request(
            "POST", f"/evaluation-suites/{suite['id']}/runs"
        )
        if status != 202:
            raise ReliabilityFailure("Evaluation Run was not accepted.")
        evaluation = self.wait_state(
            f"/evaluation-runs/{evaluation_accepted['id']}",
            "status",
            TERMINAL_RUNS,
        )
        if evaluation["status"] != "completed" or evaluation["passed_cases"] != 1:
            raise ReliabilityFailure("Evaluation evidence did not PASS.")

        self.results.update(
            {
                "calculator": "PASS",
                "memory": "PASS",
                "rag_pgvector": "PASS",
                "evaluation": "PASS",
            }
        )
        return {
            "agent_id": agent["id"],
            "run_id": run["id"],
            "knowledge_base_id": knowledge_base["id"],
            "evaluation_run_id": evaluation["id"],
        }

    def verify_evidence(
        self, evidence: dict[str, str], *, through_web: bool = False
    ) -> None:
        prefix = "/api" if through_web else ""
        base_url = self.web_url if through_web else self.api_url
        checks = [
            f"/agents/{evidence['agent_id']}",
            f"/runs/{evidence['run_id']}",
            f"/knowledge-bases/{evidence['knowledge_base_id']}",
            f"/evaluation-runs/{evidence['evaluation_run_id']}",
        ]
        for path in checks:
            status, _body = self.request(
                "GET", f"{prefix}{path}", base_url=base_url
            )
            if status != 200:
                raise ReliabilityFailure(f"Persisted evidence disappeared after restart: {path}")

        status, memories = self.request(
            "GET",
            f"{prefix}/agents/{evidence['agent_id']}/memories",
            base_url=base_url,
        )
        if status != 200 or not memories:
            raise ReliabilityFailure("Durable Memory did not reload after restart.")
        status, search = self.request(
            "POST",
            f"{prefix}/knowledge-bases/{evidence['knowledge_base_id']}/search",
            {"query": "What is the recovery codename?", "top_k": 3, "hybrid": True},
            base_url=base_url,
        )
        if status != 200 or not search["results"]:
            raise ReliabilityFailure("pgvector RAG evidence did not reload after restart.")

    def verify_pool_bound(self) -> None:
        for _ in range(200):
            status, _body = self.request("GET", "/agents")
            if status != 200:
                raise ReliabilityFailure("Connection leak request loop failed.")
        active_connections = int(
            self.compose_run(
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "agent_studio",
                "-d",
                "agent_studio",
                "-Atc",
                "SELECT numbackends FROM pg_stat_database WHERE datname = current_database()",
                capture=True,
                timeout=30,
            ).splitlines()[-1]
        )
        if active_connections > 10:
            raise ReliabilityFailure(
                f"Connection count exceeded the bounded sanity limit: {active_connections}."
            )
        self.results["connection_leak_sanity"] = "PASS"

    def image_identity(self, service: str) -> str:
        container_id = self.compose_run("ps", "-q", service, capture=True)
        if not container_id:
            raise ReliabilityFailure(f"No container found for {service}.")
        return _run(
            ["docker", "inspect", "--format", "{{.Image}}", container_id],
            env=self.env,
            capture=True,
            timeout=30,
        )

    def verify_browser_reconnect(self) -> None:
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            raise ReliabilityFailure("pnpm is required for the browser reconnect check.")
        browser_env = self.env.copy()
        browser_env["DOCKER_E2E_BASE_URL"] = self.web_url
        _run(
            [pnpm, "--dir", "apps/web", "e2e:restart"],
            env=browser_env,
            timeout=180,
        )
        self.results["web_browser_reconnect"] = "PASS"

    def write_artifact(self, status: str) -> None:
        metadata = {
            "schema_version": 1,
            "status": status,
            "delivery_meaning": "validated artifact; not publicly deployed",
            "git_sha": _run(
                ["git", "rev-parse", "HEAD"], env=self.env, capture=True, timeout=30
            ),
            "timestamp": datetime.now(UTC).isoformat(),
            "project_name": self.project_name,
            "images": {
                "api": self.image_identity("api") if status == "DELIVERY READY" else None,
                "web": self.image_identity("web") if status == "DELIVERY READY" else None,
            },
            "results": self.results,
            "timings_seconds": self.timings,
            "public_deployment": "NO",
            "registry_push": "NO",
        }
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    def capture_diagnostics(self) -> None:
        print("Agent Studio v1 Compose diagnostics (bounded):", file=sys.stderr)
        try:
            print(self.compose_run("ps", "-a", capture=True, timeout=30), file=sys.stderr)
            for service in ("db", "api", "web"):
                logs = self.compose_run(
                    "logs", "--no-color", "--tail", "120", service, capture=True, timeout=30
                )
                print(f"[{service}]\n{logs[-12000:]}", file=sys.stderr)
        except Exception as exc:  # diagnostics must not hide the original failure
            print(f"Diagnostic capture failed: {type(exc).__name__}", file=sys.stderr)

    def cleanup(self) -> Exception | None:
        try:
            self.compose_run(
                "down", "--volumes", "--remove-orphans", timeout=180
            )
            return None
        except Exception as exc:
            print(f"Project-scoped cleanup failed: {type(exc).__name__}", file=sys.stderr)
            return exc


def run(args: argparse.Namespace) -> None:
    harness = ComposeHarness(
        args.project_name,
        args.web_port,
        args.api_port,
        Path(args.artifact),
    )
    succeeded = False
    try:
        harness.compose_run("config", "--quiet", timeout=60)
        cold_started = time.monotonic()
        harness.compose_run(
            "up", "--build", "--detach", "--wait", "--wait-timeout", "300"
        )
        harness.timings["cold_start"] = round(time.monotonic() - cold_started, 3)
        harness.wait_http(f"{harness.api_url}/health", 200, timeout_seconds=30)
        harness.wait_http(harness.web_url, 200, timeout_seconds=30)
        evidence = harness.create_product_evidence()

        harness.compose_run("restart", "api", timeout=120)
        harness.timings["api_restart_recovery"] = harness.wait_http(
            f"{harness.api_url}/health", 200, timeout_seconds=60
        )
        harness.verify_evidence(evidence)
        harness.results["api_restart_persistence"] = "PASS"

        harness.compose_run("restart", "web", timeout=120)
        harness.timings["web_restart_recovery"] = harness.wait_http(
            harness.web_url, 200, timeout_seconds=60
        )
        harness.verify_evidence(evidence, through_web=True)
        if args.browser_check:
            harness.verify_browser_reconnect()
        harness.results["web_restart"] = "PASS"

        harness.compose_run("stop", "db", timeout=60)
        harness.timings["db_failure_detection"] = harness.wait_http(
            f"{harness.api_url}/health", 503, timeout_seconds=30
        )
        failure_started = time.monotonic()
        failure_status, failure_body = harness.request("GET", "/agents", timeout=10)
        failure_duration = time.monotonic() - failure_started
        serialized_failure = json.dumps(failure_body)
        if failure_status < 500 or failure_duration > 12:
            raise ReliabilityFailure("DB transient failure was not bounded and explicit.")
        if "postgresql+asyncpg" in serialized_failure or "password" in serialized_failure.lower():
            raise ReliabilityFailure("DB transient failure exposed credential-shaped details.")
        harness.compose_run("start", "db", timeout=60)
        harness.timings["db_restart_recovery"] = harness.wait_http(
            f"{harness.api_url}/health", 200, timeout_seconds=90
        )
        harness.verify_evidence(evidence)
        harness.results["db_restart_pool_recovery"] = "PASS"
        harness.verify_pool_bound()

        status, blocking_run = harness.request(
            "POST",
            f"/agents/{evidence['agent_id']}/runs",
            {"input": "__playwright_wait_for_cancel__"},
        )
        if status != 202:
            raise ReliabilityFailure("Shutdown probe run was not accepted.")
        shutdown_run_id = blocking_run["id"]
        harness.wait_state(
            f"/runs/{shutdown_run_id}", "status", {"running"}, timeout_seconds=15
        )
        harness.compose_run("stop", "-t", "30", "api", timeout=60)
        api_container = harness.compose_run("ps", "-a", "-q", "api", capture=True)
        exit_code = _run(
            ["docker", "inspect", "--format", "{{.State.ExitCode}}", api_container],
            env=harness.env,
            capture=True,
            timeout=30,
        )
        shutdown_logs = harness.compose_run(
            "logs", "--no-color", "--tail", "80", "api", capture=True
        )
        graceful_exit = exit_code == "0" or (
            exit_code == "143" and "Application shutdown complete." in shutdown_logs
        )
        if not graceful_exit:
            raise ReliabilityFailure(f"API graceful stop exit code was {exit_code}.")
        harness.compose_run("start", "api", timeout=60)
        harness.wait_http(f"{harness.api_url}/health", 200, timeout_seconds=60)
        shutdown_run = harness.wait_state(
            f"/runs/{shutdown_run_id}", "status", TERMINAL_RUNS, timeout_seconds=15
        )
        if shutdown_run["status"] not in {"cancelled", "failed"}:
            raise ReliabilityFailure("In-flight shutdown run did not become terminal.")
        status, shutdown_events = harness.request(
            "GET", f"/runs/{shutdown_run_id}/events"
        )
        terminal_events = [
            event
            for event in shutdown_events if event["type"] in {
                "run.completed",
                "run.failed",
                "run.cancelled",
            }
        ]
        if status != 200 or len(terminal_events) != 1:
            raise ReliabilityFailure("In-flight shutdown run has invalid terminal events.")
        harness.results["graceful_shutdown"] = "PASS"

        harness.compose_run("down", "--remove-orphans", timeout=180)
        warm_started = time.monotonic()
        harness.compose_run("up", "--detach", "--wait", "--wait-timeout", "180")
        harness.timings["warm_start"] = round(time.monotonic() - warm_started, 3)
        harness.verify_evidence(evidence)
        harness.results["down_up_persistence"] = "PASS"
        harness.results["idempotent_startup"] = "PASS"

        harness.write_artifact("DELIVERY READY")
        succeeded = True
        print(json.dumps({"status": "DELIVERY READY", "results": harness.results}, indent=2))
    except Exception:
        harness.capture_diagnostics()
        raise
    finally:
        cleanup_error = harness.cleanup()
        if not succeeded and harness.artifact_path.exists():
            harness.artifact_path.unlink()
        if cleanup_error is not None and succeeded:
            if harness.artifact_path.exists():
                harness.artifact_path.unlink()
            raise ReliabilityFailure("Project-scoped Docker cleanup failed.") from cleanup_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run bounded, project-scoped Agent Studio Docker reliability validation."
    )
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--web-port", type=int, default=3300)
    parser.add_argument("--api-port", type=int, default=8300)
    parser.add_argument(
        "--artifact", default=".artifacts/delivery-metadata.json"
    )
    parser.add_argument("--browser-check", action="store_true")
    args = parser.parse_args()
    if not args.project_name.startswith("agent-studio-v1-"):
        parser.error("--project-name must start with agent-studio-v1-")
    if not (1024 <= args.web_port <= 65535 and 1024 <= args.api_port <= 65535):
        parser.error("ports must be between 1024 and 65535")
    return args


if __name__ == "__main__":
    run(parse_args())
