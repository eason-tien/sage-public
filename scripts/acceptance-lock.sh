#!/usr/bin/env bash
# acceptance-lock.sh -- lock / relock / check the acceptance set so a weakened acceptance.txt
# cannot SILENTLY pass verify (R9). Tamper-EVIDENT (git-tracked lock), not tamper-proof.
# Usage:
#   ./acceptance-lock.sh lock   [acceptance.txt]   # create lock; REFUSES if a lock already exists
#   ./acceptance-lock.sh relock [acceptance.txt]   # explicitly replace an existing lock (deliberate)
#   ./acceptance-lock.sh check  [acceptance.txt]   # exit 0 if unchanged; exit 1 if changed / no lock
# ASCII-only on purpose.
set -uo pipefail
export LC_ALL=C
action="${1:-}"
accept="${2:-acceptance.txt}"

if [[ ! -f "$accept" ]]; then echo "acceptance file not found: $accept"; exit 1; fi
lock="$accept.lock"
# Canonically convert CRLF pairs to LF while preserving every lone CR byte as
# semantic content. Use a byte-level transform: line-oriented sed also removes a
# lone CR at EOF and therefore disagrees with the PowerShell implementation.
normalize_acceptance() {
  python3 -c 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().replace(b"\r\n", b"\n"))'
}
# sha256sum (GNU) with shasum fallback (macOS ships shasum, not sha256sum)
if command -v sha256sum >/dev/null 2>&1; then
  if hash="$(normalize_acceptance < "$accept" | sha256sum | awk '{print $1}')"; then :; else
    echo "sha256 pipeline failed for: $accept" >&2
    exit 1
  fi
elif command -v shasum >/dev/null 2>&1; then
  if hash="$(normalize_acceptance < "$accept" | shasum -a 256 | awk '{print $1}')"; then :; else
    echo "sha256 pipeline failed for: $accept" >&2
    exit 1
  fi
else
  echo "cannot compute sha256: neither sha256sum nor shasum found in PATH" >&2
  exit 1
fi
# fail-closed guard: never write/compare an empty or malformed hash (a broken tool must not fake a lock)
if [[ ! "$hash" =~ ^[0-9a-f]{64}$ ]]; then
  echo "sha256 computation failed for: $accept" >&2
  exit 1
fi

write_lock() {
  local timestamp
  if ! timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    || [[ ! "$timestamp" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
    echo "cannot create UTC lock timestamp" >&2
    return 1
  fi
  if ! printf '%s  %s  %s\n' "$hash" "$timestamp" "$accept" > "$lock"; then
    echo "cannot write lock file: $lock" >&2
    return 1
  fi
  echo "locked: $accept"
  echo "  sha256: $hash"
  echo "  -> commit $lock so the lock is tracked in git (tamper-evident)."
}

case "$action" in
  lock)
    if [[ -e "$lock" || -L "$lock" ]]; then
      echo "lock already exists: $lock"
      echo "  changing the acceptance set needs explicit human intent ->"
      echo "  use: acceptance-lock.sh relock $accept"
      exit 1
    fi
    write_lock || exit 1 ;;
  relock)
    write_lock || exit 1
    echo "  (relock: existing lock deliberately replaced)" ;;
  check)
    if [[ ! -f "$lock" ]]; then echo "no lock file: $lock  (run: acceptance-lock.sh lock $accept)"; exit 1; fi
    locked="$(awk 'NR==1{print $1}' "$lock")"
    if [[ "$hash" == "$locked" ]]; then echo "OK: acceptance unchanged (${hash:0:12}...)"; exit 0; fi
    echo "TAMPERED: acceptance changed since lock."
    echo "  locked : $locked"
    echo "  current: $hash"
    exit 1
    ;;
  *)
    echo "usage: acceptance-lock.sh {lock|relock|check} [acceptance.txt]"; exit 1 ;;
esac
