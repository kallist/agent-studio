from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    payload: dict[str, Any] = json.loads(args.artifact.read_text(encoding="utf-8"))

    print("### Performance")
    print()
    print("| Scenario | Count | p50 ms | p95 ms | Throughput/s | Failures |")
    print("|---|---:|---:|---:|---:|---:|")
    for name, metric in payload["scenarios"].items():
        print(
            f"| {name} | {metric['count']} | {metric['p50_ms']} | "
            f"{metric['p95_ms']} | {metric['throughput_per_s']} | "
            f"{metric['failure_count']} |"
        )
    regressions = payload.get("catastrophic_regressions", [])
    print()
    print(f"Catastrophic regressions: {len(regressions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
