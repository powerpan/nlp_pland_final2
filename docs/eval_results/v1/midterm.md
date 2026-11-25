# 評測報告：midterm

- 執行時間：2026-10-21 10:23:08　|　輸出目錄：`/Users/remote/.pland/eval_runs/midterm-v1-20261021-101814`
- 程式版本：v1（v2 修正之前，見 docs/EVALUATION_REPORT.md 第 7 節）　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`v1`
- 測試集說明：Midterm suite: 15 tasks that cover every required capability at least once — file processing with computed values, coding with hidden tests, debugging, web fetch/search (verified live at check time), git commits and a push to a local bare remote, HITL clarification and approval (approved and denied), cross-session memory reuse (task 11 states a standing preference, task 15 relies on it without restating it) and three team tasks in group rooms with real delegation. Run in file order; tasks 11 and 15 must stay in the same suite run.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 15（15） |
| **整體目標完成率**（Goal Completion Rate） | **86.7%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **95.2%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 13 / 1 / 1 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 290.6s / 19.4s / 9.3s / 55.8s / 65.7s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 179 / 921,883（81.8%）/ 41,165 |
| 估算花費 | $0.1041 |
| HITL 請求 / 委派次數 | 8 / 6 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 50.0% | 85.7% | 13.5s |
| files | 1 | 100.0% | 100.0% | 9.2s |
| git | 2 | 100.0% | 100.0% | 11.4s |
| hitl | 3 | 66.7% | 80.0% | 8.1s |
| memory | 2 | 100.0% | 100.0% | 9.5s |
| team | 3 | 100.0% | 100.0% | 57.2s |
| web | 2 | 100.0% | 100.0% | 8.4s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 12 | 83.3% | 93.2% | 9.9s |
| team | 3 | 100.0% | 100.0% | 57.2s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `mid-files-sales-report` | files/single | 成功 | 4/4 | 9.2s | 6 | 4(0) | 0 | 0 | 0 |
| 2 | `mid-coding-roman` | coding/single | 成功 | 4/4 | 12.1s | 5 | 4(0) | 0 | 0 | 0 |
| 3 | `mid-debug-stats` | coding/single | 部分完成 | 2/3 | 14.83s | 9 | 11(0) | 0 | 0 | 0 |
| 4 | `mid-web-example-title` | web/single | 成功 | 2/2 | 8.73s | 6 | 4(0) | 0 | 0 | 0 |
| 5 | `mid-web-pypi-versions` | web/single | 成功 | 2/2 | 8.12s | 5 | 3(0) | 0 | 0 | 0 |
| 6 | `mid-git-textutils` | git/single | 成功 | 6/6 | 14.23s | 10 | 10(0) | 0 | 0 | 0 |
| 7 | `mid-git-push-bare` | git/single | 成功 | 6/6 | 8.5s | 5 | 3(0) | 1 | 0 | 1 |
| 8 | `mid-hitl-clarify-temps` | hitl/single | 失敗 | 0/2 | 7.32s | 5 | 3(0) | 0 | 0 | 1 |
| 9 | `mid-hitl-approve-delete` | hitl/single | 成功 | 4/4 | 7.65s | 5 | 3(0) | 1 | 0 | 0 |
| 10 | `mid-hitl-deny-delete` | hitl/single | 成功 | 4/4 | 9.32s | 7 | 5(1) | 1 | 0 | 0 |
| 11 | `mid-memory-pref-set` | memory/single | 成功 | 4/4 | 10.75s | 7 | 6(0) | 0 | 0 | 0 |
| 12 | `mid-team-textkit` | team/team | 成功 | 6/6 | 55.75s | 38 | 35(0) | 5 | 2 | 2 |
| 13 | `mid-team-http-clients` | team/team | 成功 | 6/6 | 50.26s | 28 | 23(1) | 0 | 1 | 1 |
| 14 | `mid-team-payroll` | team/team | 成功 | 6/6 | 65.69s | 37 | 32(0) | 0 | 3 | 0 |
| 15 | `mid-memory-pref-recall` | memory/single | 成功 | 3/3 | 8.17s | 6 | 4(0) | 0 | 0 | 2 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 1 |
| HITL behaviour wrong (did not ask / asked when not needed) | 1 |

- `mid-debug-stats`（部分完成，wrong or incomplete result）
  - ✗ `hidden-behaviour`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpkn9wlg8t/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
- `mid-hitl-clarify-temps`（失敗，HITL behaviour wrong (did not ask / asked when not needed)）
  - ✗ `asked-unit`：0 clarify request(s) (expected ≥1)
  - ✗ `converted-values`：python check failed: ASSERTION FAILED: wrong conversions (got, expected Fahrenheit→Celsius): [(53.6, -11.1), (64.4, -7.8), (77.0, -3.9), (87.8, -0.6), (44.6, -13.9), (26.6, -19.4), (71.6, -5.6)]

## 記憶與經驗演化

- 取用了過往經驗的任務：5 個，目標完成率 80.0%；未取用的任務：10 個，目標完成率 90.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `mid-files-sales-report` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-coding-roman` | @default | 0/0 → 0/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-debug-stats` | @default | 0/0 → 0/0 | 2 → 3（2/1/0） | 0 | 1 | 0 |
| `mid-web-example-title` | @default | 0/0 → 0/0 | 3 → 4（3/1/0） | 0 | 1 | 0 |
| `mid-web-pypi-versions` | @default | 0/0 → 0/0 | 4 → 5（4/1/0） | 0 | 1 | 0 |
| `mid-git-textutils` | @default | 0/0 → 0/0 | 5 → 6（5/1/0） | 0 | 1 | 0 |
| `mid-git-push-bare` | @default | 0/0 → 0/0 | 6 → 7（6/1/0） | 0 | 1 | 1 |
| `mid-hitl-clarify-temps` | @default | 0/0 → 0/0 | 7 → 8（6/1/1） | 0 | 1 | 1 |
| `mid-hitl-approve-delete` | @default | 0/0 → 0/0 | 8 → 9（7/1/1） | 0 | 1 | 0 |
| `mid-hitl-deny-delete` | @default | 0/0 → 2/0 | 9 → 10（8/1/1） | 0 | 1 | 0 |
| `mid-memory-pref-set` | @default | 2/0 → 3/1 | 10 → 11（9/1/1） | 0 | 1 | 0 |
| `mid-team-textkit` | @planner | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @coder | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-textkit` | @tester | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-http-clients` | @writer | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-http-clients` | @researcher | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-payroll` | @planner | 1/0 → 1/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @analyst | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @reviewer | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-memory-pref-recall` | @default | 3/1 → 4/1 | 11 → 12（10/1/1） | 0 | 1 | 2 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
