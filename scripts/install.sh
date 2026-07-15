#!/usr/bin/env bash
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

usage() {
  echo "usage: $0 [--prefix DIR] [--uninstall]"
}

prefix="${HOME:+$HOME/.local}"
uninstall=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      if [[ $# -lt 2 ]]; then
        echo "--prefix requires a directory" >&2
        usage >&2
        exit 1
      fi
      prefix="$2"
      shift 2
      ;;
    --uninstall)
      uninstall=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$prefix" ]]; then
  echo "--prefix must not be empty (and HOME must be set when it is omitted)" >&2
  exit 1
fi

script_path="$(resolve_path "${BASH_SOURCE[0]}")"
repo_root="$(cd "$(dirname "$script_path")/.." && pwd -P)"
dispatcher="$(resolve_path "$repo_root/sage")"
bin_dir="$prefix/bin"
link="$bin_dir/sage"

is_owned_link() {
  local target
  [[ -L "$link" ]] || return 1
  target="$(resolve_path "$link" 2>/dev/null)" || return 1
  [[ "$target" == "$dispatcher" ]]
}

if [[ $uninstall -eq 1 ]]; then
  if [[ ! -e "$link" && ! -L "$link" ]]; then
    echo "sage is not installed at $link"
    exit 0
  fi
  if ! is_owned_link; then
    echo "refusing to remove unrelated target: $link" >&2
    exit 1
  fi
  rm -- "$link"
  echo "removed $link"
  exit 0
fi

mkdir -p "$bin_dir"
if [[ -e "$link" || -L "$link" ]]; then
  if is_owned_link; then
    echo "sage is already installed at $link"
    exit 0
  fi
  echo "refusing to overwrite unrelated target: $link" >&2
  exit 1
fi

ln -s "$dispatcher" "$link"
echo "installed $link -> $dispatcher"
