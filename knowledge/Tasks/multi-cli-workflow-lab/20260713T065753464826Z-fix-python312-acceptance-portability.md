---
task_id: 20260713T065753464826Z-fix-python312-acceptance-portability
project: multi-cli-workflow-lab
status: automated_gates_passed
observed_at: 2026-07-13T06:59:36.450320+00:00
route: high
---
# fix-python312-acceptance-portability

Project memory: [[Projects/multi-cli-workflow-lab/Memory]]
Version ledger: [[Projects/multi-cli-workflow-lab/Ver]]

## Contract

- Source HEAD: `5bc9957c2c4a0004e8a799ad9232854d5814ddf3`
- Spec SHA-256: `570f19e86f8297ec2ba515a480bb48c1f4707f493a4aec4f2108ee34b1efee31`
- Acceptance commands: 15 recorded by hash in preflight
- Languages: javascript, python, shell
- Version: `0.1.11` → `0.1.12` on success

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

- {"action": "sync", "edges": 1597, "files": 35, "nodes": 606, "status": "current"}

## Result

- Changed files: knowledge/Topics/Languages/javascript.md, knowledge/Topics/Languages/python.md, knowledge/Topics/Languages/shell.md, tests/test_workflow.py, tools/attest_repository.py, workflow/acceptance.py, workflow/promote.py, workflow/run.py, Tasks/multi-cli-workflow-lab/20260713T065753464826Z-fix-python312-acceptance-portability.md, knowledge/Projects/multi-cli-workflow-lab/Memory.md, knowledge/Projects/multi-cli-workflow-lab/State.json, knowledge/Projects/multi-cli-workflow-lab/Ver.md
- Failing checks: none

## Distilled lesson

Automated gates passed with an immutable candidate, current CodeGraph, and a shared knowledge briefing. Reuse this route and gate set.
