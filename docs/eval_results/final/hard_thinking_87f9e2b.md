# 評測報告：hard

- 執行時間：2026-10-21 12:33:29　|　輸出目錄：`/Users/remote/.pland/eval_runs/hard-final-thinking-20261021-120824`
- 程式版本：`87f9e2b`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`final-thinking`
- 測試集說明：Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF, whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications and an approved push, a cross-agent task where the needed price list lives only in another bot's private workspace, and a git merge with textual and semantic conflicts resolved by stated rules.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 8（8） |
| **整體目標完成率**（Goal Completion Rate） | **100.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **100.0%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 8 / 0 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 1466.7s / 183.3s / 165.2s / 395.0s / 395.0s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 289 / 8,270,787（97.0%）/ 303,973 |
| 估算花費 | $0.4861 |
| HITL 請求 / 委派次數 | 14 / 4 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 100.0% | 100.0% | 234.4s |
| files | 1 | 100.0% | 100.0% | 128.8s |
| git | 1 | 100.0% | 100.0% | 28.8s |
| hitl | 1 | 100.0% | 100.0% | 44.1s |
| team | 2 | 100.0% | 100.0% | 386.7s |
| web | 1 | 100.0% | 100.0% | 22.7s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 100.0% | 100.0% | 115.5s |
| team | 2 | 100.0% | 100.0% | 386.7s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hard-ttl-lru-cache` | coding/single | 成功 | 8/8 | 201.59s | 25 | 22(1) | 0 | 0 | 0 |
| 2 | `hard-debug-splitbill` | coding/single | 成功 | 4/4 | 267.25s | 35 | 44(0) | 0 | 0 | 1 |
| 3 | `hard-data-cleaning-shipments` | files/single | 成功 | 5/5 | 128.81s | 23 | 22(0) | 7 | 0 | 0 |
| 4 | `hard-research-django-matrix` | web/single | 成功 | 4/4 | 22.71s | 9 | 7(0) | 0 | 0 | 0 |
| 5 | `hard-team-semver-review` | team/team | 成功 | 9/9 | 378.42s | 66 | 69(0) | 1 | 2 | 0 |
| 6 | `hard-hitl-payout-run` | hitl/single | 成功 | 6/6 | 44.09s | 16 | 16(0) | 4 | 0 | 0 |
| 7 | `hard-team-private-pricing` | team/team | 成功 | 4/4 | 395.03s | 103 | 111(2) | 2 | 2 | 1 |
| 8 | `hard-git-merge-conflict` | git/single | 成功 | 6/6 | 28.83s | 12 | 21(0) | 0 | 0 | 0 |

## 失敗模式

無。

## 記憶與經驗演化

- 取用了過往經驗的任務：2 個，目標完成率 100.0%；未取用的任務：6 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `hard-ttl-lru-cache` | @default | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-debug-splitbill` | @default | 1/0 → 1/0 | 1 → 2（2/0/0） | 0 | 1 | 1 |
| `hard-data-cleaning-shipments` | @default | 1/0 → 1/0 | 2 → 3（3/0/0） | 0 | 1 | 0 |
| `hard-research-django-matrix` | @default | 1/0 → 1/0 | 3 → 4（4/0/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @lead | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @implementer | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @reviewer | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-hitl-payout-run` | @default | 1/0 → 3/0 | 4 → 5（5/0/0） | 1 | 1 | 0 |
| `hard-team-private-pricing` | @billing | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @catalog | 0/0 → 2/0 | 0 → 2（2/0/0） | 1 | 2 | 1 |
| `hard-git-merge-conflict` | @default | 3/0 → 4/0 | 5 → 6（6/0/0） | 1 | 1 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
