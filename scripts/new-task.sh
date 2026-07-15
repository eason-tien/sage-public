#!/usr/bin/env bash
# new-task.sh — 起一個新的 AI 輔助開發任務
# 用法：./new-task.sh <任務名> [目標目錄]
# 作用：建任務目錄、複製模板、git init + 起始 commit
set -euo pipefail

SOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # ai-dev-sop 根目錄
TASK_NAME="${1:-}"
BASE_DIR="${2:-$PWD}"

if [[ -z "$TASK_NAME" ]]; then
  echo "用法：$0 <任務名> [目標目錄]"
  echo "範例：$0 mes-comm-core ~/projects"
  exit 1
fi

# 任務名校驗：只允許字母/數字/. _ -
# 一舉擋住 (a) 路徑分隔符 / 與 ../ 逃逸  (b) sed 元字元 / & \ 破壞下方替換
if [[ ! "$TASK_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "✗ 任務名只允許字母/數字/. _ -（收到：${TASK_NAME}）"
  echo "  例如：mes-comm-core；請勿使用 /、空格、& 等字元。"
  exit 1
fi

TASK_DIR="$BASE_DIR/$TASK_NAME"
if [[ -e "$TASK_DIR" ]]; then
  echo "✗ 目錄已存在：$TASK_DIR"
  exit 1
fi

# 建目錄前先校驗 SOP 模板源齊全：工具包若被部分解壓/移動，及早失敗，連目錄都不建
for p in prompts checklists templates/HANDOFF.md templates/PROGRESS.md templates/CONTRACT.md templates/lessons.md; do
  if [[ ! -e "$SOP_DIR/$p" ]]; then
    echo "✗ SOP 模板缺失：$SOP_DIR/$p"
    echo "  ai-dev-sop 目錄可能不完整，請確認工具包完整後重試。"
    exit 1
  fi
done

echo "→ 建立任務目錄：$TASK_DIR"
mkdir -p "$TASK_DIR"/{sop,src,tests}

echo "→ 複製提示詞模板與 checklist 到 sop/"
cp -r "$SOP_DIR/prompts"    "$TASK_DIR/sop/prompts"
cp -r "$SOP_DIR/checklists" "$TASK_DIR/sop/checklists"
cp "$SOP_DIR/templates/HANDOFF.md"  "$TASK_DIR/sop/HANDOFF.md"
cp "$SOP_DIR/templates/PROGRESS.md" "$TASK_DIR/sop/PROGRESS.md"
cp "$SOP_DIR/templates/CONTRACT.md" "$TASK_DIR/sop/CONTRACT.md"
cp "$SOP_DIR/templates/lessons.md"  "$TASK_DIR/sop/lessons.md"

# 把任務名填進模板標題。任務名已校驗無 sed 元字元；
# 用 sed -i.bak（GNU/BSD 通用），失敗則告警而非靜默吞掉（對齊「失敗必報」）。
for f in HANDOFF.md PROGRESS.md CONTRACT.md lessons.md; do
  if sed -i.bak "s/\[任務名\]/$TASK_NAME/g" "$TASK_DIR/sop/$f"; then
    rm -f "$TASK_DIR/sop/$f.bak"
  else
    echo "⚠ 模板占位符替換失敗，請手動檢查 $TASK_DIR/sop/$f"
  fi
done

# 生成 acceptance.txt 骨架（小任務快車道直接填它 → verify.sh 跑它）
cat > "$TASK_DIR/acceptance.txt" <<'EOF'
# 驗收命令清單：一行一條可機械檢驗的命令；退出碼 0=通過、非0=不通過。
# verify.sh 會逐條跑並留證據。以 # 開頭或空白的行會被略過。
# 每行在獨立子 shell 執行、行間互不影響：cd/變數不跨行，需要的話寫在同一行用 && 串。
# 注意：全部是註解（0 條命令）的驗收集 verify 會拒絕認證（exit 2）——先填真驗收。
# 按你的任務改寫，範例：
#   pytest tests/ -q
#   python3 -m coverage report --fail-under=90
#   test -z "$(git diff --name-only | grep '^schema/')"   # 禁區未動（命令替換形，pipefail 下穩健）
#   cd frontend && npm test --silent
EOF

echo "→ git init + 起始 commit（回滾保護的起點）"
cd "$TASK_DIR"
git init -q
# 若未配置 git 身份，設一個僅本倉庫的預設值，避免 commit 失敗中斷
if ! git config user.email >/dev/null 2>&1; then
  git config user.email "ai-dev-sop@local"
  git config user.name  "ai-dev-sop"
  echo "  （已為本倉庫設預設 git 身份，可日後用 git config 改）"
fi
cat > .gitignore <<'EOF'
__pycache__/
*.pyc
.venv/
node_modules/
*.log
EOF
git add -A
git commit -q -m "chore: 任務 $TASK_NAME 起始骨架（SOP 模板 + git 回滾基線）"

echo ""
echo "✓ 任務已建立：$TASK_DIR"
echo ""
echo "下一步："
echo "  1. cd $TASK_DIR"
echo "  2. 編輯 sop/prompts/01-spec.md 填規格 + 驗收方式"
echo "  3. 把驗收命令填進 acceptance.txt，邊做邊用 verify.sh 驗"
echo ""
echo "  ▸ 小任務快車道：填 01-spec(目標+驗收) → 幹活 → verify.sh，三步收工"
echo "  ▸ 大任務/高風險才升級：A 拆分 + 接縫契約 + 多 CLI 審 + 六道閘"
echo "    （見 README「任務分流」與 checklists/）"
