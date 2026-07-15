#!/usr/bin/env bash
# preflight.sh — 進 /goal 前的環境前置檢查
# 用法：./preflight.sh
# 作用：確認環境就緒，避免 /goal 前幾輪全耗在「為什麼跑不起來」
# 不用 set -e：本腳本要逐條跑檢查命令並統計 ok/warn，個別失敗需繼續而非中斷。
set -uo pipefail

echo "═══ 環境前置檢查 ═══"
echo ""

ok=0; warn=0

check() {  # check "描述" "命令"
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  ✓ $desc"
    ok=$((ok+1))
  else
    echo "  ✗ $desc —— 未就緒"
    warn=$((warn+1))
  fi
}

echo "[1] 版本控制"
check "git 可用" git --version
check "在 git 倉庫內（有回滾基線）" git rev-parse --git-dir

echo ""
echo "[2] AI CLI（按你安裝的調整）"
for cli in claude codex; do
  if command -v "$cli" >/dev/null 2>&1; then
    echo "  ✓ $cli 已安裝"
  else
    echo "  ⊘ $cli 未安裝（如不需要可忽略）"
  fi
done
if command -v agy >/dev/null 2>&1; then
  echo "  ✓ agy 已安裝（目前 Google CLI）"
else
  echo "  ⊘ agy 未安裝（目前 Google CLI；如不需要可忽略）"
fi
if command -v gemini >/dev/null 2>&1; then
  echo "  ✓ gemini 已安裝（legacy Google CLI fallback）"
else
  echo "  ⊘ gemini 未安裝（legacy Google CLI fallback；如不需要可忽略）"
fi
if command -v grok >/dev/null 2>&1; then
  echo "  ✓ grok 已安裝"
else
  echo "  ⊘ grok 未安裝（如不需要可忽略）"
fi

echo ""
echo "[3] 執行環境（按項目語言調整）"
# 可選工具只提示不計 warn：非 Python 項目缺 pytest 不該把 preflight 打紅（工具擋假綠，不擋人）
if command -v python3 >/dev/null 2>&1; then
  echo "  ✓ python3：$(python3 --version 2>&1)"
  if python3 -m pytest --version >/dev/null 2>&1; then
    echo "  ✓ pytest 可用"; ok=$((ok+1))
  else
    echo "  ⊘ pytest 未安裝（Python 項目才需要；如不需要可忽略）"
  fi
else
  echo "  ⊘ python3 未安裝"
fi

echo ""
echo "[4] 工作目錄狀態"
if git rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -z "$(git status --porcelain)" ]]; then
    echo "  ✓ 工作區乾淨（適合開始 /goal）"
  else
    echo "  ⚠ 工作區有未提交改動 —— 建議先 commit，確保回滾基線乾淨"
    warn=$((warn+1))
  fi
fi

echo ""
echo "═══ 結果：$ok 項就緒，$warn 項需注意 ═══"
# 退出碼可機械判定（R1）：0=就緒、1=有需注意項
if [[ $warn -eq 0 ]]; then echo "✓ 可以開始"; exit 0
else echo "⚠ 先處理上面標記項再進 /goal"; exit 1; fi
