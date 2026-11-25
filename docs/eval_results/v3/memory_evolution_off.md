# 評測報告：memory_evolution

- 執行時間：2026-10-21 10:51:38　|　輸出目錄：`/Users/remote/.pland/eval_runs/memory_evolution-v3-mem-off-20261021-105010`
- 程式版本：`092349d-dirty`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`off`、passes=1、label=`v3-mem-off`
- 測試集說明：Memory-evolution suite: six tasks of the same kind — compute request statistics from a web/application log and write them in an exact five-line format. Each task uses a differently formatted log (nginx with seconds, JSON lines with float ms and broken lines, CSV with unit suffixes, logfmt mixed with non-request lines, Apache with microseconds, two rotated pipe-separated files). The numbers depend on seven team conventions (exclude health checks, only 5xx are errors, strip query strings, convert to whole ms, nearest-rank p95, skip unparseable lines, tie-break) that are revealed ONLY when the agent asks in task 1. From task 2 on, the simulated user refuses to repeat them, so later tasks can only succeed if the agent kept them (memory notes, experiences, skills) and re-applies them. Compare per-field check pass rates across the six tasks and against a `--memory off` run to see the effect of memory. Run the tasks in order in one suite run (memory: carry).

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 6（6） |
| **整體目標完成率**（Goal Completion Rate） | **16.7%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **34.2%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 1 / 3 / 2 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 87.5s / 14.6s / 14.6s / 21.1s / 21.1s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 46 / 256,409（89.3%）/ 12,046 |
| 估算花費 | $0.0241 |
| HITL 請求 / 委派次數 | 9 / 0 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| memory | 6 | 16.7% | 34.2% | 14.6s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 16.7% | 34.2% | 14.6s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `memevo-01` | memory/single | 成功 | 7/7 | 16.56s | 8 | 8(0) | 1 | 0 | 0 |
| 2 | `memevo-02` | memory/single | 失敗 | 0/6 | 13.74s | 8 | 7(0) | 2 | 0 | 0 |
| 3 | `memevo-03` | memory/single | 失敗 | 0/6 | 7.89s | 4 | 4(0) | 1 | 0 | 0 |
| 4 | `memevo-04` | memory/single | 部分完成 | 2/6 | 12.77s | 7 | 7(0) | 1 | 0 | 0 |
| 5 | `memevo-05` | memory/single | 部分完成 | 2/6 | 15.5s | 9 | 8(0) | 2 | 0 | 0 |
| 6 | `memevo-06` | memory/single | 部分完成 | 2/7 | 21.07s | 10 | 10(0) | 2 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 4 |
| memory not saved / not reused | 1 |

- `memevo-02`（失敗，wrong or incomplete result）
  - ✗ `format`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmp9ksj6j2j/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `requests`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmp91f2zrre/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `errors`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpvro_w7qu/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `error-rate`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpggxq4kjm/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
- `memevo-03`（失敗，wrong or incomplete result）
  - ✗ `format`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpk219uety/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `requests`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmp9yaj7hxn/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `errors`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpaqoy_1qm/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `error-rate`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmptgfa0min/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
- `memevo-04`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '54', expected 49
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 7.41%, expected 8.16%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2312', expected 1163
  - ✗ `slowest-endpoint`：python check failed: ASSERTION FAILED: slowest_endpoint: got '/healthz', expected '/api/exports/csv'
- `memevo-05`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '56', expected 51
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 7.14%, expected 7.84%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2133', expected 900
  - ✗ `slowest-endpoint`：python check failed: ASSERTION FAILED: slowest_endpoint: got '/healthz', expected '/api/analytics/daily'
- `memevo-06`（部分完成，memory not saved / not reused）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '61', expected 55
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 4.92%, expected 5.45%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2170', expected 1136
  - ✗ `slowest-endpoint`：python check failed: ASSERTION FAILED: slowest_endpoint: got '/health/ready', expected '/api/batch/import'

## 記憶與經驗演化

- 取用了過往經驗的任務：0 個，目標完成率 —；未取用的任務：6 個，目標完成率 16.7%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `memevo-01` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-02` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-03` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-04` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-05` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-06` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
