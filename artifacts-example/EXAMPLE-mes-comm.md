<!-- AGENT-FACING WORKED EXAMPLE：走定位A 全流程。數字/細節按實況調整。 -->
# EXAMPLE — MES 通訊核心模組（定位A）

## 1. 規格（01-spec 填法）
目標：為產線設備做 MES↔PLC 通訊模組，支援連接/心跳保活/自動重連/指令收發。
約束：
- Python 3.11 + 標準 socket，不引重型框架
- 工廠內網，不得外連
- MUST NOT：多設備並發（本期單設備） / UI
接口（契約，不可擅改）：
```python
class MESConnection:
    def connect(self) -> bool
    def send(self, cmd: Command) -> Response
    def is_alive(self) -> bool
```
驗收（可機械檢驗）：
1. `pytest tests/ -q` 退出碼 0，test_connection.py/test_reconnect.py 全綠
2. `python3 -m coverage report` 中 mes_conn.py ≥ 90%
3. 模擬斷線 100 次，重連成功率 100%，無未捕獲異常
4. `git diff --name-only` 不含 `schema/`
5. 連續跑 3 次結果一致

## 2. 分流（routing.md）
Q：之後有 Agent 接手？需嚴格控接縫？ A：是（後續加指令解析模組接此通訊層） → A

## 3. 拆分 + 接縫契約
```
Goal A: 連接+心跳+重連（本例聚焦）
Goal B: 指令收發+解析（依賴A，只透過 MESConnection）
```
契約 = MESConnection（B 不得碰 A 內部）

## 4. /goal 完成條件（05-goal 填法）
```
/goal --tokens 200K 完成 MES 通訊核心，達成條件（全部滿足）：
1. `pytest tests/ -q` 退出碼 0，test_connection.py、test_reconnect.py 全綠
2. `python3 -m coverage report` 中 mes_conn.py ≥ 90%
3. 模擬斷線 100 次重連成功率 100%，無未捕獲異常（見 test_reconnect.py）
4. `git diff --name-only` 不含 schema/
5. 連續跑測試 3 次一致
6. 產出 HANDOFF.md，WHAT/WHY/TRAPS/接口/驗收 五區塊非空
[失敗熔斷] 連續3輪同錯 / 遇規格未覆蓋分叉 / 需動 schema / 連續2輪無進展 → 停下報告
[人類介入] 範圍超出Plan / 涉及權限外發刪除 → 停下等人
max 25 turns。每輪貼真實命令輸出，不要只說「已通過」。
```

## 5. 六道閘（goal-gates.md）
GATE-1 ✓ 條件全綁命令輸出 | GATE-2 ✓ git init+commit+feat/mes-conn 分支 | GATE-3 ✓ --tokens 200K+max 25+導 goal.log | GATE-4 ✓ 成功+熔斷並列 | GATE-5 ✓ 人類介入信號 | GATE-6 ✓ HANDOFF 列驗收項 → 放行

## 6. 最終驗收（人親跑，final-acceptance.md）
```bash
# acceptance.txt
pytest tests/ -q
python3 -m coverage report --fail-under=90
python3 tests/test_reconnect.py
# 跑：
./verify.sh acceptance.txt
# → 看 verify-*.log，確認真綠，不信 goal 自報
```

## 7. 復盤（lessons.md）
```
[2026-XX-XX] MES 通訊核心 — A
1. 最卡：重連退避策略，規格沒寫清間隔
2. 錯誤假設：以為 PLC 斷線主動回 FIN，實際靜默斷 → 下次規格問通訊對端行為
3. goal 條件 OK，無假綠
5. 沉澱：「斷線N次成功率100%」驗收寫法好用，收進模板
```
