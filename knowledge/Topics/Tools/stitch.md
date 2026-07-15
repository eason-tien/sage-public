---
tool: Google Stitch
last_verified: 2026-07-13
status: mcp-configured-tools-unavailable
---
# Google Stitch

- Mandatory before Web UI, website UI, desktop visual UI, or WPF/XAML design implementation.
- Official design surface: https://stitch.withgoogle.com/
- Official MCP endpoint: `https://stitch.googleapis.com/mcp`
- Interactive design can use the signed-in Google Ultra member account in the Stitch web UI.
- Official SDK: `@google/stitch-sdk`; authentication uses `STITCH_API_KEY` or OAuth with
  `STITCH_ACCESS_TOKEN` and `GOOGLE_CLOUD_PROJECT`.
- Local observation: Claude has a Stitch MCP entry and authenticates, but tool discovery currently
  fails on the `ScreenInstance` JSON Schema; Codex has no Stitch MCP entry. Treat this as
  authenticated-but-unavailable, not as a missing key.
- Automated health checks may use only redacted list/status commands. Do not run MCP detail/get
  commands in captured logs because they may print configured headers. Rotate any exposed key.
- Export a Stitch `DESIGN.md` artifact before coding. For WPF, translate the approved desktop
  design system and screen layout into XAML; do not treat generated HTML as WPF implementation.
- If Stitch authentication or the exported design artifact is missing, stop before Agent dispatch
  and request login/authentication from the user.
