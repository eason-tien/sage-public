---
task_id: 20260714T161057739973Z-unattended-knowledge-upgrade
project: multi-cli-workflow-lab
status: automated_gates_passed
observed_at: 2026-07-14T16:11:54.017515+00:00
route: high
---
# unattended-knowledge-upgrade

Project memory: [[Projects/multi-cli-workflow-lab/Memory]]
Version ledger: [[Projects/multi-cli-workflow-lab/Ver]]

## Contract

- Source HEAD: `86e35717baf9803c6d9ab300fcc738d4cf1d15a4`
- Spec SHA-256: `c9df870ab4dd7adf7c33b58167fc51f109ac7f3bc006dfbd752b128640047566`
- Acceptance commands: 3 recorded by hash in preflight
- Languages: javascript, python, shell
- Version: `0.1.23` → `0.1.24` on success

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

- {"action": "sync", "edges": 2727, "files": 44, "nodes": 943, "status": "current"}

## Result

- Changed files: .github/sage-merge-policy.json, .github/workflows/ci.yml, CHANGELOG.md, HOOKS.md, README.md, VERSION, docs/fail-closed-merge.md, knowledge/Projects/multi-cli-workflow-lab/Memory.md, knowledge/Projects/multi-cli-workflow-lab/State.json, knowledge/Projects/multi-cli-workflow-lab/Ver.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T151402069586Z-unattended-knowledge-upgrade.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T160657218138Z-unattended-knowledge-upgrade.md, knowledge/Tasks/multi-cli-workflow-lab/20260714T161057739973Z-unattended-knowledge-upgrade.md, knowledge/Topics/Languages/javascript.md, knowledge/Topics/Languages/python.md, knowledge/Topics/Languages/shell.md, reports/governance-recovery-v0.13.2.md, reports/unattended-knowledge-audit.json, scripts/acceptance-lock.sh, scripts/claude-stop-hook.py, scripts/crosscheck.ps1, scripts/crosscheck.sh, scripts/selftest.ps1, scripts/selftest.sh, tests/sop-run.test.js, tests/test_attest_repository.py, tests/test_audit_unattended_knowledge.py, tests/test_knowledge.py, tests/test_merge_pr.py, tests/test_sop_preflight.py, tests/test_stop_hook.py, tests/test_workflow.py, tools/attest_repository.py, tools/audit_unattended_knowledge.py, tools/check_version_record.py, tools/merge_pr.py, workflow/evidence.py, workflow/knowledge.py, workflow/run.py, workflows/README.md, workflows/sop-preflight.py, workflows/sop-run.js
- Failing checks: none

## Distilled lesson

Automated gates passed with an immutable candidate, current CodeGraph, and a shared knowledge briefing. Reuse this route and gate set.
