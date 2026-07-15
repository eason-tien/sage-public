---
task_id: 20260714T011231216436Z-fix-verify-cwd-evidence-v0.1.21-claude-retry-2
project: multi-cli-workflow-lab
status: automated_gates_passed
observed_at: 2026-07-14T01:32:58.056465+00:00
route: standard
---
# fix-verify-cwd-evidence-v0.1.21-claude-retry-2

Project memory: [[Projects/multi-cli-workflow-lab/Memory]]
Version ledger: [[Projects/multi-cli-workflow-lab/Ver]]

## Contract

- Source HEAD: `ec07f113f2435317fff197610176e771bb33d955`
- Spec SHA-256: `bffa726505feb84996affdd74178073a4bf0d602a9ee9db8f1ac0375c947b045`
- Acceptance commands: 8 recorded by hash in preflight
- Languages: javascript, python, shell
- Version: `0.1.20` → `0.1.21` on success

## Capability preflight

- claude: ready — `2.1.207 (Claude Code)`
- git: ready — `git version 2.50.1 (Apple Git-155)`
- gitleaks: ready — `8.30.1`
- codegraph: ready — `1.1.6`
- obsidian: ready — `Obsidian desktop CLI available`
- evidence_signing_key: ready — `private and public key present`

## CodeGraph

- {"action": "init", "edges": 1778, "files": 35, "nodes": 652, "status": "current"}

## Result

- Changed files: scripts/selftest.ps1, scripts/selftest.sh, scripts/verify.ps1, scripts/verify.sh
- Failing checks: none

## Distilled lesson

Automated gates passed with an immutable candidate, current CodeGraph, and a shared knowledge briefing. Reuse this route and gate set.
