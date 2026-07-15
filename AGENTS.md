# Workflow Lab Rules

## Mandatory unattended preflight

1. Read `knowledge/Home.md`, the relevant project `Memory.md`, and `Ver.md` before planning.
2. A `.codegraph/` index is mandatory. Use `codegraph explore` before grep/find for code
   understanding, and run `python3 tools/check_codegraph.py .` after code changes.
3. All Codex, Claude, and Agy/Gemini work must use the same orchestrator-generated
   `SAGE_KNOWLEDGE.md`; agents may read but never edit the shared snapshot or central vault.
4. Every successful code update must advance the project version and update its Obsidian
   `Ver.md`. Failed work is recorded in Memory but does not advance version.
5. Run `python3 tools/check_version_record.py --require-staged-update` before commit.
6. Web UI, website UI, desktop visual UI, and WPF/XAML design must use Google Stitch before
   implementation. Require a Stitch-exported, locked `STITCH_DESIGN.md`; if it must be generated
   and Stitch authentication is unavailable, stop and ask the user to complete Google account
   login or configure a Stitch API key/OAuth. Never print MCP headers while diagnosing access.
7. Automated tests, Promotion, and GitHub CI may report only `automated_gates_passed` or
   `ci_passed`. They must keep `r5_human_verification=pending` and `merge_authorized=false`;
   only a human may complete R5 or authorize ready/merge.

This repository benchmarks agent workflows. Preserve experimental validity.

1. Never expose `benchmarks/hidden/` to a benchmarked CLI.
2. Never let a benchmarked CLI edit `TASK.md`, `AGENTS.md`, or `tests/`.
3. Run each candidate workflow in its own directory under `runs/`.
4. Do not use flags that bypass approvals or sandboxing.
5. A workflow is successful only when public tests, hidden tests, integrity checks,
   and secret scanning all pass.
6. Keep raw model output and timing evidence under the corresponding run directory.
