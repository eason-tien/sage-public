---
task_id: 20260713T060955348295Z-fix-pr-head-version-validation
project: multi-cli-workflow-lab
status: automated_gates_passed
observed_at: 2026-07-13T06:11:10.652143+00:00
route: high
---
# fix-pr-head-version-validation

Project memory: [[Projects/multi-cli-workflow-lab/Memory]]
Version ledger: [[Projects/multi-cli-workflow-lab/Ver]]

## Contract

- Source HEAD: `56f897143926e283e11a7bffb78f4acff78bb09f`
- Spec SHA-256: `60529ca1f317dfc9bb9ab390890d2f6aa9bcf49ab9a235073bb91b565acfa6c1`
- Acceptance commands: 7 recorded by hash in preflight
- Languages: javascript, python, shell
- Version: `0.1.7` → `0.1.8` on success

## Capability preflight

- agy: ready — `1.1.1`
- codex: ready — `codex-cli 0.144.1`
- claude: ready — `2.1.207 (Claude Code)`
- git: ready — `git version 2.50.1 (Apple Git-155)`
- gitleaks: ready — `8.30.1`
- codegraph: ready — `1.1.6`
- obsidian: ready — `Obsidian desktop CLI available`

## CodeGraph

- {"action": "sync", "edges": 1564, "files": 34, "nodes": 593, "status": "current"}

## Result

- Changed files: .github/workflows/ci.yml, knowledge/Tasks/multi-cli-workflow-lab/20260713T060955348295Z-fix-pr-head-version-validation.md, knowledge/Topics/Languages/javascript.md, knowledge/Topics/Languages/python.md, knowledge/Topics/Languages/shell.md, tools/check_version_record.py
- Failing checks: none

## Distilled lesson

Automated gates passed with an immutable candidate, current CodeGraph, and a shared knowledge briefing. Reuse this route and gate set.
