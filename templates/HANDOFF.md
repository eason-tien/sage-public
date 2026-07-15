<!-- AGENT-FILLED SCHEMA. 跨 Agent 交接，給下一個調整的 Agent（非審計日誌）。完成時 MUST 趁記得上下文產出，事後補不出。 -->
# HANDOFF — [任務名]

NOTE: 記「接手者需知道什麼才能安全接續」。WHY/TRAPS 是精髓，缺了接手 = 從零理解。

## 1. STATUS (required)
- 完成度：[已完成 / 部分(卡第X步) / 失敗熔斷]
- 最後 commit：[hash]
- 驗收結果：[哪些綠/哪些沒過，附真實命令輸出]

## 2. WHAT (required)
- 新增/修改文件：`path` — [職責]
- 對外接口：
  ```
  [函數簽名 + 輸入輸出契約]
  ```

## 3. WHY (required) ★審計日誌沒有
- 關鍵設計決策 + 理由
- 放棄的方案 + 為何放棄（防接手者重蹈）
- 借鏡來源

## 4. TRAPS (required) ★接手者最先看
- 已知的坑：[見 file:line]
- 不能動的東西：[約束]
- 假設：[若改變則需重構之處]

## 5. FOR NEXT AGENT (required)
- 要調整 X → 改 `file:line`，注意 [約束]
- TODO：[未完成]
- 驗收怎麼跑（複製即執行）：
  ```bash
  [驗收命令]
  ```
