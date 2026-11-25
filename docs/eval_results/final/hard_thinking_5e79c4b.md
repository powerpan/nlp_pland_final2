# 評測報告：hard

- 執行時間：2026-10-21 11:53:33　|　輸出目錄：`/Users/remote/.pland/eval_runs/hard-thinking-20261021-113232`
- 程式版本：`5e79c4b`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`thinking`
- 測試集說明：Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF, whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications and an approved push, a cross-agent task where the needed price list lives only in another bot's private workspace, and a git merge with textual and semantic conflicts resolved by stated rules.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 8（8） |
| **整體目標完成率**（Goal Completion Rate） | **75.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **91.3%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 6 / 2 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 1226.5s / 153.3s / 127.3s / 379.1s / 379.1s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 232 / 5,955,515（96.7%）/ 257,187 |
| 估算花費 | $0.4023 |
| HITL 請求 / 委派次數 | 12 / 3 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 100.0% | 100.0% | 222.0s |
| files | 1 | 0.0% | 40.0% | 117.7s |
| git | 1 | 100.0% | 100.0% | 29.1s |
| hitl | 1 | 100.0% | 100.0% | 98.0s |
| team | 2 | 50.0% | 92.3% | 258.0s |
| web | 1 | 100.0% | 100.0% | 21.7s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 83.3% | 90.9% | 118.4s |
| team | 2 | 50.0% | 92.3% | 258.0s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hard-ttl-lru-cache` | coding/single | 成功 | 8/8 | 300.11s | 35 | 39(1) | 2 | 0 | 0 |
| 2 | `hard-debug-splitbill` | coding/single | 成功 | 4/4 | 143.86s | 32 | 30(1) | 1 | 0 | 0 |
| 3 | `hard-data-cleaning-shipments` | files/single | 部分完成 | 2/5 | 117.74s | 17 | 15(0) | 6 | 0 | 0 |
| 4 | `hard-research-django-matrix` | web/single | 成功 | 4/4 | 21.73s | 10 | 10(0) | 0 | 0 | 1 |
| 5 | `hard-team-semver-review` | team/team | 部分完成 | 8/9 | 379.14s | 60 | 66(1) | 0 | 2 | 0 |
| 6 | `hard-hitl-payout-run` | hitl/single | 成功 | 6/6 | 98.02s | 17 | 17(0) | 3 | 0 | 0 |
| 7 | `hard-team-private-pricing` | team/team | 成功 | 4/4 | 136.81s | 48 | 56(3) | 0 | 1 | 0 |
| 8 | `hard-git-merge-conflict` | git/single | 成功 | 6/6 | 29.05s | 13 | 20(0) | 0 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 1 |
| no real delegation / task tracking | 1 |

- `hard-data-cleaning-shipments`（部分完成，wrong or incomplete result）
  - ✗ `shipments-exact`：python check failed: ASSERTION FAILED: shipments.csv: 16 data rows (expected 15); ['EU10010', '2026-09-26', 'Eva Novak', 'AT', '125.000'] != expected ['EU10011', '2026-09-27', 'Tom Baker', 'GB', '1000.250']; ['EU10011', 
  - ✗ `rejects-exact`：python check failed: ASSERTION FAILED: rejects.csv: 22 data rows (expected 23); ['eu_shipments.csv', '15', 'bad_date'] != expected ['eu_shipments.csv', '13', 'bad_weight']; ['eu_shipments.csv', '16', 'unknown_country'] !
  - ✗ `summary-exact`：python check failed: ASSERTION FAILED: summary.json valid = 16, expected 15
- `hard-team-semver-review`（部分完成，no real delegation / task tracking）
  - ✗ `delegated-reviewer`：0 delegation(s) to reviewer (need ≥1)

## 記憶與經驗演化

- 取用了過往經驗的任務：1 個，目標完成率 100.0%；未取用的任務：7 個，目標完成率 71.4%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `hard-ttl-lru-cache` | @default | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-debug-splitbill` | @default | 2/0 → 2/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `hard-data-cleaning-shipments` | @default | 2/0 → 3/0 | 2 → 3（2/1/0） | 0 | 1 | 0 |
| `hard-research-django-matrix` | @default | 3/0 → 4/0 | 3 → 4（3/1/0） | 0 | 1 | 1 |
| `hard-team-semver-review` | @lead | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @implementer | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @reviewer | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `hard-hitl-payout-run` | @default | 4/0 → 5/0 | 4 → 5（4/1/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @billing | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @catalog | 0/0 → 3/0 | 0 → 2（2/0/0） | 0 | 2 | 0 |
| `hard-git-merge-conflict` | @default | 5/0 → 6/0 | 5 → 6（5/1/0） | 0 | 1 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
