# 評測報告：final

- 執行時間：2026-10-21 13:02:20　|　輸出目錄：`/Users/remote/.pland/eval_runs/final-release-20261021-124204`
- 程式版本：`44fa24a`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`release`
- 測試集說明：Final suite: 8 harder, multi-step tasks, each completable by a capable agent in roughly 40 steps / 10 minutes: a tokenizer+parser project with hidden tests and a CLI, a data pipeline that is re-run on unseen data, a debugging task spread over four modules, a git release workflow (branch, --no-ff merge, annotated tag, push to a local bare remote), a live-data research report verified against the source API at check time, an under-specified export that needs a clarification round-trip, and two team tasks — one with dependent subtasks (parser → stats → CLI → tests/docs) and one combining web research with coding.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 8（8） |
| **整體目標完成率**（Goal Completion Rate） | **100.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **100.0%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 8 / 0 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 1182.7s / 147.8s / 81.8s / 457.7s / 457.7s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 303 / 6,137,922（95.5%）/ 235,433 |
| 估算花費 | $0.4009 |
| HITL 請求 / 委派次數 | 60 / 9 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 100.0% | 100.0% | 137.6s |
| files | 1 | 100.0% | 100.0% | 104.2s |
| git | 1 | 100.0% | 100.0% | 28.6s |
| hitl | 1 | 100.0% | 100.0% | 59.4s |
| team | 2 | 100.0% | 100.0% | 346.9s |
| web | 1 | 100.0% | 100.0% | 21.6s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 100.0% | 100.0% | 81.5s |
| team | 2 | 100.0% | 100.0% | 346.9s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `final-calc-evaluator` | coding/single | 成功 | 6/6 | 246.56s | 21 | 22(0) | 0 | 0 | 0 |
| 2 | `final-data-pipeline` | files/single | 成功 | 5/5 | 104.2s | 19 | 18(1) | 8 | 0 | 0 |
| 3 | `final-debug-invoicing` | coding/single | 成功 | 4/4 | 28.55s | 10 | 12(0) | 0 | 0 | 1 |
| 4 | `final-git-release` | git/single | 成功 | 7/7 | 28.65s | 18 | 19(0) | 7 | 0 | 0 |
| 5 | `final-research-python-support` | web/single | 成功 | 5/5 | 21.6s | 11 | 10(0) | 0 | 0 | 0 |
| 6 | `final-hitl-crm-export` | hitl/single | 成功 | 3/3 | 59.43s | 15 | 15(1) | 3 | 0 | 3 |
| 7 | `final-team-logkit` | team/team | 成功 | 8/8 | 457.69s | 145 | 162(0) | 37 | 6 | 12 |
| 8 | `final-team-deps-audit` | team/team | 成功 | 5/5 | 236.05s | 64 | 69(2) | 5 | 3 | 8 |

## 失敗模式

無。

## 記憶與經驗演化

- 取用了過往經驗的任務：4 個，目標完成率 100.0%；未取用的任務：4 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `final-calc-evaluator` | @default | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `final-data-pipeline` | @default | 2/0 → 2/0 | 1 → 2（2/0/0） | 1 | 1 | 0 |
| `final-debug-invoicing` | @default | 2/0 → 2/0 | 2 → 3（3/0/0） | 1 | 1 | 1 |
| `final-git-release` | @default | 2/0 → 3/0 | 3 → 4（4/0/0） | 1 | 1 | 0 |
| `final-research-python-support` | @default | 3/0 → 3/0 | 4 → 5（5/0/0） | 1 | 1 | 0 |
| `final-hitl-crm-export` | @default | 3/0 → 4/0 | 5 → 6（6/0/0） | 1 | 1 | 3 |
| `final-team-logkit` | @architect | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `final-team-logkit` | @coder | 0/0 → 1/0 | 0 → 4（4/0/0） | 0 | 4 | 9 |
| `final-team-logkit` | @tester | 0/0 → 1/0 | 0 → 3（3/0/0） | 0 | 3 | 3 |
| `final-team-deps-audit` | @lead | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `final-team-deps-audit` | @researcher | 0/0 → 1/0 | 0 → 2（2/0/0） | 0 | 2 | 3 |
| `final-team-deps-audit` | @coder | 1/0 → 1/0 | 4 → 5（5/0/0） | 0 | 1 | 5 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
