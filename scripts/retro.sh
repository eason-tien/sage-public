#!/usr/bin/env bash
# retro.sh — 30 秒執行後檢討：生成一則 3 問骨架到 sage 倉 retro/（供週迭代彙整）
# 用法：./retro.sh <任務名> [目標目錄]
# 定位：提醒與便利，不是閘——不裁定任何流程，verify/lock 不依賴它（工具不是監獄）。
# set -e：本腳本不執行使用者命令，任何步驟失敗（如目錄建不出）都應立即以非零退出，不得假報 ✓。
set -euo pipefail

SOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_NAME="${1:-}"
OUT_DIR="${2:-$SOP_DIR/retro}"

if [[ -z "$TASK_NAME" ]]; then
  echo "用法：retro.sh <任務名> [目標目錄]"
  echo "範例：sage retro mes-comm-core   # 生成 retro/YYYYMMDD-HHMM-mes-comm-core.md"
  exit 1
fi

# 任務名校驗（同 new-task 字元集，另禁前導 -：與 PS 參數綁定行為對齊）
if [[ ! "$TASK_NAME" =~ ^[A-Za-z0-9._][A-Za-z0-9._-]*$ ]]; then
  echo "✗ 任務名只允許字母/數字/. _ -（收到：${TASK_NAME}）"
  exit 1
fi

STAMP="$(date -u +%Y%m%d-%H%M)"
FILE="$OUT_DIR/$STAMP-$TASK_NAME.md"
mkdir -p "$OUT_DIR"

if [[ -e "$FILE" ]]; then
  echo "同分鐘已有這個任務的檢討，直接編輯它：$FILE"
  exit 1
fi

cat > "$FILE" <<EOF
# retro — ${TASK_NAME}（$STAMP UTC）
## 1. 這次哪裡卡了？

## 2. 驗收哪條寫得好或爛？

## 3. SOP 本身哪裡摩擦？

值不值：
EOF

echo "✓ 檢討骨架：$FILE"
echo "  30 秒填完即可；週彙整見 checklists/weekly-retro.md。"
