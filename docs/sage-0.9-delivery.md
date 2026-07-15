# SAGE 0.9 Delivery Audit

## Scope

本次升級把 SAGE 政策層與 workflow-lab 執行層合併成一條不能把自動綠誤認成人類
驗收的交付鏈。

## P0 — semantics and portability

- `automated_gates_passed` 與 `r5_human_verification` 分離。
- Agent 產物固定 `r5_human_verification=pending`、`merge_authorized=false`。
- SAGE CLI 版本升至 0.9.0；CI push 僅監聽 master，PR2 目前執行五個跨平台
  check runs，另有獨立的 `SAGE Evidence` commit status。
- Claude Workflow 從 `import.meta.url` 推導 root；Stop-hook 使用 `SAGE_ROOT`。
  （**現況註記 v0.13.0**：`import.meta` 在 Workflow runtime 是啟動前 SyntaxError——此法已
  實測不可行並撤除，現行為 `args.sageRoot` 必填；見 CHANGELOG 0.13.0。本行保留為歷史記錄。）
- PR2 是唯一有效的整合候選，保持 draft、auto-merge 為 null；較早的 pilot PR 已關閉並
  由 PR2 取代。

## P1 — budgets, resume, gates

- Budget ledger 在呼叫 Agent 前預留 turns、token、USD 和時間。
- Promotion timeout／CI failure 可安全 resume；遠端 commit 改變即拒絕。
- `.sage/gates.json` 提供 argv-only gate plugins；內建 Ruff、Biome、actionlint、
  ShellCheck、Gitleaks 與 diff gate。
- Gate config 與 candidate patch 在執行前後都鎖定；Agent 改 gate 或 acceptance 改
  patch 均會 fail-closed。

## P2 — signed evidence

- Evidence manifest 使用 SSH namespace `sage-evidence` detached signature。
- Trusted signer fingerprint：
  `SHA256:3Pa2VT9bpQDBeYL+dCD3mS8zOW/CTteXMcF6Ws1gguE`。
- PR2 head 的精確 commit 與 patch hash 由簽署 manifest 記錄，避免交付文件保存很快
  過期的自我引用 SHA。當前候選已發布綠色 `SAGE Evidence` commit status；描述明確
  保留 human R5 pending。

## P3 — real repositories

- 12 個 pinned public repositories，12 種主要語言。
- 所有 repo 只當不可信資料；沒有執行其 build、test、hook 或程式碼。
- 12/12 clone／commit／語言／gate discovery／diff 有效。
- 10/12 通過嚴格 Gitleaks；另外兩個保留 redacted compatibility findings，未靜默
  suppress。詳見 `reports/real-repo-benchmark.md`。

## P4 — lightweight UI audit

- `examples/sprite-audit-game` 是原創 Canvas「星光小精靈」。
- Desktop 與 390px mobile browser QA 通過，無水平溢出。
- 方向鍵、WASD、觸控、得分、生命、出口與 restart 有 deterministic core。
- 公開 6 tests、隱藏 5 tests、HTTP、UI structure、plugin、lock、Biome、Gitleaks
  均由 `tools/audit_sprite_game.py` 裁決。
- 沒有安裝 OpenHands 或 `gh-aw`：目前不需要第二個大型 control plane；GitHub Agentic
  Workflows 保留為未來可選的 read-only observer，不能繞過 Promotion／R5。

## Human-owned final gate

以上只證明自動證據鏈。SAGE R5 仍要求人親跑最終 verify、review draft PR，並由人
決定 ready／merge。PR2 在完成新的文件修正、重跑 CI 與簽署 Evidence 後仍必須停在
這個人工閘；任何程式均沒有 merge 或 auto-merge 路徑。
