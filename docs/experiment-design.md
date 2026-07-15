# Experiment Design

## Question

For mixed Python and Node.js maintenance work, which orchestration of Codex CLI,
Antigravity CLI, and Claude Code gives the best verified result per unit of time and
model effort?

## Candidate workflows

1. **Solo baselines**: each CLI implements the same task alone.
2. **Sequential review**: one CLI implements, a different CLI performs a read-only
   adversarial review, and the implementer applies actionable findings.
3. **Contract-first tri-model**: two CLIs independently plan and identify risks;
   the implementer receives only their written plans, implements the task, then a
   different CLI audits the diff before the final correction pass.

The winning workflow must beat the solo baseline on hidden acceptance and integrity.
If two flows are equally correct, prefer the one with fewer model turns and lower wall
time. A slower flow may win only when it finds materially more defects or provides
stronger evidence.

## Metrics

- Public acceptance pass/fail.
- Hidden acceptance pass/fail.
- Contract integrity: task and tests remain unchanged.
- Secret scan pass/fail.
- Wall-clock time and CLI exit status per stage.
- Files and lines changed.
- Review findings: actionable, false positive, or missed by hidden tests.
- Reproducibility across a second fresh run of the winning flow.

## Safety boundaries

- Benchmark workspaces contain only the public fixture.
- Hidden tests stay outside the agent workspace and run only after the agent exits.
- Network-capable agents run with their normal authenticated service, while generated
  shell commands remain sandboxed or approval-gated.
- No push, pull request, or modification of the user's production repositories occurs
  during workflow selection.

