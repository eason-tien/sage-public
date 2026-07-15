---
task_id: 20260713T062005041675Z-fix-pr-shallow-history-validation
project: multi-cli-workflow-lab
status: automated_gates_passed
observed_at: 2026-07-13T06:21:01.237549+00:00
route: high
---
# fix-pr-shallow-history-validation

Project memory: [[Projects/multi-cli-workflow-lab/Memory]]
Version ledger: [[Projects/multi-cli-workflow-lab/Ver]]

## Contract

- Source HEAD: `1c08a54e142ddc2343365a2dede9352eb23f06fc`
- Spec SHA-256: `0ff384bb392315df8530017b80ae4c08edee70d6bb5b57e29723973c4cec73a4`
- Acceptance commands: 9 recorded by hash in preflight
- Languages: javascript, python, shell
- Version: `0.1.8` → `0.1.9` on success

## Capability preflight

- agy: ready — `1.1.1`
- codex: ready — `codex-cli 0.144.1`
- claude: ready — `2.1.207 (Claude Code)`
- git: ready — `git version 2.50.1 (Apple Git-155)`
- gitleaks: ready — `8.30.1`
- codegraph: ready — `1.1.6`
- obsidian: ready — `Obsidian desktop CLI available`
- evidence_signing_key: ready — `private and public key present`

## CodeGraph

- {"action": "sync", "edges": 1566, "files": 34, "nodes": 594, "status": "current"}

## Result

- Changed files: .github/workflows/ci.yml, knowledge/Topics/Languages/javascript.md, knowledge/Topics/Languages/python.md, knowledge/Topics/Languages/shell.md, tools/check_version_record.py
- Failing checks: none

## Distilled lesson

Automated gates passed with an immutable candidate, current CodeGraph, and a shared knowledge briefing. Reuse this route and gate set.
