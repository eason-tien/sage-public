# Multi-CLI Benchmark Results

Generated from the raw run summaries and fresh local quality checks.

| Run | Flow | Functional | Seconds | Stages | Diff +/− | Ruff | Format | Biome | Excluded |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solo-agy-1 | solo-agy | 30 | 22.7 | 1 | +0/-0 | pass | fail | fail | invalid adapter invocation: --print consumed an option name as the prompt |
| solo-claude-1 | solo-claude | 100 | 87.5 | 1 | +81/-12 | pass | pass | pass |  |
| solo-agy-2 | solo-agy | 100 | 99.7 | 1 | +56/-14 | pass | fail | fail |  |
| solo-agy-3 | solo-agy | 100 | 121.1 | 1 | +53/-12 | pass | fail | fail |  |
| solo-claude-2 | solo-claude | 100 | 198.9 | 1 | +77/-12 | pass | fail | pass |  |
| solo-codex-1 | solo-codex | 100 | 296.0 | 1 | +116/-15 | pass | fail | pass |  |
| agy-codex-claude-gated-1 | agy-codex-claude-gated | 100 | 470.9 | 3 | +87/-14 | pass | pass | pass |  |
| claude-agy-review-1 | claude-agy-review | 100 | 479.5 | 3 | +74/-11 | pass | pass | fail |  |
| claude-agy-gated-1 | claude-agy-gated | 100 | 590.0 | 3 | +82/-11 | pass | pass | fail |  |
| tri-model-contract-1 | tri-model-contract | 100 | 715.1 | 4 | +76/-13 | pass | pass | pass |  |
| codex-claude-review-1 | codex-claude-review | 100 | 893.5 | 3 | +157/-14 | pass | fail | pass |  |

## Flow aggregates

| Flow | Runs | All functional | Median seconds | Maintainability pass rate |
|---|---:|---:|---:|---:|
| agy-codex-claude-gated | 1 | True | 470.9 | 100% |
| claude-agy-gated | 1 | True | 590.0 | 0% |
| claude-agy-review | 1 | True | 479.5 | 0% |
| codex-claude-review | 1 | True | 893.5 | 0% |
| solo-agy | 2 | True | 110.4 | 0% |
| solo-claude | 2 | True | 143.2 | 50% |
| solo-codex | 1 | True | 296.0 | 0% |
| tri-model-contract | 1 | True | 715.1 | 100% |
