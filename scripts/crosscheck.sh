#!/usr/bin/env bash
# crosscheck.sh — 把同一份內容發給多個 CLI 做隔離式獨立審查
# 用法：./crosscheck.sh <待審文件> [輸出目錄]
# 關鍵：各 CLI 使用獨立 cwd，全部結束前不發布任何 review，降低互相錨定。
# 這是流程層隔離，不宣稱能防禦主動掃描整台主機的惡意 CLI。
# 注意：這是「模板」——各 CLI 呼叫語法因版本而異，首次用請先校準下方 run_reviewer 函數。
set -euo pipefail

REVIEW_FILE="${1:-}"
OUT_DIR="${2:-./crosscheck-$(date +%Y%m%d-%H%M%S)}"
MIN_SUCCESS="${SAGE_MIN_REVIEWERS:-2}"
SOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPT_FILE="$SOP_DIR/prompts/04-review-crosscheck.md"

if [[ -z "$REVIEW_FILE" || ! -f "$REVIEW_FILE" ]]; then
  echo "用法：$0 <待審文件(規格+Plan+契約)> [輸出目錄]"
  exit 1
fi
if [[ ! "$MIN_SUCCESS" =~ ^[0-9]+$ || "$MIN_SUCCESS" -lt 2 ]]; then
  echo "SAGE_MIN_REVIEWERS 必須是 >= 2 的整數（目前：${MIN_SUCCESS}）" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
TEMP_DIRS=()
# shellcheck disable=SC2317,SC2329 # invoked indirectly by EXIT trap
cleanup_review_dirs() {
  local directory
  for directory in "${TEMP_DIRS[@]}"; do rm -rf -- "$directory"; done
}
trap cleanup_review_dirs EXIT

# Reusing an output directory must not mix reviewers from an earlier run. Remove
# only artifacts managed by this script; preserve unrelated user files.
rm -f -- \
  "$OUT_DIR"/review-*.md \
  "$OUT_DIR"/review-*.md.err \
  "$OUT_DIR"/failed-*.out \
  "$OUT_DIR"/failed-*.err \
  "$OUT_DIR/status.tsv" \
  "$OUT_DIR/_input.md"

# 組合「審查提示詞 + 待審內容」成一份完整輸入
PROMPT_TEXT="$(cat "$PROMPT_FILE"; printf '\n\n---\n## 待審內容\n\n'; cat "$REVIEW_FILE")"

echo "→ 待審輸入已在記憶體組合；完成前不發布中間 review"
echo "→ 開始隔離式審查（獨立 cwd、延後集中發布）..."
echo ""

# ───────────────────────────────────────────────
# 定義各 CLI 的「非互動」呼叫方式（讀 prompt → 出文字到 stdout）。
# 依你本機安裝/版本調整這個函數即可；新增 CLI 在 case 加一支並寫進 REVIEWERS。
# 安全：prompt 以單一 argv 參數傳入，不經 eval/shell 二次解析，
#       待審內容含 $ ` " ' 等字元都當純文字，無命令注入面，路徑含空格也安全。
# ───────────────────────────────────────────────
run_reviewer() {
  local label="$1" prompt="$PROMPT_TEXT"
  # 下列呼叫語法已於本機實測可用（均非互動、退出碼 0）。
  # </dev/null：給空 stdin，避免 CLI 等待互動輸入而卡住（prompt 已由 argv 傳入）。
  case "$label" in
    claude) claude -p "$prompt" </dev/null ;;
    codex)  codex exec --skip-git-repo-check "$prompt" </dev/null ;;  # 非 git 目錄也能跑
    agy)    agy --print "$prompt" </dev/null ;;
    gemini) gemini -p "$prompt" </dev/null ;;
    grok)   grok -p "$prompt" </dev/null ;;    # -p=--single 非互動（裸 grok 會開 TUI）
    *)      echo "run_reviewer：未定義的 reviewer '$label'，請在 case 補上" >&2; return 127 ;;
  esac
}
# 待審內容很大時（接近 ARG_MAX），改用 CLI 的 --prompt-file/stdin 形式。

REVIEWERS=(claude codex)
if command -v agy >/dev/null 2>&1; then
  REVIEWERS+=(agy)
elif command -v gemini >/dev/null 2>&1; then
  REVIEWERS+=(gemini)
fi
REVIEWERS+=(grok)

STATUS_FILE="$OUT_DIR/status.tsv"
status_rows=$'reviewer\tstatus\texit_code\tdetail\n'
success_count=0
for label in "${REVIEWERS[@]}"; do
  review_dir="$(mktemp -d "${TMPDIR:-/tmp}/sage-review-${label}.XXXXXX")"
  TEMP_DIRS+=("$review_dir")
  chmod 700 "$review_dir"
  out="$review_dir/review-$label.md"
  failed_out="$review_dir/failed-$label.out"
  failed_err="$review_dir/failed-$label.err"
  echo "  ▶ $label"
  if command -v "$label" >/dev/null 2>&1; then
    # 真實執行；單家失敗不中斷其他審查者
    rc=0
    if (cd "$review_dir" && run_reviewer "$label") > "$failed_out" 2>"$failed_err"; then
      rc=0
    else
      rc=$?
    fi
    if [[ $rc -eq 0 && -s "$failed_err" ]]; then
      rc=1
    fi
    if [[ $rc -eq 0 ]] && grep -q '[^[:space:]]' "$failed_out"; then
      mv -- "$failed_out" "$out"
      [[ -s "$failed_err" ]] || rm -f -- "$failed_err"
      success_count=$((success_count + 1))
      status_rows+="$(printf '%s\tsuccess\t0\tnonempty output' "$label")"$'\n'
      echo "    ✓ 完成（暫存；尚未發布）"
    else
      if [[ $rc -eq 0 ]]; then
        printf '%s\n' "reviewer returned empty output" >> "$failed_err"
        detail="empty output"
      else
        detail="execution failed"
      fi
      status_rows+="$(printf '%s\tfailed\t%s\t%s' "$label" "$rc" "$detail")"$'\n'
      echo "    ✗ ${detail}（診斷將在全部 reviewer 結束後發布）"
    fi
  else
    echo "    ⊘ 未安裝 '$label'，跳過。可在 run_reviewer 函數調整。"
    printf '%s\n' "reviewer command not installed: $label" > "$failed_err"
    : > "$failed_out"
    status_rows+="$(printf '%s\tmissing\t127\tcommand not installed' "$label")"$'\n'
  fi
done

# Only now make the prompt and each review/diagnostic visible in the requested
# output directory. Later reviewers never run with earlier output in their cwd.
printf '%s\n' "$PROMPT_TEXT" > "$OUT_DIR/_input.md"
printf '%s' "$status_rows" > "$STATUS_FILE"
for review_dir in "${TEMP_DIRS[@]}"; do
  for artifact in "$review_dir"/review-*.md "$review_dir"/failed-*.out "$review_dir"/failed-*.err; do
    [[ -e "$artifact" ]] && cp -- "$artifact" "$OUT_DIR/"
  done
done

echo ""
if [[ $success_count -lt $MIN_SUCCESS ]]; then
  echo "✗ 獨立審查 quorum 未達：${success_count} / ${MIN_SUCCESS}；拒絕繼續。" >&2
  echo "狀態：$STATUS_FILE" >&2
  exit 1
fi
echo "✓ 獨立審查 quorum：$success_count / $MIN_SUCCESS"
echo "✓ 成功結果：$OUT_DIR/review-*.md；狀態：$STATUS_FILE"
echo ""
echo "下一步（人工，不交給 AI 裁決）："
echo "  1. 並排看各家意見"
echo "  2. 標出『一致認同』vs『有分歧』的點"
echo "  3. 分歧點列各方理由，由你拍板"
echo "  4. （若由某個 Claude 匯總）要求它原樣列意見、標分歧、提建議但不裁決，"
echo "     尤其對涉及它自己初版的批評要原樣呈現"
exit 0
