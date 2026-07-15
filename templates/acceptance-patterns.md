<!-- AGENT-FACING 參考庫（人起草驗收時翻閱；不隨 new-task 複製進任務目錄）。 -->
# acceptance-patterns — 常見任務型的驗收範式

用法：起草 acceptance.txt 時按任務型抄改。每條=1命令+退出碼（R1）；每行獨立子行程。跨步驟串接：
bash 同行用 `&&`；PowerShell 注意 `;` **不短路**（中段原生命令失敗會被後段洗綠；cmdlet 錯誤仍會判紅）——
原生多步驟請包成 .ps1 用 exit 傳碼，或拆成獨立驗收行。lock 前必問：「這套驗收下，最爛但仍能全綠的實作長什麼樣？」

## 1. bugfix
```
# 必有一條：修前會紅的復現命令（先跑一次看它紅，修完轉綠——證明修的是這個 bug）
python3 -m pytest tests/test_issue_123.py -q
# 迴歸不破：原有測試全綠
python3 -m pytest tests/ -q
# 禁區未動（修 bug 不順手重構）：改動清單裡不得出現禁區路徑
# 用命令替換而非 grep -q 管線：避免 -q 提早退出在 pipefail 下產生 SIGPIPE 誤判
test -z "$(git diff --name-only origin/main | grep '^src/core/')"
```

## 2. CLI 工具
```
# 正常路徑：真實輸入 → 預期輸出/退出碼
./mycli convert sample.in -o /tmp/out.json && python3 -c "import json;json.load(open('/tmp/out.json'))"
# 失敗路徑必須紅得乾淨：壞輸入 → 非零退出碼＋stderr 有訊息（不是 traceback 噴一屏）
./mycli convert nonexistent.in 2>/tmp/err.txt; test $? -ne 0 && test -s /tmp/err.txt
# help/version 可機械查驗
./mycli --version | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'
```

## 3. API 服務
```
# 服務型驗收首選：包進專案測試 runner（pytest fixture 起服務），驗收只跑 runner
python3 -m pytest tests/test_api.py -q
# 直接驗時，同一行「起 → 等 → 測 → 收」自包含（行間不共享狀態，背景行程不得洩漏到行外）：
sh -c './run-server.sh --port 18080 & p=$!; sleep 2; curl -sf http://localhost:18080/health | grep -q ok; r=$?; kill $p; exit $r'
sh -c './run-server.sh --port 18081 & p=$!; sleep 2; c=$(curl -s -o /dev/null -w %{http_code} -X POST localhost:18081/api/items -d garbage); kill $p; case $c in 4??) exit 0;; *) exit 1;; esac'
```

## 4. 資料轉換/遷移
```
# 條數守恆（或明確的預期差額）
test "$(wc -l < output.csv)" = "$(wc -l < input.csv)"
# 冪等：連跑兩次結果 hash 相同
./transform.sh input.csv out1.csv && ./transform.sh input.csv out2.csv && cmp -s out1.csv out2.csv
# 抽樣欄位值可驗（挑已知記錄硬斷言，防「格式對了內容錯了」）
grep -q '^A1001,活性,42$' output.csv
```
