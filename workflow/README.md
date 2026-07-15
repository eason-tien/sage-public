# Evidence-Gated Multi-CLI Workflow

這是基準實驗後選出的風險分流流程。所有路徑都先在隔離 clone 中執行，
不直接修改來源 checkout，也不自動 commit、push 或建立 PR。

## 路由

| Route | 適用 | 編排 |
|---|---|---|
| `fast` | 小型、清楚、可獨立驗收 | Agy 實作 → 機械閘門 |
| `standard` | 一般功能、跨數個檔案 | Claude 實作 → 機械閘門 |
| `high` | 核心邏輯、安全、資料、跨模組接縫 | Agy 規劃 → Codex 實作 → 中間驗收 → Claude 審計 → 必要時 Codex 修正 → 最終驗收 |

所有 route 的完成條件相同：使用者提供的 acceptance commands、規格雜湊、
受保護檔案、`git diff --check`、Gitleaks，以及項目可用的 Ruff、Biome、
actionlint 閘門全部通過。最終 gates 不直接信任 agent workspace 的 ignored／gitlink 內容：
orchestrator 會在全新 clone 從 baseline 套用 exact binary patch，再於該可重建候選上執行驗收。

## 使用

```bash
python3 workflow/run.py \
  --repo /path/to/repository \
  --route high \
  --name issue-123 \
  --spec /path/to/task.md \
  --acceptance 'python3 -m pytest -q' \
  --acceptance 'pnpm test'
```

產物寫入本實驗室的 `runs/pilots/<name>/`。`result.json` 是機械裁決，
`final.patch` 可供人審查；其中的 SHA-256、檔案集合與原始驗收命令會寫入
`promotion_manifest`，供 Promotion Gate 鎖定已驗證產物。

## Promotion Gate

只有 `result.automated_gates_passed=true`、最終機械閘門通過、SSH Evidence 簽章可信
且 patch 完整性可證明的 run 才能
晉升。Promotion Gate 會從 GitHub 遠端最新 base 建立隔離 clone，確認原始來源
commit 是 base 的祖先，再把 patch 三方套用到全新的分支。它會重跑原本的
acceptance commands 與品質閘門，全部通過後才 commit、push 及建立 draft PR。新版
Evidence 亦會攜帶來源 repository 中尚未提交的已簽署 `knowledge/` records；Promotion
在驗證 patch 原始檔案集合後還原並明確 stage 這些 records，拒絕與 patch 重疊、路徑
穿越或 symlink，並在任何 acceptance gate 前執行 staged version invariant：
`python3 tools/check_version_record.py --repo . --vault knowledge --project-id <signed-project-id> --require-staged-update`。

```bash
python3 workflow/promote.py \
  --run runs/pilots/issue-123 \
  --repo /path/to/repository \
  --branch codex/issue-123 \
  --allowed-signers workflow/trusted_signers \
  --wait-timeout 1800
```

建立 PR 後會等待 GitHub checks，並在前後確認 PR 仍為 draft 且沒有
`autoMergeRequest`。CI 失敗、缺少 checks 或等待逾時都會令 promotion 失敗；
分支與 draft PR 會保留供人檢查，但流程沒有任何 merge 或 auto-merge 操作。

所有自動結果必須用 `automated_gates_passed` 表達，並固定留下
`r5_human_verification: pending`、`merge_authorized: false`。自動綠只表示可以交給
人親跑 SAGE `verify`，不得解讀成 R5 完成、ready 或 merge 授權。舊欄位 `passed`
暫時保留作相容 alias，但只代表自動閘門。

### 單一任務設定

從 version 2 的 `workflow/task.example.json` 複製任務設定，再使用：

```bash
python3 workflow/sage.py preflight --config path/to/task.json
python3 workflow/sage.py run --config path/to/task.json
python3 workflow/sage.py promote --config path/to/task.json
python3 workflow/sage.py resume-promotion --config path/to/task.json
```

### Obsidian memory 與 CodeGraph

`knowledge.vault` 是單一 Obsidian-compatible Markdown vault。Preflight 在派工前完成：

1. 核對 route 所需 CLI、CodeGraph、Obsidian、Gitleaks 與 Evidence key；
2. 從 tracked file patterns 偵測語言並建立／更新相關 knowledge notes；
3. 取得專案 Memory 與 Ver ledger，計算下一個 patch version；
4. 產生一份有 SHA-256 的 read-only `SAGE_KNOWLEDGE.md`；
5. 在隔離 workspace 初始化或同步 `.codegraph/` 後才允許第一個 Agent stage。

所有 Agent prompt 都強制先讀同一份 briefing 並使用 `codegraph explore`。Agent 修改
briefing、`AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 或 gate config 都會失敗。每輪 gates
再次同步 CodeGraph。任務結束時 orchestrator 單寫 Task note、蒸餾 Memory，成功才更新
`Ver.md`；human-readable snapshots、`State.json`、pending repository knowledge tree 與
`post-task.json` 由 Evidence manifest 一併簽署。外部 vault 的 repository tree 為空，
既有只有五個 flat knowledge artifacts 的 schema-v1 Evidence 仍可驗證但不會憑空還原
repository knowledge。
Pre-commit 對 staged diff、CI 對 HEAD diff 都會要求同一組 Memory／State／Ver／Task
note；完整保留歷史也會重驗。最新版 ledger 除宣告檔案外，還以 canonical candidate-tree
SHA-256 綁定所有版本化 path、Git mode 與 Git clean-filter 後的 bytes；worktree 透過臨時
index/object DB 計算，確保 CRLF checkout、自訂 filter、staged index 與 commit 使用同一 canonical
byte domain，並拒絕同名二次篡改、type change 或 rename-source 漏記。

Web UI／網站 UI／桌面視覺 UI／WPF/XAML 任務會觸發 Stitch gate。認證使用官方 Stitch
MCP/SDK 的 `STITCH_API_KEY`，或 `STITCH_ACCESS_TOKEN` 加 `GOOGLE_CLOUD_PROJECT`；
也可由 Google Ultra 會員帳號登入 Stitch 網頁後匯出 `DESIGN.md`。Task config 的
`knowledge.stitch_design` 指向該檔，orchestrator 會複製並鎖定為
`STITCH_DESIGN.md`。沒有設計檔就不會派工。自動診斷只可使用
`claude mcp list`/`codex mcp list`；不可執行會回顯 Header 的 MCP 詳情命令。

Promotion resume 只接受已 commit／push 且已建立 draft PR 的 attempt；它會先確認
遠端 branch OID 沒變、簽章仍可信、PR 仍 draft 且無 auto-merge，才重新等待 CI。

### 預算

每個 Agent stage 啟動前先保留 turn、token ceiling、USD ceiling 與 wall-time。未知的
訂閱制 CLI 費用不會被冒充為精確 billing：`budget.json` 分開記錄 preauthorized
reservation 與 visible-I/O token estimate。任何一項超限都在下一個模型呼叫前拒絕。

可以在任務設定的 `budget` 區塊選填 `stage_idle_timeout_seconds` 與 `heartbeat_interval_seconds`，以自訂進程監控的超時與心跳頻率。


### 可插拔 gates

項目可以新增 `.sage/gates.json`：

```json
{
  "version": 1,
  "gates": [
    {
      "id": "go_test",
      "globs": ["*.go"],
      "required_files": ["go.mod"],
      "command": ["go", "test", "./..."],
      "append_files": false
    }
  ]
}
```

`command` 必須是 argv array；`{files}` 只能作獨立 argv item，並禁止 shell interpreter。
Gate 設定在建立 run 時鎖定雜湊，Agent 不能新增或修改；acceptance 與 quality gates
若改變 candidate patch，該輪會 fail-closed。全新 candidate clone 會在 CodeGraph 與任何 gate
前拒絕 absolute 或解析後離開 candidate root 的 symlink、移除 source remote，並用 credential-
minimized environment 執行。但 gate 程式仍能在單一行程內暫時建立 symlink 或直接讀主機；
簽署 result 會以 `runtime_boundary` 明列 filesystem/network sandbox=false。hostile candidate 的
高信任無人值守必須把整個 runner 放進外部 container／VM，不能把前後掃描當 OS sandbox。

### 簽署 Evidence

`workflow/run.py` 必須取得 `--signing-key`，產生 `evidence/manifest.json` 與 detached
SSH signature。Promotion 必須取得 `--allowed-signers` 並重驗 result、patch、budget
hash 和安全狀態，未簽、被改或 signer 不受信都 fail-closed。manifest 直接簽 exact
in-memory bytes、自驗後原子發布；驗證端會把 run/head/acceptance/scope 再對回 result。

## Reviewer 閘門

Reviewer 只有在 finding 同時包含以下證據時才能要求返工：

1. 被違反的規格原文；
2. 最小重現輸入或失敗命令。

缺任一項只能列為 advisory。`PASS + 全部機械閘門通過` 時不再呼叫實作者。
