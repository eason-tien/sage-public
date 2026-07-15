<!-- AGENT-FILLED. 接縫契約，拆分時定。所有相關子 Goal 規格 MUST 引用本契約。 -->
# CONTRACT — 接縫契約（任務：[任務名]）

RULE: 任一子 Goal 想改契約 = 觸發人類介入信號，MUST 停下找人，MUST NOT 自行修改。 → GATE-5

## 模塊清單與依賴方向
```
Goal A: [模塊] — [職責]
Goal B: [模塊] — [職責]，依賴 A（只透過下方接口，不得碰 A 內部）
Goal C: [模塊] — [職責]，依賴 B
```
依賴：A → B → C（單向，禁反向/循環）

## 接縫接口定義（不可擅改）
### A 對外暴露
```
def connect() -> bool          # 契約：成功返回 True
def send(cmd: Command) -> Response
def is_alive() -> bool
```
### B 對外暴露
```
[...]
```

## 共享數據結構
```
[跨模塊數據結構，例 Command/Response 字段]
```

## 變更記錄
| 日期 | 改了什麼 | 經誰確認 |
|---|---|---|
| | 初版 | [人] |
