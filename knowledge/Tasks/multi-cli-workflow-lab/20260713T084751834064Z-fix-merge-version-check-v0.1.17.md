---
task_id: 20260713T084751834064Z-fix-merge-version-check-v0.1.17
project: multi-cli-workflow-lab
status: automated_gates_passed
observed_at: 2026-07-13T08:50:07.078877+00:00
route: high
---
# fix-merge-version-check-v0.1.17

Project memory: [[Projects/multi-cli-workflow-lab/Memory]]
Version ledger: [[Projects/multi-cli-workflow-lab/Ver]]

## Contract

- Source HEAD: `bf4c764d2f2ec984dfd7f9cae4d4f722654c113d`
- Spec SHA-256: `288cfdc70de3d8940678591eeac08039e9997f4868df725d8c713fe32c0f22bd`
- Acceptance commands: 16 recorded by hash in preflight
- Languages: javascript, python, shell
- Version: `0.1.16` → `0.1.17` on success

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

- {"action": "sync", "edges": 1617, "files": 35, "nodes": 614, "status": "current"}

## Result

- Changed files: knowledge/Projects/multi-cli-workflow-lab/Ver.md, knowledge/Tasks/multi-cli-workflow-lab/20260713T084751834064Z-fix-merge-version-check-v0.1.17.md, knowledge/Topics/Languages/javascript.md, knowledge/Topics/Languages/python.md, knowledge/Topics/Languages/shell.md, tests/test_knowledge.py, tools/check_version_record.py
- Failing checks: none

## Distilled lesson

Automated gates passed with an immutable candidate, current CodeGraph, and a shared knowledge briefing. Reuse this route and gate set.
