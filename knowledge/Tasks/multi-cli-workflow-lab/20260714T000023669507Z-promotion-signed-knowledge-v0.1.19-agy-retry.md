---
task_id: 20260714T000023669507Z-promotion-signed-knowledge-v0.1.19-agy-retry
project: multi-cli-workflow-lab
status: failed
observed_at: 2026-07-14T00:08:40.653347+00:00
route: fast
---
# promotion-signed-knowledge-v0.1.19-agy-retry

Project memory: [[Projects/multi-cli-workflow-lab/Memory]]
Version ledger: [[Projects/multi-cli-workflow-lab/Ver]]

## Contract

- Source HEAD: `5937fe95a14b38b5b4c46ad9197d0d598724c54a`
- Spec SHA-256: `80488eb47f3bb3c4d347cee76a7d31253fa827adfc15c649ea55826ddb666ecd`
- Acceptance commands: 5 recorded by hash in preflight
- Languages: javascript, python, shell
- Version: `0.1.18` → `0.1.19` on success

## Capability preflight

- agy: ready — `1.1.2`
- git: ready — `git version 2.50.1 (Apple Git-155)`
- gitleaks: ready — `8.30.1`
- codegraph: ready — `1.1.6`
- obsidian: ready — `Obsidian desktop CLI available`
- evidence_signing_key: ready — `private and public key present`

## CodeGraph

- {"action": "init", "edges": 1647, "files": 35, "nodes": 620, "status": "current"}

## Result

- Changed files: workflow/README.md, workflow/evidence.py, workflow/knowledge.py, workflow/promote.py
- Failing checks: acceptance_2

## Distilled lesson

Task failed closed. Investigate these checks before retrying: acceptance_2
