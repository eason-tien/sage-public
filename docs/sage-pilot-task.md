# SAGE cross-platform CLI and Agy migration

## Goal

Make the existing SAGE command and crosscheck workflow work safely on macOS/Linux,
while preserving Windows behavior and adding automated cross-platform evidence.

## Required changes

1. Add an executable Bash dispatcher named `sage` at repository root. It must resolve
   its own real repository location even when invoked through a symlink, and expose the
   same commands as `sage.ps1`: `new`, `lock`, `relock`, `check`, `verify`, `crosscheck`,
   `preflight`, `test`, `rules`, and help/default. Paths containing spaces must work.
2. Add executable `scripts/install.sh` with `--prefix DIR` (default `$HOME/.local`) and
   `--uninstall`. Installation creates only `<prefix>/bin/sage` as a symlink to the
   repository dispatcher, is idempotent, never requires sudo, and refuses to overwrite
   an unrelated existing file or symlink. Uninstall removes only the symlink owned by
   this repository and is idempotent.
3. Update README installation instructions for Windows and macOS/Linux, including the
   PATH requirement for `<prefix>/bin`.
4. Update both `scripts/crosscheck.sh` and `scripts/crosscheck.ps1` to prefer `agy` as the
   Google reviewer, using its real non-interactive syntax (`agy --print <prompt>` in
   plan/sandbox mode). Retain legacy `gemini` only as a fallback when `agy` is absent.
   A single run must never invoke both Agy and legacy Gemini. Existing Claude, Codex, and
   Grok behavior remains available.
5. Update Bash and PowerShell selftests with stub CLIs to prove the Agy adapter and output
   file work without making real model requests. Bash selftest must also cover dispatcher
   help plus install, idempotent reinstall, safe refusal to overwrite an unrelated target,
   uninstall, and idempotent uninstall.
6. Update preflight output to detect `agy` as the current Google CLI and identify legacy
   `gemini` separately when present.
7. Add `.github/workflows/ci.yml` that runs Bash selftests on Ubuntu and macOS, PowerShell
   selftests on Windows, and ShellCheck/actionlint where appropriate.
8. Make existing Bash scripts ShellCheck-clean. Do not weaken ShellCheck severity or add
   blanket exclusions to hide findings.

## Constraints

- Preserve R1–R9, especially fail-closed acceptance locking and human-owned final verify.
- No network access or real AI model call from selftests.
- No system-wide install, sudo, shell profile modification, or automatic push/commit.
- Maximum workflow stages: 4. Each model stage has a 900-second hard timeout and logs
  prompt, output, timing, and diff as audit evidence.
- New files are limited to `sage`, `scripts/install.sh`, and `.github/workflows/ci.yml`.
- Existing selftest files may change only to cover these new behaviors.

## Mechanical acceptance

The workflow runner will execute these commands independently:

```bash
bash scripts/selftest.sh
pwsh -NoProfile -File scripts/selftest.ps1
shellcheck sage scripts/*.sh
actionlint
bash sage help | grep -F 'sage <command>'
tmp="$(mktemp -d)"; bash scripts/install.sh --prefix "$tmp"; "$tmp/bin/sage" help | grep -F 'sage <command>'; bash scripts/install.sh --prefix "$tmp" --uninstall; test ! -e "$tmp/bin/sage"
```
