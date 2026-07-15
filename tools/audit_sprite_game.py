#!/usr/bin/env python3
"""Run public and hidden audit gates for the SAGE sprite game."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.request import urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.gates import select_plugin_commands


ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "examples" / "sprite-audit-game"
HIDDEN = ROOT / "benchmarks" / "sprite-game-hidden" / "game-hidden.test.js"


def portable(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(str(ROOT), "$PROJECT_ROOT")
    if isinstance(value, list):
        return [portable(item) for item in value]
    if isinstance(value, dict):
        return {key: portable(item) for key, item in value.items()}
    return value


def execute(command: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return {
            "command": portable(command),
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": completed.stdout,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError) as error:
        return {
            "command": portable(command),
            "exit_code": 124 if isinstance(error, subprocess.TimeoutExpired) else 127,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": str(error),
        }


def redact_hidden_check(check: dict[str, Any]) -> dict[str, Any]:
    """Keep deterministic evidence while withholding hidden test details."""
    output = str(check.get("output", ""))
    encoded = output.encode("utf-8", errors="replace")
    return {
        **check,
        "command": ["<redacted-hidden-test>"],
        "output": {
            "redacted": True,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
        },
    }


def acceptance_lock_check() -> dict[str, Any]:
    acceptance = GAME / "acceptance.txt"
    lock = GAME / "acceptance.txt.lock"
    if not acceptance.is_file() or not lock.is_file():
        return {"exit_code": 2, "output": "acceptance lock is missing"}
    digest = hashlib.sha256(acceptance.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    locked = lock.read_text(encoding="utf-8").split()[0]
    return {
        "exit_code": 0 if digest == locked else 2,
        "output": {"expected": locked, "actual": digest},
    }


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def http_smoke() -> dict[str, Any]:
    handler = partial(QuietHandler, directory=str(GAME))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results: dict[str, Any] = {}
    try:
        for path in ("index.html", "game.js", "game-core.js", "styles.css"):
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/{path}", timeout=5
            ) as response:
                content = response.read()
                results[path] = {
                    "status": response.status,
                    "bytes": len(content),
                }
    except Exception as error:
        return {"exit_code": 1, "output": str(error)}
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    passed = all(
        item["status"] == 200 and item["bytes"] > 100 for item in results.values()
    )
    return {"exit_code": 0 if passed else 1, "output": results}


def structural_ui_check() -> dict[str, Any]:
    html = (GAME / "index.html").read_text(encoding="utf-8")
    core = (GAME / "game-core.js").read_text(encoding="utf-8")
    required_html = [
        'id="game"',
        'id="audit-json"',
        'data-direction="up"',
        'aria-live="polite"',
        'type="module"',
    ]
    missing = [marker for marker in required_html if marker not in html]
    unsafe_state = (
        'r5HumanVerification: "pending"' not in core
        or "mergeAuthorized: false" not in core
    )
    return {
        "exit_code": 1 if missing or unsafe_state else 0,
        "output": {"missing": missing, "unsafe_state": unsafe_state},
    }


def plugin_check() -> dict[str, Any]:
    changed = [
        str(path.relative_to(GAME)) for path in GAME.rglob("*") if path.is_file()
    ]
    commands = dict(select_plugin_commands(GAME, changed))
    expected = ["node", "--test", "test/game-core.test.js"]
    return {
        "exit_code": 0 if commands.get("sprite_game_tests") == expected else 1,
        "output": portable(commands),
    }


def run_audit(*, public_only: bool) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {
        "public_node_tests": execute(
            ["node", "--test", "test/game-core.test.js"], GAME
        ),
        "biome": execute(
            [
                "biome",
                "check",
                "index.html",
                "styles.css",
                "game-core.js",
                "game.js",
                "package.json",
                ".sage/gates.json",
            ],
            GAME,
        ),
        "http_smoke": http_smoke(),
        "structural_ui": structural_ui_check(),
        "plugin_discovery": plugin_check(),
    }
    if not public_only:
        checks.update(
            {
                "acceptance_lock": acceptance_lock_check(),
                "hidden_node_tests": redact_hidden_check(
                    execute(["node", "--test", str(HIDDEN)], ROOT)
                ),
                "gitleaks": execute(
                    [
                        "gitleaks",
                        "detect",
                        "--no-git",
                        "--redact",
                        "--source",
                        str(GAME),
                    ],
                    GAME,
                ),
            }
        )
    passed = all(check["exit_code"] == 0 for check in checks.values())
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "automated_gates_passed": passed,
        "r5_human_verification": "pending",
        "merge_authorized": False,
        "public_only": public_only,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="run all gates without rewriting the durable audit report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "sprite-game-audit.json",
    )
    args = parser.parse_args()
    result = run_audit(public_only=args.public_only)
    if not args.public_only and not args.no_write:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "automated_gates_passed": result["automated_gates_passed"],
                "r5_human_verification": "pending",
                "public_only": args.public_only,
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["automated_gates_passed"] else 1)


if __name__ == "__main__":
    main()
