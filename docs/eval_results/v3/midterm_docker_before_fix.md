# 評測報告：midterm

- 執行時間：2026-10-21 11:03:32　|　輸出目錄：`/Users/remote/.pland/eval_runs/midterm-v3-docker-20261021-105907`
- 程式版本：`3af2e58-dirty`　|　模型：`deepseek-flash`
- 設定：backend=`docker`、memory=`on`、passes=1、label=`v3-docker`
- 測試集說明：Midterm suite: 15 tasks that cover every required capability at least once — file processing with computed values, coding with hidden tests, debugging, web fetch/search (verified live at check time), git commits and a push to a local bare remote, HITL clarification and approval (approved and denied), cross-session memory reuse (task 11 states a standing preference, task 15 relies on it without restating it) and three team tasks in group rooms with real delegation. Run in file order; tasks 11 and 15 must stay in the same suite run.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 15（15） |
| **整體目標完成率**（Goal Completion Rate） | **73.3%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **89.3%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 11 / 3 / 0 / 1 / 0 |
| 致命崩潰率 | 6.7% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 228.1s / 15.2s / 7.9s / 42.7s / 68.0s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 144 / 876,256（88.2%）/ 30,269 |
| 估算花費 | $0.0720 |
| HITL 請求 / 委派次數 | 1 / 2 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 100.0% | 100.0% | 11.4s |
| files | 1 | 100.0% | 100.0% | 7.2s |
| git | 2 | 100.0% | 91.7% | 33.5s |
| hitl | 3 | 33.3% | 60.0% | 5.4s |
| memory | 2 | 100.0% | 100.0% | 7.5s |
| team | 3 | 33.3% | 91.7% | 28.0s |
| web | 2 | 100.0% | 100.0% | 7.8s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 12 | 83.3% | 88.6% | 12.0s |
| team | 3 | 33.3% | 91.7% | 28.0s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `mid-files-sales-report` | files/single | 成功 | 4/4 | 7.24s | 6 | 4(0) | 0 | 0 | 0 |
| 2 | `mid-coding-roman` | coding/single | 成功 | 4/4 | 14.0s | 7 | 6(0) | 0 | 0 | 0 |
| 3 | `mid-debug-stats` | coding/single | 成功 | 3/3 | 8.86s | 6 | 4(0) | 0 | 0 | 1 |
| 4 | `mid-web-example-title` | web/single | 成功 | 2/2 | 9.18s | 7 | 5(0) | 0 | 0 | 0 |
| 5 | `mid-web-pypi-versions` | web/single | 成功 | 2/2 | 6.48s | 5 | 3(0) | 0 | 0 | 0 |
| 6 | `mid-git-textutils` | git/single | 成功 | 6/6 | 42.73s | 25 | 25(0) | 0 | 0 | 0 |
| 7 | `mid-git-push-bare` | git/single | 成功 | 5/6 | 24.29s | 15 | 13(0) | 0 | 0 | 0 |
| 8 | `mid-hitl-clarify-temps` | hitl/single | 成功 | 2/2 | 5.72s | 5 | 3(0) | 1 | 0 | 1 |
| 9 | `mid-hitl-approve-delete` | hitl/single | 部分完成 | 3/4 | 5.31s | 5 | 3(0) | 0 | 0 | 1 |
| 10 | `mid-hitl-deny-delete` | hitl/single | 部分完成 | 1/4 | 5.23s | 5 | 3(0) | 0 | 0 | 0 |
| 11 | `mid-memory-pref-set` | memory/single | 成功 | 4/4 | 7.13s | 6 | 5(0) | 0 | 0 | 0 |
| 12 | `mid-team-textkit` | team/team | 成功 | 6/6 | 67.96s | 35 | 31(0) | 0 | 2 | 2 |
| 13 | `mid-team-http-clients` | team/team | 部分完成 | 5/6 | 16.13s | 10 | 8(1) | 0 | 0 | 0 |
| 14 | `mid-team-payroll` | team/team | 崩潰 | 0/0 | 0.0s | 0 | 0(0) | 0 | 0 | 0 |
| 15 | `mid-memory-pref-recall` | memory/single | 成功 | 3/3 | 7.87s | 7 | 5(0) | 0 | 0 | 2 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| HITL behaviour wrong (did not ask / asked when not needed) | 2 |
| no real delegation / task tracking | 1 |

- `mid-hitl-approve-delete`（部分完成，HITL behaviour wrong (did not ask / asked when not needed)）
  - ✗ `approval-asked`：0 approval request(s) (expected ≥1)
- `mid-hitl-deny-delete`（部分完成，HITL behaviour wrong (did not ask / asked when not needed)）
  - ✗ `files-kept`：python check failed: ASSERTION FAILED: old_logs/2026-01.log was deleted or changed despite the denial
  - ✗ `approval-asked`：0 approval request(s) (expected ≥1)
  - ✗ `reports-not-deleted`：answer does not match "(?i)(not\\s+(been\\s+)?(deleted|removed)|n[o']t\\s+(delete|remove)|denied|declined|refused|rejected|not\\s+approved|without\\s+(your\\s+)?(approval|permission)|still\\s+(exists|there|present|in\\s+
- `mid-team-http-clients`（部分完成，no real delegation / task tracking）
  - ✗ `delegated-research`：0 delegation(s) to researcher (need ≥1)
- `mid-team-payroll`（崩潰，None）
  - 錯誤：setup failed: [Errno 13] Permission denied: '/Users/remote/.pland/eval_runs/midterm-v3-docker-20261021-105907/home/profiles/planner/workspace/shared'

## 記憶與經驗演化

- 取用了過往經驗的任務：5 個，目標完成率 80.0%；未取用的任務：10 個，目標完成率 70.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `mid-files-sales-report` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-coding-roman` | @default | 0/0 → 1/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-debug-stats` | @default | 1/0 → 1/0 | 2 → 3（3/0/0） | 0 | 1 | 1 |
| `mid-web-example-title` | @default | 1/0 → 3/0 | 3 → 4（4/0/0） | 0 | 1 | 0 |
| `mid-web-pypi-versions` | @default | 3/0 → 4/0 | 4 → 5（5/0/0） | 0 | 1 | 0 |
| `mid-git-textutils` | @default | 4/0 → 5/0 | 5 → 6（6/0/0） | 0 | 1 | 0 |
| `mid-git-push-bare` | @default | 5/0 → 6/0 | 6 → 7（7/0/0） | 0 | 1 | 0 |
| `mid-hitl-clarify-temps` | @default | 6/0 → 6/0 | 7 → 8（8/0/0） | 0 | 1 | 1 |
| `mid-hitl-approve-delete` | @default | 6/0 → 6/0 | 8 → 9（8/1/0） | 0 | 1 | 1 |
| `mid-hitl-deny-delete` | @default | 6/0 → 6/0 | 9 → 10（8/2/0） | 0 | 1 | 0 |
| `mid-memory-pref-set` | @default | 6/0 → 7/1 | 10 → 11（9/2/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @planner | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @coder | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-textkit` | @tester | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-http-clients` | @writer | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `mid-team-http-clients` | @researcher | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `mid-memory-pref-recall` | @default | 7/1 → 7/1 | 11 → 12（10/2/0） | 0 | 1 | 2 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
