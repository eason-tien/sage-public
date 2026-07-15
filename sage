#!/usr/bin/env bash
# SAGE = Spec . Acceptance . Gate . Evidence
set -euo pipefail

resolve_path() {
  local source="$1" dir
  while [[ -L "$source" ]]; do
    dir="$(cd -P "$(dirname "$source")" >/dev/null 2>&1 && pwd)" || return 1
    source="$(readlink "$source")" || return 1
    [[ "$source" == /* ]] || source="$dir/$source"
  done
  dir="$(cd -P "$(dirname "$source")" >/dev/null 2>&1 && pwd)" || return 1
  printf '%s/%s\n' "$dir" "$(basename "$source")"
}

SAGE_PATH="$(resolve_path "${BASH_SOURCE[0]}")"
SAGE_ROOT="$(dirname "$SAGE_PATH")"
SAGE_SCRIPTS="$SAGE_ROOT/scripts"

show_help() {
  cat <<'EOF'
sage <command>  --  SAGE = Spec . Acceptance . Gate . Evidence
  new <name>              new task: dir + git init + templates + acceptance.txt
  lock  [acceptance.txt]  lock the acceptance set (R9; refuses if already locked)
  relock [acceptance.txt] deliberately replace an existing lock
  check [acceptance.txt]  is the acceptance set unchanged?
  verify [acceptance.txt] run acceptance, see the REAL green (you run it)
  crosscheck <file> <out> multi-CLI back-to-back review
  retro <name> [dir]      30-sec retro note -> retro/ (reminder, not a gate)
  preflight               environment precheck
  test                    selftest
  version                 print the installed SAGE CLI version
  rules                   print SAGE_RULES.md (R1-R9 / dosage / gates)
EOF
}

command_name="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$command_name" in
  new)        exec bash "$SAGE_SCRIPTS/new-task.sh" "$@" ;;
  lock)       exec bash "$SAGE_SCRIPTS/acceptance-lock.sh" lock "$@" ;;
  relock)     exec bash "$SAGE_SCRIPTS/acceptance-lock.sh" relock "$@" ;;
  check)      exec bash "$SAGE_SCRIPTS/acceptance-lock.sh" check "$@" ;;
  verify)     exec bash "$SAGE_SCRIPTS/verify.sh" "$@" ;;
  crosscheck) exec bash "$SAGE_SCRIPTS/crosscheck.sh" "$@" ;;
  retro)      exec bash "$SAGE_SCRIPTS/retro.sh" "$@" ;;
  preflight)  exec bash "$SAGE_SCRIPTS/preflight.sh" "$@" ;;
  test)       exec bash "$SAGE_SCRIPTS/selftest.sh" "$@" ;;
  version)    cat "$SAGE_ROOT/VERSION" ;;
  rules)      cat "$SAGE_ROOT/SAGE_RULES.md" ;;
  *)          show_help ;;
esac
