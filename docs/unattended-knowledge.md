# Unattended Knowledge Architecture

## Boundary

The Obsidian vault is durable shared knowledge, but it is not a multi-writer scratchpad. The
orchestrator is the only writer. Agy, Codex, and Claude receive one identical immutable briefing,
which prevents races, prompt-specific memory drift, and an Agent rewriting policy for later stages.

## Lifecycle

`preflight → knowledge retrieval/update → isolated clone → CodeGraph init → shared briefing → Agent stages → CodeGraph/gates → memory distillation → Ver.md → signed evidence`

### Preflight

- Verify every CLI required by the selected route.
- Verify Git, Gitleaks, CodeGraph, Obsidian, and the SSH signing-key pair.
- Detect tracked languages and refresh their vault notes.
- Read bounded project memory and calculate the next semantic patch version.
- Stop before dispatch on any missing capability or unknown knowledge domain.
- Detect Web UI and WPF/XAML visual-design work. Such tasks require a Stitch-exported `DESIGN.md`;
  the export is locked as `STITCH_DESIGN.md` before coding. A signed-in Google Ultra web session,
  a Stitch API key, or OAuth can create/fetch the design; MCP health checks never read or print
  configured headers. Authentication is requested when none of those paths is usable.

### Shared execution context

- `WORKFLOW_TASK.md` is the locked task contract.
- `SAGE_KNOWLEDGE.md` is the locked memory snapshot.
- `.codegraph/codegraph.db` is local and ignored by Git.
- Agent policy files and gate configuration are protected by hashes.
- Stitch design evidence is protected by hash and cannot be changed by an implementation Agent.

### Post-task distillation

- Every attempt receives a Task note.
- Stable outcomes and failing checks are distilled into project `Memory.md`.
- Successful updates advance `Ver.md`; failed attempts keep the previous version.
- Concurrent tasks that preflight against the same version cannot both finalize successfully.
- Pre-commit checks staged project updates; CI independently checks the committed HEAD and rejects
  missing or incomplete Memory, State, Task note, and version records.
- Run-local knowledge snapshots are immutable evidence artifacts; changing one breaks signature
  verification.

## Obsidian layout

```text
knowledge/
├── Home.md
├── System/Memory Policy.md
├── Topics/Languages/*.md
├── Projects/<project>/Memory.md
├── Projects/<project>/State.json
├── Projects/<project>/Ver.md
└── Tasks/<project>/<task-id>.md
```

Open the `knowledge/` directory as an Obsidian vault. Obsidian does not need to be running for the
workflow because the durable format is ordinary Markdown, JSON state, and wikilinks.
