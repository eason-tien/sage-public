#!/usr/bin/env bash
# verify.sh — 跑驗收命令並留下真實證據（最終驗收 Gate 3 用）
# 用法：./verify.sh
# 作用：執行你在 acceptance.txt 定義的驗收命令，逐條記錄真實輸出與退出碼。
# 核心：這是「你親自跑、看真綠」的工具，不信 AI 自報的綠。
# 不用 set -e：本腳本要逐條跑可能失敗的驗收命令並統計 pass/fail，遇錯需繼續而非中斷。
set -uo pipefail

# 驗收命令可能 cd 到別處（或改動 shell 變數/trap）；證據日誌路徑須固定在「呼叫本腳本
# 當下的目錄」，故先鎖存呼叫端絕對路徑，不受後續命令影響。
INVOKE_DIR="$(pwd)"

ACCEPT_FILE="acceptance.txt"; ALLOW_UNLOCKED=0
for a in "$@"; do
  case "$a" in
    --allow-unlocked) ALLOW_UNLOCKED=1 ;;
    *) ACCEPT_FILE="$a" ;;
  esac
done
# 跳過 R9 只認命令列顯式旗標（R5：人親自敲），不設環境變數通道。
# LOG 用絕對路徑：驗收行在子行程裡 cd 也不會讓證據日誌散落到別的目錄。
LOG="$INVOKE_DIR/verify-$(date +%Y%m%d-%H%M%S).log"

if [[ ! -f "$ACCEPT_FILE" ]]; then
  cat <<'EOF'
找不到驗收命令清單。請建立 acceptance.txt，一行一條可執行的驗收命令，例如：

  pytest tests/ -q
  python3 -m coverage report --fail-under=95
  test -z "$(git diff --name-only | grep '^schema/')"
  cd frontend && npm test --silent

每條命令的退出碼 0 = 通過，非 0 = 不通過。
每行在獨立子 shell 執行、行間互不影響：cd/變數不跨行，需要的話寫在同一行用 && 串。
EOF
  exit 1
fi

RAW_ACCEPT="$(mktemp "${TMPDIR:-/tmp}/sage-acceptance-raw.XXXXXX")" || exit 2
NORMALIZED_ACCEPT="$(mktemp "${TMPDIR:-/tmp}/sage-acceptance.XXXXXX")" || {
  rm -f -- "$RAW_ACCEPT"
  exit 2
}
# shellcheck disable=SC2317,SC2329 # invoked indirectly by EXIT trap
cleanup_acceptance_snapshots() {
  rm -f -- "$RAW_ACCEPT" "$RAW_ACCEPT.lock" "$NORMALIZED_ACCEPT"
}
trap cleanup_acceptance_snapshots EXIT
if ! cp -- "$ACCEPT_FILE" "$RAW_ACCEPT"; then
  echo "cannot snapshot acceptance file: $ACCEPT_FILE" >&2
  exit 2
fi

echo "═══ 最終驗收（真實執行，留證據）═══" | tee "$LOG"
echo "時間：$(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# 防篡改閘：驗收集若被改動則拒絕認證綠（acceptance set tamper-check, R9）
# 委派給 acceptance-lock.sh check，雜湊邏輯只存一處（DRY，含 CRLF 歸一化）
LOCK_FILE="$ACCEPT_FILE.lock"
if [[ -f "$LOCK_FILE" ]]; then
  if ! cp -- "$LOCK_FILE" "$RAW_ACCEPT.lock"; then
    echo "✗ 驗收鎖無法建立不可變 snapshot；未執行任何驗收命令。" | tee -a "$LOG"
    exit 2
  fi
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  lock_out="$(bash "$HERE/acceptance-lock.sh" check "$RAW_ACCEPT" 2>&1)"; lock_rc=$?
  if [[ $lock_rc -ne 0 ]]; then
    printf '%s\n' "$lock_out" | tee -a "$LOG"
    # 區分「驗收集被改」與「校驗本身跑不起來」兩種原因，都 fail-closed exit 2（R9）
    if printf '%s\n' "$lock_out" | grep -q '^TAMPERED'; then
      echo "✗ 驗收集已被改動（ACCEPTANCE TAMPERED）——拒絕認證綠，未執行任何驗收命令。" | tee -a "$LOG"
      echo "  → 有意改驗收請顯式 relock（git 留痕），否則視為假綠攻擊。" | tee -a "$LOG"
    else
      echo "✗ 鎖校驗無法完成（acceptance-lock check 失敗，非 TAMPERED）——fail-closed，拒絕認證。" | tee -a "$LOG"
      echo "  → 上面是 acceptance-lock 的原始輸出；先讓 check 能跑通再 verify。" | tee -a "$LOG"
    fi
    exit 2
  fi
  echo "驗收集未變（acceptance-lock check ✓）" | tee -a "$LOG"
elif [[ $ALLOW_UNLOCKED -eq 1 ]]; then
  echo "（無 ${LOCK_FILE}：以 --allow-unlocked 顯式跳過 R9 防篡改——僅供臨時/throwaway。）" | tee -a "$LOG"
else
  echo "✗ 無 ${LOCK_FILE}：R9 要求驗收集先鎖定（fail-closed）。先跑 acceptance-lock.sh lock ${ACCEPT_FILE}，" | tee -a "$LOG"
  echo "  或明確加 --allow-unlocked 跳過（不建議：等於 fail-open）。未認證，未執行任何驗收命令。" | tee -a "$LOG"
  exit 2
fi
echo "" | tee -a "$LOG"

pass=0; fail=0; n=0
if ! python3 -c 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().replace(b"\r\n", b"\n"))' \
  < "$RAW_ACCEPT" > "$NORMALIZED_ACCEPT"; then
  echo "✗ CRLF 歸一化失敗；未執行驗收命令。" | tee -a "$LOG"
  exit 2
fi
# 只把 CRLF pair 歸一成 LF；embedded/EOF lone CR 保持可執行語義，並與 lock hash 完全一致。
# || [[ -n "$cmd" ]]：檔案最後一行沒有換行符時也要執行（否則最後一條驗收被靜默跳過）
while IFS= read -r cmd || [[ -n "$cmd" ]]; do
  # 略過空白行與註解行（容忍前導空白/Tab 的縮排註解）
  [[ -z "${cmd//[[:space:]]/}" || "$cmd" =~ ^[[:space:]]*# ]] && continue
  n=$((n+1))
  echo "──────────────────────────────────────" | tee -a "$LOG"
  echo "[$n] \$ $cmd" | tee -a "$LOG"
  # 每行在獨立子 bash 執行（bash -o pipefail -c）：
  # - 行間完全獨立（R1 每條=1命令+退出碼）：exit/cd/變數賦值只影響該子行程，不會終結
  #   verify 本身、不會洗掉計數器；跨行狀態（cd 到某目錄再驗）請寫在同一行用 && 串。
  # - pipefail 刻意保留：管線中段失敗（如 pytest | tee log）必須紅——fail-closed 優先，
  #   寧可 SIGPIPE 場景偶發誤紅，不可中段失敗翻綠。-e/-u 不繼承（貼近人手跑語義）。
  # - </dev/null 隔離 stdin，避免會讀 stdin 的命令(如裸 cat/read)吞掉 acceptance.txt 後續行。
  if bash -o pipefail -c "$cmd" >>"$LOG" 2>&1 </dev/null; then
    echo "    → 退出碼 0 ✓ 通過" | tee -a "$LOG"
    pass=$((pass+1))
  else
    code=$?
    echo "    → 退出碼 $code ✗ 不通過" | tee -a "$LOG"
    fail=$((fail+1))
  fi
done < "$NORMALIZED_ACCEPT"

echo "" | tee -a "$LOG"
echo "═══ 驗收結果：$pass 通過 / $fail 不通過（共 $n 條）═══" | tee -a "$LOG"
echo "完整證據：$LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"
if [[ $n -eq 0 ]]; then
  echo "✗ 0 條驗收命令——空驗收集不可認證（R1 要求至少一條可機械判定）。填好 $ACCEPT_FILE 再來。" | tee -a "$LOG"
  exit 2
fi
if [[ $fail -eq 0 ]]; then
  echo "✓ 全綠（且是你親跑的真綠）。可考慮合入 main。" | tee -a "$LOG"
  echo "  30 秒檢討（可選）：sage retro <任務名>——落到 sage 倉 retro/，供週迭代彙整。" | tee -a "$LOG"
  exit 0
else
  echo "✗ 有未通過項。git 回滾，修條件或 Plan，重來。不要合入。" | tee -a "$LOG"
  exit 1
fi
