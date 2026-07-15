# Completion Audit

## Objective 1 — build the best process using GitHub projects and engineering judgment

**Proven.** GitHub candidates were evaluated, deterministic tools were installed, and an
evidence-gated risk-adaptive process was implemented in `workflow/`. The selection rationale is
recorded in `process-recommendation.md`.

## Objective 2 — test multiple processes and select the best

**Proven.** The lab executed solo Codex, solo Claude, solo Agy, two sequential-review orderings,
a reviewer-decision-gated variant, a double-plan tri-model flow, and the optimized
Agy→Codex→Claude high route. Valid benchmark results are in `benchmark-results.json`; the invalid
Agy adapter invocation is explicitly excluded rather than silently deleted.

## Objective 3 — actual testing and audit after each process

**Proven.** Every benchmark run recorded public tests, hidden Python/Node acceptance, protected
file checks, Gitleaks, diff metrics, exit codes, and timings. Fresh Ruff/Biome audits were added.
The correct oracle passed every hidden test, and the intentionally broken fixture remains
discriminating. The reusable fast route and SAGE high route received additional independent
post-run audits.

## Objective 4 — act as a new process-development engineer

**Proven.** The work produced a benchmark design, faulty fixture, hidden acceptance, oracle,
multi-CLI adapters, result aggregator, risk router, reusable isolated runner, evidence schema,
scope/hash gates, correction decision rule, Promotion Gate, unit tests, pre-commit hooks, and
non-model CI.
Failures in the process itself were treated as defects and fixed:

- Agy `--print` positional argument was initially miswired.
- Node hidden-test invocation initially passed the workspace as a second test file.
- formatter gates initially scanned unrelated legacy files.
- unexpected temporary files were initially not rejected.
- Git stderr warnings initially polluted parsed file lists.
- reviewer findings initially triggered rework without enough contractual evidence.
- the first standalone Promotion CLI invocation exposed an import-path defect; a CLI smoke test
  now prevents regression.

## Objective 6 — close the identified P0–P4 gaps

**Automated portion proven; human R5 intentionally pending.**

- P0: SAGE 0.9 separates machine-green state from human R5 and merge authorization, removes
  duplicate CI execution, and derives runtime paths portably.
- P1: Promotion resume is commit-locked and fail-closed; one ledger enforces turns, token/USD
  reservations, and time; language gates are argv-only plugins.
- P2: canonical evidence manifests are SSH-signed and verified against a committed allowlist;
  Promotion publishes an independent `SAGE Evidence` GitHub status.
- P3: 12 pinned public repositories across 12 primary languages passed benchmark-validity checks
  without executing external code. Ten passed strict scans; nine redacted findings across the two
  remaining upstream fixtures remain visible.
- P4: the original Canvas sprite audit game supplies a small review UI and deterministic test
  target without adding a second orchestration control plane.

## Objective 5 — choose and install required GitHub/software tooling

**Proven.** The required tools were installed and version-checked. PowerShell was added specifically
to validate SAGE's Windows scripts on macOS. Claude Squad was installed but kept optional after its
interactive TUI characteristics were evaluated. Vibe Kanban and Spec Kit were deliberately not
installed because they would duplicate the tested headless evidence/control layers.

## Final verification evidence

- `python3 -m unittest discover -s tests -p 'test_*.py'`: 44/44 passed, including budget boundaries,
  immutable gate configuration/candidate patches, plugin validation, signed-evidence tamper
  rejection, Promotion resume, and task-config safety.
- `python3 tools/audit_sprite_game.py`: 8/8 audit groups passed; six public and five hidden game
  tests passed.
- `python3 tools/benchmark_real_repos.py`: 12/12 pinned repositories and 12/12 languages passed
  benchmark validity; 10/12 passed every strict scan.
- `just verify-fixture`: fixture discrimination passed.
- `ruff check .` and `ruff format --check .`: passed.
- root, fixture, game, and hidden-test Biome checks: passed.
- the latest PR2 repository attestation ran redacted Gitleaks over the complete local candidate
  tree with no findings; pinned third-party clones are handled by the separate real-repository
  report rather than silently allowlisted as strict passes.
- root `actionlint`: passed.
- SAGE pilot: Bash 37/37, PowerShell 22/22, ShellCheck, actionlint, installer round-trip, all
  allowlists/hashes, Gitleaks, and final gate passed.
- SAGE reviewer found one blocking CI false-green defect; correction was applied and reverified.
- PR2 consolidation: patch SHA-256 and source ancestry were verified and 18 local acceptance
  commands replayed before the final documentation correction. PR2 combines the retained pilot
  history, unattended orchestration, portable CLI, and cross-platform CI.
- GitHub CI on the last published PR2 head: five check runs passed — `test`, Bash on Ubuntu,
  Bash on macOS, PowerShell on Windows, and ShellCheck. The separate signed `SAGE Evidence`
  status is green; PR2 remains `isDraft=true` with `autoMergeRequest=null`.

## Remaining human-owned action

The verified integration candidate is [SAGE draft PR2](https://github.com/eason-tien/sage/pull/2).
The earlier pilot PR is closed and superseded. The workflow deliberately cannot mark PR2 ready or
merge it. Human review, a personally executed SAGE R5 verify, ready-for-review, and merge remain
outstanding human-owned actions.
