#!/usr/bin/env bash
# selftest.sh — 自检：在臨時目錄驗證 Bash 工具在本機能否正常工作（不調用真實 AI CLI）
# 用法：bash selftest.sh   （全部通過 exit 0；任一檢查失敗 exit 1）
# 它自己就是「可機械檢驗」的示範：跑一次看 true/false，不靠閱讀理解。
set -uo pipefail

SOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCR="$SOP_DIR/scripts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0
ok() { echo "  ✓ $1"; pass=$((pass+1)); }
ng() { echo "  ✗ $1"; fail=$((fail+1)); }
eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else ng "$1（得到 [$2] 期望 [$3]）"; fi; }

echo "═══ ai-dev-sop 自检（bash）═══"
echo "臨時目錄：$TMP"
echo ""

echo "[new-task.sh]"
bash "$SCR/new-task.sh" demo-x "$TMP" >/dev/null 2>&1; rc=$?
eq "正常任務名 → exit 0" "$rc" "0"
if [[ -f "$TMP/demo-x/sop/prompts/01-spec.md" ]]; then ok "目錄結構正確"; else ng "目錄結構缺失"; fi
if grep -rq '\[任務名\]' "$TMP/demo-x/sop" 2>/dev/null; then ng "占位符未替換"; else ok "占位符已替換"; fi
if [[ -f "$TMP/demo-x/acceptance.txt" ]]; then ok "已生成 acceptance.txt"; else ng "缺 acceptance.txt"; fi
if [[ -f "$TMP/demo-x/sop/lessons.md" ]]; then ok "已複製 lessons.md 復盤模板（非孤兒）"; else ng "缺 sop/lessons.md（孤兒模板未修）"; fi
bash "$SCR/new-task.sh" "bad/name" "$TMP" >/dev/null 2>&1; rc=$?
eq "非法任務名 → exit 1（拒絕）" "$rc" "1"

echo ""
echo "[verify.sh]"
printf 'true\ntrue\n'  > "$TMP/acc_ok.txt"
printf 'true\nfalse\n' > "$TMP/acc_ng.txt"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_ok.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "全部通過(+--allow-unlocked) → exit 0" "$rc" "0"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_ng.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "有失敗(+--allow-unlocked) → exit 1" "$rc" "1"
if ( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_ok.txt" --allow-unlocked ) 2>/dev/null | grep -q 'sage retro'; then
  ok "全綠訊息含 retro 提示（提醒非強制）"
else
  ng "全綠訊息缺 retro 提示"
fi
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_ok.txt" ) >/dev/null 2>&1; rc=$?
eq "無鎖無 override → 拒絕 fail-closed exit 2 (C2)" "$rc" "2"
( cd "$TMP" && SAGE_ALLOW_UNLOCKED=1 bash "$SCR/verify.sh" "$TMP/acc_ok.txt" ) >/dev/null 2>&1; rc=$?
eq "環境變數不能替代顯式旗標 → 仍 exit 2 (B-08)" "$rc" "2"
printf 'printf "true\\n" > "%s"\nfalse\n' "$TMP/acc_snapshot.txt" > "$TMP/acc_snapshot.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" lock "$TMP/acc_snapshot.txt" ) >/dev/null 2>&1
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_snapshot.txt" ) >/dev/null 2>&1; rc=$?
eq "驗收第一行換掉原檔也不能跳過 snapshot 內後續 false → exit 1" "$rc" "1"

# —— 假綠面負向案例（AUDIT 2026-07-13 迭代 1）：這些全都必須「紅得出來」——
printf 'exit 0\nfalse\n' > "$TMP/acc_exit.txt"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_exit.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "驗收行含 exit 不劫持 runner，後續失敗行照計 → exit 1 (B-01)" "$rc" "1"
printf 'false\nfail=0\ntrue\n' > "$TMP/acc_wash.txt"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_wash.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "驗收行賦值洗不掉計數器 → exit 1 (B-02)" "$rc" "1"
printf 'true\nfalse' > "$TMP/acc_noeol.txt"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_noeol.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "無尾換行的最後一行仍被執行 → exit 1 (B-03)" "$rc" "1"
printf '# 只有註解，一條驗收都沒有\n' > "$TMP/acc_empty.txt"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_empty.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "空驗收集不可認證 → exit 2 (B-04)" "$rc" "2"
printf 'true\r\ntrue\r\n' > "$TMP/acc_crlf.txt"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_crlf.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "CRLF 驗收檔正常執行 → exit 0 (B-09)" "$rc" "0"
printf 'false | tee /dev/null\n' > "$TMP/acc_pipe.txt"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_pipe.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "管線中段失敗（pipefail）→ exit 1（不因末段 tee 翻綠）" "$rc" "1"
printf 'cat\ntrue\n' > "$TMP/acc_stdin.txt"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_stdin.txt" --allow-unlocked </dev/null ) >/dev/null 2>&1; rc=$?
eq "會讀 stdin 的驗收行立即 EOF 不掛死、不吞後續行 → exit 0" "$rc" "0"
mkdir -p "$TMP/cdcase" && printf 'cd /\ntrue\n' > "$TMP/cdcase/acc_cd.txt"
( cd "$TMP/cdcase" && bash "$SCR/verify.sh" "$TMP/cdcase/acc_cd.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
if [[ $rc -eq 0 ]] && ls "$TMP/cdcase"/verify-*.log >/dev/null 2>&1; then
  ok "驗收行 cd 不劈走證據日誌（LOG 絕對路徑）(B-02)"
else
  ng "cd 案例失敗（rc=$rc 或日誌不在起始目錄）"
fi

echo ""
echo "[retro.sh]"
bash "$SCR/retro.sh" demo-x "$TMP/retro-out" >/dev/null 2>&1; rc=$?
eq "正常生成檢討骨架 → exit 0" "$rc" "0"
rfile="$(cd "$TMP/retro-out" 2>/dev/null && compgen -G '*.md' | head -1)"
if [[ "$rfile" =~ ^[0-9]{8}-[0-9]{4}-demo-x\.md$ ]]; then ok "檔名為 UTC 零填充格式"; else ng "檔名格式錯（${rfile}）"; fi
if [[ -n "$rfile" ]] && grep -q '這次哪裡卡了' "$TMP/retro-out/$rfile" \
   && grep -q '驗收哪條寫得好或爛' "$TMP/retro-out/$rfile" \
   && grep -q 'SOP 本身哪裡摩擦' "$TMP/retro-out/$rfile" \
   && grep -q '值不值' "$TMP/retro-out/$rfile"; then
  ok "骨架含 3 問＋值不值"
else
  ng "骨架內容缺欄位"
fi
bash "$SCR/retro.sh" "bad/name" "$TMP/retro-out" >/dev/null 2>&1; rc=$?
eq "非法任務名 → exit 1（拒絕）" "$rc" "1"
bash "$SCR/retro.sh" "-h" "$TMP/retro-out" >/dev/null 2>&1; rc=$?
eq "前導 - 的任務名 → exit 1（與 PS 參數綁定對齊）" "$rc" "1"
touch "$TMP/rblock"
if bash "$SCR/retro.sh" demo-f "$TMP/rblock/sub" >/dev/null 2>&1; then
  ng "目錄建不出仍報成功（假 ✓）"
else
  ok "目錄建不出 → 非零退出，不假報 ✓（set -e）"
fi
bash "$SOP_DIR/sage" retro demo-y "$TMP/retro-out2" >/dev/null 2>&1; rc=$?
if [[ $rc -eq 0 ]] && ls "$TMP/retro-out2"/*-demo-y.md >/dev/null 2>&1; then
  ok "sage retro 經 dispatcher 可用"
else
  ng "dispatcher retro 失敗（rc=${rc}）"
fi

echo ""
echo "[verify.sh 驗收命令變更目錄]"
CWD_CASE="$TMP/cwdcase"; mkdir -p "$CWD_CASE/nested"
# $(pwd) 故意不在此展開：要寫進驗收命令清單，留給 verify.sh 之後執行時才展開
# shellcheck disable=SC2016
printf 'cd "%s/nested" && echo IN_NESTED\n[ "$(pwd)" = "%s" ] && echo BACK_IN_INVOKE_DIR || echo STILL_DISPLACED\n' \
  "$CWD_CASE" "$CWD_CASE" > "$CWD_CASE/acc_cwd.txt"
( cd "$CWD_CASE" && bash "$SCR/verify.sh" "$CWD_CASE/acc_cwd.txt" --allow-unlocked ) >/dev/null 2>&1; rc=$?
eq "含 cd 的驗收命令仍全部通過 → exit 0" "$rc" "0"
cwd_log_count=$(find "$CWD_CASE" -maxdepth 1 -name 'verify-*.log' | wc -l | tr -d ' ')
eq "呼叫目錄僅一份 verify-*.log" "$cwd_log_count" "1"
if find "$CWD_CASE/nested" -maxdepth 1 -name 'verify-*.log' | grep -q .; then
  ng "nested 目錄出現分裂日誌"
else
  ok "nested 目錄無分裂日誌"
fi
cwd_log_file=$(find "$CWD_CASE" -maxdepth 1 -name 'verify-*.log' | head -n1)
# 每條命令的原始文字本身會被寫入 "[$n] $ $cmd" 標頭，所以命令原文中未觸發的分支
# 文字（如 STILL_DISPLACED）一定也會出現 1 次；真正判斷位置是否還原，要看該記號
# 是否「額外」以獨立輸出行出現：BACK_IN_INVOKE_DIR 若真的還原，記錄裡會出現 2 次
# （標頭 1 次 + 實際輸出 1 次)，STILL_DISPLACED 則只會有標頭那 1 次。
in_nested_count=0; back_count=0; displaced_count=0
if [[ -n "$cwd_log_file" ]]; then
  in_nested_count=$(grep -c 'IN_NESTED' "$cwd_log_file" || true)
  back_count=$(grep -c 'BACK_IN_INVOKE_DIR' "$cwd_log_file" || true)
  displaced_count=$(grep -c 'STILL_DISPLACED' "$cwd_log_file" || true)
fi
if [[ -n "$cwd_log_file" ]] && [[ "$in_nested_count" -eq 2 ]] && [[ "$back_count" -eq 2 ]] \
  && [[ "$displaced_count" -eq 1 ]] && grep -q '2 通過 / 0 不通過' "$cwd_log_file"; then
  ok "單一日誌含兩條命令輸出、後續命令位置已還原、與最終彙總"
else
  ng "日誌缺少命令輸出、位置未還原、或彙總缺失"
fi

echo ""
echo "[acceptance-lock.sh]"
printf 'true\n' > "$TMP/acc_lock.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" lock "$TMP/acc_lock.txt" ) >/dev/null 2>&1; rc=$?
eq "lock → exit 0" "$rc" "0"
if [[ -f "$TMP/acc_lock.txt.lock" ]]; then ok "已生成 .lock"; else ng "缺 .lock"; fi
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" check "$TMP/acc_lock.txt" ) >/dev/null 2>&1; rc=$?
eq "未改 check → exit 0" "$rc" "0"
printf 'true\nfalse\n' > "$TMP/acc_lock.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" check "$TMP/acc_lock.txt" ) >/dev/null 2>&1; rc=$?
eq "改動後 check → exit 1（防篡改）" "$rc" "1"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_lock.txt" ) >/dev/null 2>&1; rc=$?
eq "驗收集被改 → verify 拒絕認證 exit 2" "$rc" "2"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" lock "$TMP/acc_lock.txt" ) >/dev/null 2>&1; rc=$?
eq "已鎖再 lock → exit 1（拒靜默重鎖 C1）" "$rc" "1"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" relock "$TMP/acc_lock.txt" ) >/dev/null 2>&1; rc=$?
eq "relock → exit 0（顯式重鎖）" "$rc" "0"
mkdir -p "$TMP/fakebin"
printf '#!/usr/bin/env bash\nexit 127\n' > "$TMP/fakebin/sha256sum"
chmod +x "$TMP/fakebin/sha256sum"
printf 'true\n' > "$TMP/acc_badhash.txt"
( cd "$TMP" && PATH="$TMP/fakebin:$PATH" bash "$SCR/acceptance-lock.sh" lock "$TMP/acc_badhash.txt" ) >/dev/null 2>&1; rc=$?
if [[ $rc -ne 0 && ! -f "$TMP/acc_badhash.txt.lock" ]]; then
  ok "sha256 工具壞掉 → lock 拒絕寫壞鎖（fail-closed）(B-05)"
else
  ng "sha256 工具壞掉仍寫鎖（rc=${rc}）"
fi
mkdir -p "$TMP/failpythonbin"
printf '#!/usr/bin/env bash\nexit 1\n' > "$TMP/failpythonbin/python3"
chmod +x "$TMP/failpythonbin/python3"
printf 'true\n' > "$TMP/acc_badnormalize.txt"
( cd "$TMP" && PATH="$TMP/failpythonbin:$PATH" bash "$SCR/acceptance-lock.sh" lock "$TMP/acc_badnormalize.txt" ) >/dev/null 2>&1; rc=$?
if [[ $rc -ne 0 && ! -f "$TMP/acc_badnormalize.txt.lock" ]]; then
  ok "CRLF normalize 有輸出但 pipeline 非零 → lock fail-closed、不寫鎖"
else
  ng "normalize pipeline 失敗仍產生合法 digest/鎖（rc=${rc}）"
fi
printf '\377\r\n' > "$TMP/acc_binary.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" lock "$TMP/acc_binary.txt" ) >/dev/null 2>&1; rc=$?
eq "非 UTF-8 bytes 在 byte locale 可 lock" "$rc" "0"
printf '\376\r\n' > "$TMP/acc_binary.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" check "$TMP/acc_binary.txt" ) >/dev/null 2>&1; rc=$?
eq "binary byte 變更 → check exit 1" "$rc" "1"
printf 'exit 1\n' > "$TMP/acc_lone_cr.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" lock "$TMP/acc_lone_cr.txt" ) >/dev/null 2>&1; rc=$?
eq "lone-CR 樣本 lock → exit 0" "$rc" "0"
printf 'exit\r 1\n' > "$TMP/acc_lone_cr.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" check "$TMP/acc_lone_cr.txt" ) >/dev/null 2>&1; rc=$?
eq "插入 lone CR 必須 TAMPERED → check exit 1" "$rc" "1"
( cd "$TMP" && bash "$SCR/verify.sh" "$TMP/acc_lone_cr.txt" ) >/dev/null 2>&1; rc=$?
eq "lone CR 篡改後 verify 先拒絕、不執行 → exit 2" "$rc" "2"
printf 'true\r' > "$TMP/acc_eof_cr.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" lock "$TMP/acc_eof_cr.txt" ) >/dev/null 2>&1; rc=$?
eq "EOF lone CR 可建立語義保留鎖" "$rc" "0"
if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoProfile -File "$SCR/acceptance-lock.ps1" check "$TMP/acc_eof_cr.txt" >/dev/null 2>&1; rc=$?
  eq "Bash 鎖與 PowerShell 對 EOF lone CR 雜湊一致" "$rc" "0"
fi
mkdir "$TMP/acc_write_fail.txt.lock"
printf 'true\n' > "$TMP/acc_write_fail.txt"
( cd "$TMP" && bash "$SCR/acceptance-lock.sh" relock "$TMP/acc_write_fail.txt" ) >/dev/null 2>&1; rc=$?
if [[ $rc -ne 0 ]]; then ok "lock 寫入目標為目錄 → 非零、不假報 locked"; else ng "lock 寫入失敗仍回報成功"; fi

echo ""
echo "[preflight.sh]"
pf="$(bash "$SCR/preflight.sh" 2>&1)"; rc=$?
if echo "$pf" | grep -q '環境前置檢查'; then ok "preflight 執行並輸出結果"; else ng "preflight 無預期輸出"; fi
if [[ $rc -eq 0 || $rc -eq 1 ]]; then ok "preflight 退出碼可機械判定（0=就緒/1=需注意）(B-10)"; else ng "preflight 退出碼異常（${rc}）"; fi
# 釘住 warn→1 映射：非 git 目錄必有 warn，必須 exit 1（rc∈{0,1} 攔不住「永遠 0」的原病灶）
mkdir -p "$TMP/nogit" && ( cd "$TMP/nogit" && bash "$SCR/preflight.sh" ) >/dev/null 2>&1; rc=$?
eq "非 git 目錄（必有 warn）→ exit 1 (B-10 映射釘死)" "$rc" "1"

echo ""
echo "[crosscheck.sh]（用樁 CLI，不調真實 AI）"
mkdir -p "$TMP/stubbin"
cat > "$TMP/stub-cli" <<'EOF'
#!/usr/bin/env bash
name="${0##*/}"
printf '%s %s\n' "$name" "$*" >> "$SAGE_STUB_LOG"
if [[ "${SAGE_STUB_EMPTY:-0}" == "1" ]]; then
  printf '   \n'
else
  printf 'stub-%s output\n' "$name"
fi
if [[ "${SAGE_STUB_STDERR:-0}" == "1" ]]; then
  printf 'native stderr failure marker\n' >&2
fi
if [[ "${SAGE_STUB_CHECK_ISOLATION:-0}" == "1" && "$name" == "codex" ]]; then
  if [[ -e review-claude.md ]]; then printf 'SAW_PRIOR_REVIEW_ANCHOR\n';
  else printf 'ISOLATED_FROM_PRIOR_REVIEW\n'; fi
fi
EOF
for c in claude codex agy gemini grok; do
  cp "$TMP/stub-cli" "$TMP/stubbin/$c"
  chmod +x "$TMP/stubbin/$c"
done
printf '# 待審內容（自检樣本）\n' > "$TMP/rev.md"
SAGE_STUB_LOG="$TMP/stub-calls.log" PATH="$TMP/stubbin:/usr/bin:/bin" bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout" >/dev/null 2>&1; rc=$?
eq "正常執行 → exit 0" "$rc" "0"
if [[ -s "$TMP/ccout/review-claude.md" ]]; then ok "產出 review-claude.md"; else ng "缺 review 輸出"; fi
if [[ -e "$TMP/ccout/review-claude.md.err" ]]; then ng "空 .err 未清理"; else ok "空 .err 已清理"; fi
if grep -q '^agy --print ' "$TMP/stub-calls.log" && [[ -s "$TMP/ccout/review-agy.md" ]]; then
  ok "Agy 使用 --print 並產出 review-agy.md"
else
  ng "Agy adapter 或輸出缺失"
fi
if grep -q '^gemini ' "$TMP/stub-calls.log" || [[ -e "$TMP/ccout/review-gemini.md" ]]; then
  ng "Agy 存在時仍調用了 legacy Gemini"
else
  ok "Agy 存在時不調 legacy Gemini"
fi
SAGE_STUB_CHECK_ISOLATION=1 SAGE_STUB_LOG="$TMP/isolation-calls.log" PATH="$TMP/stubbin:/usr/bin:/bin" bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout-isolation" >/dev/null 2>&1; rc=$?
if [[ $rc -eq 0 ]] && grep -q 'ISOLATED_FROM_PRIOR_REVIEW' "$TMP/ccout-isolation/review-codex.md" \
  && ! grep -q 'SAW_PRIOR_REVIEW_ANCHOR' "$TMP/ccout-isolation/review-codex.md"; then
  ok "後續 reviewer cwd 看不到先前 review；全部完成後才集中發布"
else
  ng "reviewer cwd/發布隔離失效"
fi

rm "$TMP/stubbin/agy"
: > "$TMP/stub-calls.log"
SAGE_STUB_LOG="$TMP/stub-calls.log" PATH="$TMP/stubbin:/usr/bin:/bin" bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout-fallback" >/dev/null 2>&1; rc=$?
eq "Agy 缺失時 fallback → exit 0" "$rc" "0"
if grep -q '^gemini -p ' "$TMP/stub-calls.log" && [[ -s "$TMP/ccout-fallback/review-gemini.md" ]]; then
  ok "legacy Gemini 僅作 fallback"
else
  ng "legacy Gemini fallback 或輸出缺失"
fi
printf 'preserve me\n' > "$TMP/ccout-fallback/unrelated.txt"
cp "$TMP/stub-cli" "$TMP/stubbin/agy"; chmod +x "$TMP/stubbin/agy"
: > "$TMP/stub-calls.log"
SAGE_STUB_LOG="$TMP/stub-calls.log" PATH="$TMP/stubbin:/usr/bin:/bin" bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout-fallback" >/dev/null 2>&1; rc=$?
eq "重用輸出目錄切回 Agy → exit 0" "$rc" "0"
if [[ ! -e "$TMP/ccout-fallback/review-gemini.md" && -s "$TMP/ccout-fallback/review-agy.md" ]]; then
  ok "重用輸出目錄不殘留上一輪 Gemini 成功檔"
else
  ng "重用輸出目錄混入上一輪 reviewer 產物"
fi
if [[ -s "$TMP/ccout-fallback/unrelated.txt" ]]; then ok "清理保留非腳本管理檔"; else ng "清理誤刪使用者檔"; fi
bash "$SCR/crosscheck.sh" >/dev/null 2>&1; rc=$?
eq "缺參數 → exit 1" "$rc" "1"

PATH="/usr/bin:/bin" bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout-none" >/dev/null 2>&1; rc=$?
eq "0 家 reviewer 可用 → quorum fail-closed exit 1" "$rc" "1"
if find "$TMP/ccout-none" -maxdepth 1 -name 'review-*.md' | grep -q .; then
  ng "未安裝 marker 污染 review-*.md"
else
  ok "未安裝 reviewer 不生成成功 review-*.md"
fi

mkdir -p "$TMP/emptybin"
for c in claude codex agy grok; do
  cp "$TMP/stub-cli" "$TMP/emptybin/$c"
  chmod +x "$TMP/emptybin/$c"
done
SAGE_STUB_EMPTY=1 SAGE_STUB_LOG="$TMP/empty-calls.log" PATH="$TMP/emptybin:/usr/bin:/bin" bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout-empty" >/dev/null 2>&1; rc=$?
eq "全 reviewer 空白輸出 → quorum fail-closed exit 1" "$rc" "1"

SAGE_STUB_STDERR=1 SAGE_STUB_LOG="$TMP/stderr-calls.log" PATH="$TMP/emptybin:/usr/bin:/bin" bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout-stderr" >/dev/null 2>&1; rc=$?
eq "partial stdout + native stderr → quorum fail-closed exit 1" "$rc" "1"

mkdir -p "$TMP/onebin"
cp "$TMP/stub-cli" "$TMP/onebin/claude"; chmod +x "$TMP/onebin/claude"
SAGE_STUB_LOG="$TMP/one-calls.log" PATH="$TMP/onebin:/usr/bin:/bin" bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout-one" >/dev/null 2>&1; rc=$?
eq "僅 1 家成功 → 未達預設 quorum 2 exit 1" "$rc" "1"
SAGE_MIN_REVIEWERS=1 bash "$SCR/crosscheck.sh" "$TMP/rev.md" "$TMP/ccout-badquorum" >/dev/null 2>&1; rc=$?
eq "非法 quorum <2 → exit 1" "$rc" "1"

if awk 'NR==1{print $2}' "$TMP/acc_lock.txt.lock" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'; then
  ok "鎖時間戳為 UTC Z 格式（雙平台一致）"
else
  ng "鎖時間戳非 UTC Z 格式"
fi

echo ""
echo "[sage + install.sh]"
bash "$SOP_DIR/sage" help | grep -Fq 'sage <command>'; rc=$?
eq "dispatcher help → exit 0" "$rc" "0"
if [[ -x "$SOP_DIR/sage" ]]; then ok "sage 可執行"; else ng "sage 缺 executable bit"; fi
xbit_missing=""
for f in "$SCR"/*.sh; do [[ -x "$f" ]] || xbit_missing="$xbit_missing ${f##*/}"; done
if [[ -z "$xbit_missing" ]]; then ok "scripts/*.sh 全部有 executable bit (X-04)"; else ng "缺 executable bit:$xbit_missing"; fi
# 規則正文看守：R1–R9 逐條 + 關鍵機制詞都在（單一 grep 'R9' 是空殼閘，放個只含 R9 的檔就繞過；
# 此看守仍是 tamper-evident 而非 tamper-proof——蓄意造全詞假檔屬顯式欺詐，同 R9 的定位）
rules_out="$(bash "$SOP_DIR/sage" rules)"
rules_missing=""
for i in 1 2 3 4 5 6 7 8 9; do
  echo "$rules_out" | grep -q "R$i" || rules_missing="$rules_missing R$i"
done
echo "$rules_out" | grep -q 'acceptance-lock' || rules_missing="$rules_missing acceptance-lock"
echo "$rules_out" | grep -q 'fail-closed'     || rules_missing="$rules_missing fail-closed"
if [[ -z "$rules_missing" ]]; then
  ok "sage rules 印出完整鐵律正文（R1–R9 + 機制詞，SAGE_RULES.md）"
else
  ng "sage rules 正文缺:$rules_missing ——規則單一事實源斷鏈/被掏空"
fi
if [[ "$(bash "$SOP_DIR/sage" version)" == "$(cat "$SOP_DIR/VERSION")" ]]; then
  ok "dispatcher version 與 VERSION 一致"
else
  ng "dispatcher version 漂移"
fi

install_prefix="$TMP/prefix with spaces"
bash "$SCR/install.sh" --prefix "$install_prefix" >/dev/null 2>&1; rc=$?
eq "安裝到含空格 prefix → exit 0" "$rc" "0"
if [[ -L "$install_prefix/bin/sage" ]] && "$install_prefix/bin/sage" help | grep -Fq 'sage <command>'; then
  ok "安裝 symlink 可執行 dispatcher"
else
  ng "安裝 symlink 缺失或不可用"
fi
bash "$SCR/install.sh" --prefix "$install_prefix" >/dev/null 2>&1; rc=$?
eq "重複安裝 idempotent → exit 0" "$rc" "0"

unrelated_prefix="$TMP/unrelated"
mkdir -p "$unrelated_prefix/bin"
printf 'keep me\n' > "$unrelated_prefix/bin/sage"
bash "$SCR/install.sh" --prefix "$unrelated_prefix" >/dev/null 2>&1; rc=$?
eq "拒絕覆寫 unrelated target → exit 1" "$rc" "1"
if grep -Fq 'keep me' "$unrelated_prefix/bin/sage"; then ok "unrelated target 未改動"; else ng "unrelated target 被改動"; fi
bash "$SCR/install.sh" --prefix "$unrelated_prefix" --uninstall >/dev/null 2>&1; rc=$?
eq "拒絕移除 unrelated target → exit 1" "$rc" "1"
if grep -Fq 'keep me' "$unrelated_prefix/bin/sage"; then ok "uninstall 保留 unrelated target"; else ng "uninstall 改動 unrelated target"; fi

bash "$SCR/install.sh" --prefix "$install_prefix" --uninstall >/dev/null 2>&1; rc=$?
eq "uninstall → exit 0" "$rc" "0"
if [[ ! -e "$install_prefix/bin/sage" && ! -L "$install_prefix/bin/sage" ]]; then ok "owned symlink 已移除"; else ng "owned symlink 未移除"; fi
bash "$SCR/install.sh" --prefix "$install_prefix" --uninstall >/dev/null 2>&1; rc=$?
eq "重複 uninstall idempotent → exit 0" "$rc" "0"

echo ""
echo "[version/release 機械一致性] (X-05)"
ver="$(tr -d ' \r\n' < "$SOP_DIR/VERSION")"
cl="$(grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' "$SOP_DIR/CHANGELOG.md" | tr -d '#[] ')"
eq "VERSION == CHANGELOG 最新條目（${ver}）" "$ver" "$cl"
if grep -q "^\[$ver\]:" "$SOP_DIR/CHANGELOG.md"; then ok "CHANGELOG 連結錨點含 $ver"; else ng "CHANGELOG 缺 [$ver]: 連結錨點"; fi
sver="$(tr -d ' \r\n' < "$SOP_DIR/SOP_VERSION")"
scl="$(grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' "$SOP_DIR/SOP_CHANGELOG.md" | tr -d '#[] ')"
eq "SOP_VERSION == SOP_CHANGELOG 首條（凍結快照 ${sver}）" "$sver" "$scl"

echo ""
echo "[編碼不變量] (X-06)：.sh=LF 無 BOM；含非 ASCII 的 .ps1 必有 BOM"
enc_bad=""
for f in "$SOP_DIR/sage" "$SCR"/*.sh; do
  [[ "$(head -c3 "$f" | od -An -tx1 | tr -d ' \n')" == "efbbbf" ]] && enc_bad="$enc_bad ${f##*/}:BOM"
  grep -q $'\r' "$f" && enc_bad="$enc_bad ${f##*/}:CR"
done
for f in "$SOP_DIR/sage.ps1" "$SCR"/*.ps1; do
  # C locale 下非 ASCII 位元組不屬 [:print:]/[:space:]（可攜寫法，macOS BSD grep 無 -P）
  if LC_ALL=C grep -q '[^[:print:][:space:]]' "$f"; then
    [[ "$(head -c3 "$f" | od -An -tx1 | tr -d ' \n')" == "efbbbf" ]] || enc_bad="$enc_bad ${f##*/}:含中文無BOM"
  fi
done
if [[ -z "$enc_bad" ]]; then ok "全部腳本符合 DESIGN 編碼不變量"; else ng "編碼不變量違規:$enc_bad"; fi
# bash 3.2（macOS 系統 bash）相容：$VAR 緊貼非 ASCII 字元會把多位元組吃進變數名 → unbound crash。
# 一律要求 ${VAR} 大括號形。C locale 下非 ASCII 位元組不屬 [:print:]/[:space:]（BSD grep 可攜）。
b32_bad=""
for f in "$SOP_DIR/sage" "$SCR"/*.sh; do
  LC_ALL=C grep -qE '\$[A-Za-z_][A-Za-z0-9_]*[^[:print:][:space:]]' "$f" && b32_bad="$b32_bad ${f##*/}"
done
if [[ -z "$b32_bad" ]]; then
  ok "無 \$VAR 緊貼非 ASCII（bash 3.2/macOS 相容，需 \${VAR} 形）"
else
  ng "bash 3.2 地雷（\$VAR 緊貼非 ASCII，須加大括號）:$b32_bad"
fi

echo ""
echo "[workflows/sop-run.js]（形態2 語法煙測，有 node 才跑）"
# Workflow runtime 把腳本剝掉 export 後包進「普通（非 module）async 函式」再解析——
# 所以 import.meta 等 module-only 語法是啟動前 SyntaxError（0.13.0 修的實際事故）。
# 這裡用同形包裝只解析不執行：紅=Workflow 會拒啟動。兩處刻意收緊：
# - 只剝 `export const meta`（runtime 文件契約的那一個），行首其它 export 不誤傷；
# - 加 "use strict" 前導（runtime 嚴格性未實測；strict 是更嚴超集——寧可響亮誤紅，
#   不可 selftest 綠而 runtime 拒啟動的靜默漏放；本倉風格不用 sloppy-only 語法）。
# shellcheck disable=SC2016  # 刻意單引號：JS 程式碼字串，反引號/\n 必須原樣傳給 node、不可被 shell 展開
sop_parse='const fs=require("fs");const src=fs.readFileSync(process.argv[1],"utf8").replace(/^export (?=const meta)/m,"");const AF=Object.getPrototypeOf(async function(){}).constructor;new AF("args","budget","agent","parallel","pipeline","phase","log","workflow",`"use strict";\n`+src);'
if command -v node >/dev/null 2>&1; then
  if node -e "$sop_parse" "$SOP_DIR/workflows/sop-run.js" 2>"$TMP/sopjs.err"; then
    ok "sop-run.js 以 runtime 同形包裝可解析（AsyncFunction+strict，不執行）"
  else
    ng "sop-run.js 解析失敗（Workflow 會拒啟動）：$(grep -m1 -E '[A-Za-z]*Error' "$TMP/sopjs.err" 2>/dev/null || head -1 "$TMP/sopjs.err" 2>/dev/null)"
  fi
  node --test "$SOP_DIR/tests/sop-run.test.js" >/dev/null 2>&1; rc=$?
  eq "sop-run.js 語義／quorum／exception 負測全綠" "$rc" "0"
  # 守門自證（紅得出來）：module-only 語法必須被抓
  printf 'const x = import.meta.url\n' > "$TMP/sopjs-bad.js"
  if node -e "$sop_parse" "$TMP/sopjs-bad.js" >/dev/null 2>&1; then
    ng "煙測放行了 import.meta（守門失效）"
  else
    ok "煙測能抓 module-only 語法（import.meta → 紅）"
  fi
else
  echo "  （無 node → 跳過。形態2 是 opt-in，缺 node 不算失敗；CI 三平台都有 node 會補跑）"
fi

echo ""
echo "═══ 自检結果：$pass 通過 / $fail 失敗 ═══"
if [[ $fail -eq 0 ]]; then echo "✓ 本機 Bash 工具工作正常"; exit 0
else echo "✗ 有失敗項，請檢查上面 ✗ 條目"; exit 1; fi
