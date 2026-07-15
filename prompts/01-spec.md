<!-- AGENT-FACING TEMPLATE. 每新項目 cp 一份填。[ ]=待填。鐵律見 SAGE_RULES.md R1–R9。 -->
# 01 — 規格契約（階段1~4 + 驗收）

NOTE: 本文件=整套地基。地基模糊 → Agent 把模糊放大成模糊代碼。1~4 思考深度 = 提示詞質量上限，Agent 替不了。

## 目標
[一句話：解決什麼問題 + 成功長什麼樣]

## 約束與邊界
- 語言/框架/版本：[如 Python 3.11 + FastAPI]
- 運行環境：[如 Windows 本機 / 工廠內網]
- 依賴限制：[能用/不能用什麼]
- MUST NOT 做：[明確排除項，防範圍蔓延]
- 性能/安全限制：[如 P95<200ms / 不得外連]

## 數據模型/接口（契約，Agent MUST NOT 擅改）
```
[Schema / 接口簽名 / 數據結構]
```

## 架構/分層
- 模塊劃分：[A 依賴 B，不可反向]
- 文件結構（預期）：[目錄樹]

## 驗收方式（可機械檢驗） ★命門，MUST NOT 省/模糊 → R1
RULE: 每條 MUST 能由「跑1命令 + 看輸出/退出碼」判 true/false。
MUST NOT:「功能正常」「通訊穩定」「質量好」這類靠閱讀判定的。
RULE: lock 前先問「這套驗收下，最爛但仍能全綠的實作長什麼樣？」→ 把答案暴露的洞補進驗收。
起草驗收的 agent MUST NOT 同時是實作 agent（P1）。範式參考：sage 倉 `templates/acceptance-patterns.md`。
1. [如] `pytest tests/ -q` 退出碼 0，test_xxx.py 全綠
2. [如] `coverage report` 中 [模塊].py ≥ 95%
3. [如] 模擬 [失敗場景] N 次，成功率 100%，無未捕獲異常
4. [如] `git diff --name-only` 不含 [禁區路徑]
5. [如] 連續運行 3 次結果一致（輸出 hash 相同）

## AGENT 行為約束（MUST）
- 先輸出計劃/骨架，MUST NOT 直接寫實現，等人確認。
- MUST 列出所有假設，逐條等人確認。MUST NOT 默默猜然後當事實往下做。
- 規格有歧義/不確定 → MUST 標出問人，MUST NOT 自編一個往下跑。
- 外部 API/工具 MUST 先確認存在再用。
- 不確定 MUST 停下求助，MUST NOT 編造答案。
- 進度與完成 MUST 用可看成品呈現（截圖/跑起來的樣子/真實輸出 + 當前步驟），文字壓到最少、少用縮寫。 → R8
