---
task_id: 20260714T182533085203Z-unattended-governance-upgrade
project: multi-cli-workflow-lab
status: automated_gates_passed
observed_at: 2026-07-14T18:26:53.752629+00:00
route: high
---
# unattended-governance-upgrade

Project memory: [[Projects/multi-cli-workflow-lab/Memory]]
Version ledger: [[Projects/multi-cli-workflow-lab/Ver]]

## Contract

- Source HEAD: `86e35717baf9803c6d9ab300fcc738d4cf1d15a4`
- Spec SHA-256: `750dea144106b8f3e8c9ce2a37c6f4ecb6a23c0ecfaf2498b5fc9e5150f31618`
- Acceptance commands: 3 recorded by hash in preflight
- Languages: javascript, python, shell
- Version: `0.1.25` → `0.1.26` on success

## Capability preflight

- agy: ready — `1.1.2`
- codex: ready — `codex-cli 0.144.1`
- claude: ready — `2.1.207 (Claude Code)`
- git: ready — `git version 2.50.1 (Apple Git-155)`
- gitleaks: ready — `8.30.1`
- codegraph: ready — `1.1.6`
- obsidian: ready — `Obsidian desktop CLI available`
- evidence_signing_key: ready — `private and public key present`

## CodeGraph

- {"action": "sync", "edges": 3006, "files": 45, "nodes": 1002, "status": "current"}

## Result

- Changed files: .github/sage-merge-policy.json, .github/workflows/ci.yml, CHANGELOG.md, HOOKS.md, README.md, SAGE_RULES.md, VERSION, docs/fail-closed-merge.md, knowledge/Projects/multi-cli-workflow-lab/Memory.md, knowledge/Projects/multi-cli-workflow-lab/State.json, knowledge/Projects/multi-cli-workflow-lab/Ver.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T151402069586Z-unattended-knowledge-upgrade.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T160657218138Z-unattended-knowledge-upgrade.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T161057739973Z-unattended-knowledge-upgrade.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T161210896256Z-unattended-knowledge-upgrade.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T182011751757Z-unattended-knowledge-upgrade.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T182533085203Z-unattended-governance-upgrade.md, knowledge/Topics/Languages/javascript.md, knowledge/Topics/Languages/python.md, knowledge/Topics/Languages/shell.md, prompts/04-review-crosscheck.md, reports/governance-recovery-v0.13.2.md, reports/sprite-game-audit.json, reports/unattended-knowledge-audit.json, scripts/acceptance-lock.ps1, scripts/acceptance-lock.sh, scripts/claude-stop-hook.py, scripts/crosscheck.ps1, scripts/crosscheck.sh, scripts/selftest.ps1, scripts/selftest.sh, scripts/verify.ps1, scripts/verify.sh, tests/sop-run.test.js, tests/test_attest_repository.py, tests/test_audit_unattended_knowledge.py, tests/test_knowledge.py, tests/test_merge_pr.py, tests/test_sop_preflight.py, tests/test_stop_hook.py, tests/test_workflow.py, tools/attest_repository.py, tools/audit_unattended_knowledge.py, tools/check_version_record.py, tools/merge_pr.py, workflow/README.md, workflow/acceptance.py, workflow/evidence.py, workflow/knowledge.py, workflow/promote.py, workflow/run.py, workflow/version_snapshot.py, workflows/README.md, workflows/sop-preflight.py, workflows/sop-run.js
- Failing checks: none

## Distilled lesson

Automated gates passed with an immutable candidate, current CodeGraph, and a shared knowledge briefing. Reuse this route and gate set.
