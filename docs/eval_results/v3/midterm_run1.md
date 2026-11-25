# 評測報告：midterm

- 執行時間：2026-10-21 10:52:06　|　輸出目錄：`/Users/remote/.pland/eval_runs/midterm-v3-20261021-104648`
- 程式版本：`092349d`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`v3`
- 測試集說明：Midterm suite: 15 tasks that cover every required capability at least once — file processing with computed values, coding with hidden tests, debugging, web fetch/search (verified live at check time), git commits and a push to a local bare remote, HITL clarification and approval (approved and denied), cross-session memory reuse (task 11 states a standing preference, task 15 relies on it without restating it) and three team tasks in group rooms with real delegation. Run in file order; tasks 11 and 15 must stay in the same suite run.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 15（15） |
| **整體目標完成率**（Goal Completion Rate） | **100.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **100.0%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 15 / 0 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 314.5s / 21.0s / 10.6s / 67.7s / 89.7s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 184 / 1,223,945（88.2%）/ 44,267 |
| 估算花費 | $0.1031 |
| HITL 請求 / 委派次數 | 7 / 6 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 100.0% | 100.0% | 11.9s |
| files | 1 | 100.0% | 100.0% | 10.6s |
| git | 2 | 100.0% | 100.0% | 12.1s |
| hitl | 3 | 100.0% | 100.0% | 8.6s |
| memory | 2 | 100.0% | 100.0% | 11.2s |
| team | 3 | 100.0% | 100.0% | 64.2s |
| web | 2 | 100.0% | 100.0% | 7.7s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 12 | 100.0% | 100.0% | 10.2s |
| team | 3 | 100.0% | 100.0% | 64.2s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `mid-files-sales-report` | files/single | 成功 | 4/4 | 10.61s | 7 | 5(0) | 0 | 0 | 0 |
| 2 | `mid-coding-roman` | coding/single | 成功 | 4/4 | 12.15s | 5 | 4(0) | 0 | 0 | 0 |
| 3 | `mid-debug-stats` | coding/single | 成功 | 3/3 | 11.75s | 7 | 8(0) | 0 | 0 | 0 |
| 4 | `mid-web-example-title` | web/single | 成功 | 2/2 | 9.44s | 6 | 4(0) | 0 | 0 | 0 |
| 5 | `mid-web-pypi-versions` | web/single | 成功 | 2/2 | 5.86s | 4 | 2(0) | 0 | 0 | 0 |
| 6 | `mid-git-textutils` | git/single | 成功 | 6/6 | 15.42s | 10 | 10(0) | 0 | 0 | 0 |
| 7 | `mid-git-push-bare` | git/single | 成功 | 6/6 | 8.74s | 6 | 4(0) | 1 | 0 | 0 |
| 8 | `mid-hitl-clarify-temps` | hitl/single | 成功 | 2/2 | 9.95s | 7 | 5(0) | 1 | 0 | 1 |
| 9 | `mid-hitl-approve-delete` | hitl/single | 成功 | 4/4 | 6.99s | 5 | 3(0) | 1 | 0 | 2 |
| 10 | `mid-hitl-deny-delete` | hitl/single | 成功 | 4/4 | 8.79s | 6 | 4(1) | 1 | 0 | 0 |
| 11 | `mid-memory-pref-set` | memory/single | 成功 | 4/4 | 9.6s | 6 | 5(0) | 0 | 0 | 1 |
| 12 | `mid-team-textkit` | team/team | 成功 | 6/6 | 67.7s | 40 | 37(0) | 3 | 2 | 2 |
| 13 | `mid-team-http-clients` | team/team | 成功 | 6/6 | 35.07s | 18 | 14(1) | 0 | 1 | 1 |
| 14 | `mid-team-payroll` | team/team | 成功 | 6/6 | 89.71s | 49 | 45(6) | 0 | 3 | 2 |
| 15 | `mid-memory-pref-recall` | memory/single | 成功 | 3/3 | 12.75s | 8 | 6(0) | 0 | 0 | 2 |

## 失敗模式

無。

## 記憶與經驗演化

- 取用了過往經驗的任務：7 個，目標完成率 100.0%；未取用的任務：8 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `mid-files-sales-report` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-coding-roman` | @default | 0/0 → 0/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-debug-stats` | @default | 0/0 → 0/0 | 2 → 3（3/0/0） | 0 | 1 | 0 |
| `mid-web-example-title` | @default | 0/0 → 0/0 | 3 → 4（4/0/0） | 0 | 1 | 0 |
| `mid-web-pypi-versions` | @default | 0/0 → 0/0 | 4 → 5（5/0/0） | 0 | 1 | 0 |
| `mid-git-textutils` | @default | 0/0 → 0/0 | 5 → 6（6/0/0） | 0 | 1 | 0 |
| `mid-git-push-bare` | @default | 0/0 → 0/0 | 6 → 7（7/0/0） | 0 | 1 | 0 |
| `mid-hitl-clarify-temps` | @default | 0/0 → 1/0 | 7 → 8（8/0/0） | 0 | 1 | 1 |
| `mid-hitl-approve-delete` | @default | 1/0 → 1/0 | 8 → 9（9/0/0） | 0 | 1 | 2 |
| `mid-hitl-deny-delete` | @default | 1/0 → 1/0 | 9 → 10（10/0/0） | 0 | 1 | 0 |
| `mid-memory-pref-set` | @default | 1/0 → 2/1 | 10 → 11（11/0/0） | 0 | 1 | 1 |
| `mid-team-textkit` | @planner | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @coder | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-textkit` | @tester | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-http-clients` | @writer | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-http-clients` | @researcher | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-payroll` | @planner | 1/0 → 2/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @analyst | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-payroll` | @reviewer | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-memory-pref-recall` | @default | 2/1 → 2/1 | 11 → 12（12/0/0） | 0 | 1 | 2 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
