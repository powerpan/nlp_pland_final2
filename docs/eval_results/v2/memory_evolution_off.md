# 評測報告：memory_evolution

- 執行時間：2026-10-21 10:37:01　|　輸出目錄：`/Users/remote/.pland/eval_runs/memory_evolution-v2-mem-off-20261021-103522`
- 程式版本：`e60d063`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`off`、passes=1、label=`v2-mem-off`
- 測試集說明：Memory-evolution suite: six tasks of the same kind — compute request statistics from a web/application log and write them in an exact five-line format. Each task uses a differently formatted log (nginx with seconds, JSON lines with float ms and broken lines, CSV with unit suffixes, logfmt mixed with non-request lines, Apache with microseconds, two rotated pipe-separated files). The numbers depend on seven team conventions (exclude health checks, only 5xx are errors, strip query strings, convert to whole ms, nearest-rank p95, skip unparseable lines, tie-break) that are revealed ONLY when the agent asks in task 1. From task 2 on, the simulated user refuses to repeat them, so later tasks can only succeed if the agent kept them (memory notes, experiences, skills) and re-applies them. Compare per-field check pass rates across the six tasks and against a `--memory off` run to see the effect of memory. Run the tasks in order in one suite run (memory: carry).

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 6（6） |
| **整體目標完成率**（Goal Completion Rate） | **16.7%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **31.6%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 1 / 3 / 2 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 98.0s / 16.3s / 15.0s / 25.5s / 25.5s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 50 / 287,612（90.3%）/ 14,270 |
| 估算花費 | $0.0271 |
| HITL 請求 / 委派次數 | 11 / 0 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| memory | 6 | 16.7% | 31.6% | 16.3s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 16.7% | 31.6% | 16.3s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `memevo-01` | memory/single | 成功 | 7/7 | 13.87s | 7 | 8(0) | 1 | 0 | 0 |
| 2 | `memevo-02` | memory/single | 失敗 | 0/6 | 15.98s | 8 | 7(0) | 2 | 0 | 0 |
| 3 | `memevo-03` | memory/single | 部分完成 | 1/6 | 13.94s | 9 | 8(0) | 2 | 0 | 0 |
| 4 | `memevo-04` | memory/single | 部分完成 | 2/6 | 25.48s | 11 | 11(0) | 2 | 0 | 0 |
| 5 | `memevo-05` | memory/single | 失敗 | 0/6 | 10.11s | 5 | 4(0) | 2 | 0 | 0 |
| 6 | `memevo-06` | memory/single | 部分完成 | 2/7 | 18.65s | 10 | 10(0) | 2 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 4 |
| memory not saved / not reused | 1 |

- `memevo-02`（失敗，wrong or incomplete result）
  - ✗ `format`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpie83e7c3/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `requests`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmp8ii7ym9o/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `errors`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpz7yiub1_/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `error-rate`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmptdi4jctg/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
- `memevo-03`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '56', expected 51
  - ✗ `errors`：python check failed: ASSERTION FAILED: errors: got '7', expected 3
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 12.50%, expected 5.88%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '1755', expected 604
- `memevo-04`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '54', expected 49
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 7.41%, expected 8.16%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2312', expected 1163
  - ✗ `slowest-endpoint`：python check failed: ASSERTION FAILED: slowest_endpoint: got '/healthz', expected '/api/exports/csv'
- `memevo-05`（失敗，wrong or incomplete result）
  - ✗ `format`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmp8u1e1cgg/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `requests`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmphh6nsqvm/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `errors`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpsji_1uyf/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `error-rate`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpslsi5kfx/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
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
