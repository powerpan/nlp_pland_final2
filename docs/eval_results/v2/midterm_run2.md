# 評測報告：midterm

- 執行時間：2026-10-21 10:44:40　|　輸出目錄：`/Users/remote/.pland/eval_runs/midterm-v2-r2-20261021-104029`
- 程式版本：`e60d063`（執行期間載入的版本）　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`v2-r2`
- 測試集說明：Midterm suite: 15 tasks that cover every required capability at least once — file processing with computed values, coding with hidden tests, debugging, web fetch/search (verified live at check time), git commits and a push to a local bare remote, HITL clarification and approval (approved and denied), cross-session memory reuse (task 11 states a standing preference, task 15 relies on it without restating it) and three team tasks in group rooms with real delegation. Run in file order; tasks 11 and 15 must stay in the same suite run.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 15（15） |
| **整體目標完成率**（Goal Completion Rate） | **86.7%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **96.8%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 13 / 2 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 247.1s / 16.5s / 10.1s / 56.0s / 58.8s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 148 / 734,639（78.5%）/ 33,958 |
| 估算花費 | $0.0915 |
| HITL 請求 / 委派次數 | 8 / 5 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 50.0% | 85.7% | 10.9s |
| files | 1 | 100.0% | 100.0% | 9.3s |
| git | 2 | 100.0% | 100.0% | 12.7s |
| hitl | 3 | 100.0% | 100.0% | 8.5s |
| memory | 2 | 100.0% | 100.0% | 7.8s |
| team | 3 | 66.7% | 94.4% | 44.0s |
| web | 2 | 100.0% | 100.0% | 8.7s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 12 | 91.7% | 97.7% | 9.6s |
| team | 3 | 66.7% | 94.4% | 44.0s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `mid-files-sales-report` | files/single | 成功 | 4/4 | 9.26s | 6 | 4(0) | 0 | 0 | 0 |
| 2 | `mid-coding-roman` | coding/single | 成功 | 4/4 | 11.63s | 5 | 4(0) | 0 | 0 | 0 |
| 3 | `mid-debug-stats` | coding/single | 部分完成 | 2/3 | 10.26s | 7 | 8(0) | 0 | 0 | 0 |
| 4 | `mid-web-example-title` | web/single | 成功 | 2/2 | 11.96s | 6 | 4(0) | 0 | 0 | 0 |
| 5 | `mid-web-pypi-versions` | web/single | 成功 | 2/2 | 5.37s | 4 | 2(0) | 0 | 0 | 0 |
| 6 | `mid-git-textutils` | git/single | 成功 | 6/6 | 16.28s | 10 | 10(0) | 0 | 0 | 0 |
| 7 | `mid-git-push-bare` | git/single | 成功 | 6/6 | 9.18s | 6 | 4(0) | 1 | 0 | 0 |
| 8 | `mid-hitl-clarify-temps` | hitl/single | 成功 | 2/2 | 10.11s | 7 | 5(0) | 1 | 0 | 1 |
| 9 | `mid-hitl-approve-delete` | hitl/single | 成功 | 4/4 | 8.57s | 7 | 5(0) | 1 | 0 | 0 |
| 10 | `mid-hitl-deny-delete` | hitl/single | 成功 | 4/4 | 6.82s | 5 | 3(1) | 1 | 0 | 1 |
| 11 | `mid-memory-pref-set` | memory/single | 成功 | 4/4 | 8.08s | 6 | 5(0) | 0 | 0 | 0 |
| 12 | `mid-team-textkit` | team/team | 成功 | 6/6 | 56.03s | 31 | 28(0) | 4 | 2 | 2 |
| 13 | `mid-team-http-clients` | team/team | 部分完成 | 5/6 | 17.2s | 9 | 8(1) | 0 | 0 | 0 |
| 14 | `mid-team-payroll` | team/team | 成功 | 6/6 | 58.81s | 33 | 28(0) | 0 | 3 | 0 |
| 15 | `mid-memory-pref-recall` | memory/single | 成功 | 3/3 | 7.55s | 6 | 4(0) | 0 | 0 | 2 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 1 |
| no real delegation / task tracking | 1 |

- `mid-debug-stats`（部分完成，wrong or incomplete result）
  - ✗ `hidden-behaviour`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpnnp3fy2f/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
- `mid-team-http-clients`（部分完成，no real delegation / task tracking）
  - ✗ `delegated-research`：0 delegation(s) to researcher (need ≥1)

## 記憶與經驗演化

- 取用了過往經驗的任務：4 個，目標完成率 100.0%；未取用的任務：11 個，目標完成率 81.8%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `mid-files-sales-report` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-coding-roman` | @default | 0/0 → 0/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-debug-stats` | @default | 0/0 → 0/0 | 2 → 3（2/1/0） | 0 | 1 | 0 |
| `mid-web-example-title` | @default | 0/0 → 1/0 | 3 → 4（3/1/0） | 0 | 1 | 0 |
| `mid-web-pypi-versions` | @default | 1/0 → 1/0 | 4 → 5（4/1/0） | 0 | 1 | 0 |
| `mid-git-textutils` | @default | 1/0 → 1/0 | 5 → 6（5/1/0） | 0 | 1 | 0 |
| `mid-git-push-bare` | @default | 1/0 → 2/0 | 6 → 7（6/1/0） | 0 | 1 | 0 |
| `mid-hitl-clarify-temps` | @default | 2/0 → 3/0 | 7 → 8（7/1/0） | 0 | 1 | 1 |
| `mid-hitl-approve-delete` | @default | 3/0 → 3/0 | 8 → 9（8/1/0） | 0 | 1 | 0 |
| `mid-hitl-deny-delete` | @default | 3/0 → 4/0 | 9 → 10（9/1/0） | 0 | 1 | 1 |
| `mid-memory-pref-set` | @default | 4/0 → 5/1 | 10 → 11（10/1/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @planner | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @coder | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-textkit` | @tester | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-http-clients` | @writer | 0/0 → 2/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `mid-team-http-clients` | @researcher | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `mid-team-payroll` | @planner | 1/0 → 1/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @analyst | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @reviewer | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-memory-pref-recall` | @default | 5/1 → 5/1 | 11 → 12（11/1/0） | 0 | 1 | 2 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
