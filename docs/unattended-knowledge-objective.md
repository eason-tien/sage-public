# Unattended Knowledge and Versioning Objective

## Required behavior

1. Keep durable task state and distilled knowledge in an Obsidian-compatible vault.
2. Before every task, prove required CLI capability and relevant knowledge readiness; update the
   vault before dispatch.
3. Give Agy, Codex, and Claude one identical, immutable knowledge briefing.
4. Initialize or synchronize CodeGraph before dispatch and during mechanical gates.
5. Record every task. Successful project updates must advance semantic version and update
   `Ver.md`; failures must be remembered without advancing version.
6. Include immutable knowledge and version snapshots in signed SAGE Evidence.
7. Require Google Stitch before Web UI, website UI, desktop visual UI, or WPF/XAML design; lock the
   exported design artifact before Agent dispatch. Support Google Ultra web login, Stitch API-key,
   and OAuth paths without exposing credentials in diagnostic output.

## Acceptance

- Capability or knowledge gaps stop before any Agent invocation.
- CodeGraph missing, stale, or failed stops the workflow.
- Editing `SAGE_KNOWLEDGE.md`, `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` fails the contract gate.
- Concurrent tasks cannot silently reuse the same planned version.
- Signed evidence verification fails after any knowledge snapshot is changed.
- A detected UI/WPF design task without `STITCH_DESIGN.md` fails before the first Agent invocation;
  missing authentication is reported when the artifact still needs to be generated.
