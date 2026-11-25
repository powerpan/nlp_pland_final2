# 評測報告：memory_evolution

- 執行時間：2026-10-21 11:33:29　|　輸出目錄：`/Users/remote/.pland/eval_runs/memory_evolution-official-mem-off-20261021-113158`
- 程式版本：`8b7bbf5`（含未提交的 hard 測試集檔案，程式碼相同）　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`off`、passes=1、label=`official-mem-off`
- 測試集說明：Memory-evolution suite: six tasks of the same kind — compute request statistics from a web/application log and write them in an exact five-line format. Each task uses a differently formatted log (nginx with seconds, JSON lines with float ms and broken lines, CSV with unit suffixes, logfmt mixed with non-request lines, Apache with microseconds, two rotated pipe-separated files). The numbers depend on seven team conventions (exclude health checks, only 5xx are errors, strip query strings, convert to whole ms, nearest-rank p95, skip unparseable lines, tie-break) that are revealed ONLY when the agent asks in task 1. From task 2 on, the simulated user refuses to repeat them, so later tasks can only succeed if the agent kept them (memory notes, experiences, skills) and re-applies them. Compare per-field check pass rates across the six tasks and against a `--memory off` run to see the effect of memory. Run the tasks in order in one suite run (memory: carry).

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 6（6） |
| **整體目標完成率**（Goal Completion Rate） | **33.3%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **39.5%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 2 / 2 / 2 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 89.0s / 14.8s / 14.8s / 22.4s / 22.4s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 47 / 276,505（88.0%）/ 11,198 |
| 估算花費 | $0.0249 |
| HITL 請求 / 委派次數 | 10 / 0 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| memory | 6 | 33.3% | 39.5% | 14.8s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 33.3% | 39.5% | 14.8s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `memevo-01` | memory/single | 成功 | 7/7 | 9.91s | 6 | 5(0) | 1 | 0 | 0 |
| 2 | `memevo-02` | memory/single | 部分完成 | 1/6 | 16.47s | 10 | 9(0) | 1 | 0 | 0 |
| 3 | `memevo-03` | memory/single | 失敗 | 0/6 | 13.46s | 6 | 5(0) | 2 | 0 | 0 |
| 4 | `memevo-04` | memory/single | 成功 | 6/6 | 22.39s | 10 | 10(0) | 2 | 0 | 0 |
| 5 | `memevo-05` | memory/single | 部分完成 | 1/6 | 16.06s | 9 | 9(0) | 2 | 0 | 0 |
| 6 | `memevo-06` | memory/single | 失敗 | 0/7 | 10.73s | 6 | 5(0) | 2 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 3 |
| memory not saved / not reused | 1 |

- `memevo-02`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '58', expected 53
  - ✗ `errors`：python check failed: ASSERTION FAILED: errors: got '7', expected 3
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 12.07%, expected 5.66%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2143', expected 861
- `memevo-03`（失敗，wrong or incomplete result）
  - ✗ `format`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmp3s9okutc/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `requests`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpq0cagp73/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `errors`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpcallxx3d/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `error-rate`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmp7tezw8ai/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
- `memevo-05`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '56', expected 51
  - ✗ `errors`：python check failed: ASSERTION FAILED: errors: got '11', expected 4
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 19.64%, expected 7.84%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2133', expected 900
- `memevo-06`（失敗，memory not saved / not reused）
  - ✗ `format`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpqmrg2rrs/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `requests`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpbzfn40_s/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `errors`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpvmpm5iu7/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `error-rate`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpag4y5o4h/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line

## 記憶與經驗演化

- 取用了過往經驗的任務：0 個，目標完成率 —；未取用的任務：6 個，目標完成率 33.3%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `memevo-01` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-02` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-03` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-04` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-05` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-06` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
