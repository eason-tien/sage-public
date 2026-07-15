# SAGE Memory Policy

- The orchestrator is the only writer.
- Agents receive the same immutable `SAGE_KNOWLEDGE.md` snapshot.
- Preflight must pass before dispatch.
- Failed tasks are remembered but do not advance project version.
- Successful code changes require a CodeGraph refresh and `Ver.md` entry.
- Web UI, website UI, desktop visual UI, and WPF/XAML design require Stitch and a locked
  `STITCH_DESIGN.md` before Agent dispatch.
