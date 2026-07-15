<!-- AGENT-FACING. Plan 階段逐任務判定。預設A，明確適合才升B/降C。 -->
# routing — A/B/C 分流判定

DECIDE-1:「此任務之後會有別的 Agent 接手調整嗎？需嚴格控制模塊接縫嗎？」
- 都否 + 獨立一次性 → 可 C
- 任一是 → MUST A
- 純廣度探索（調研/審legacy/遷移評估） → B
- 探索/原型/設計向（產物可拋可重寫、機械驗收寫不出或寫了也假） → **不進 SAGE**：Claude 素身跑；
  產物要收編進主體系時 → 當外來模塊走 R6 ＋ 補驗收再併（硬套儀式或偷偷繞過都比明走此門更傷紀律）
- 拿不準 → A（最安全）

## A — 人主導拆分（核心/高風險/需接力/需嚴格接縫）
- [ ] 在 Plan 拆成有依賴順序的子 Goal
- [ ] 定接縫契約（CONTRACT.md），標不可擅改
- [ ] 每子 Goal 過六道閘（goal-gates.md）
- [ ] 每子 Goal 產 HANDOFF.md + PROGRESS.md
- [ ] 複雜子任務內部可嵌 B（加 ultracode 並行）
- [ ] 順序執行，可 /resume 恢復
- [ ] 增量集成（A綠→合→B…），MUST NOT 大爆炸

## B — UltraCode 並行探索（廣度）
- [ ] 唯讀為主的廣度探索
- [ ] 產出「啟發清單」非代碼（02-research.md）
- [ ] 做完 MUST 降回 high（控成本）
- [ ] 注意：workflow 中斷會從頭重跑

## C — UltraCode 全自動（一次性/獨立/無接力）
RED-LINE（一條都不能省，否則=無人值守幻覺機）：
- [ ] token 硬上限已設（C 無內建 cap）
- [ ] git init + 起始 commit + 分支/worktree 隔離
- [ ] 最終真實驗收：人親跑，不信自報綠 → R5
- [ ] 一次跑完別中斷（中斷從頭重跑）
- [ ] 做完 MUST 降回 high
- [ ] 產物併入主體系 → 當外來模塊額外驗接縫 → R6

## FORBIDDEN
- [ ] MUST NOT 對同一任務同時用 A+C（C自動拆分繞過A接縫契約=A白做）。同一任務只走一條。
