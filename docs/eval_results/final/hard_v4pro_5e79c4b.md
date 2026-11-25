# 評測報告：hard

- 執行時間：2026-10-21 11:55:53　|　輸出目錄：`/Users/remote/.pland/eval_runs/hard-v4pro-20261021-113232`
- 程式版本：`5e79c4b`　|　模型：`deepseek-v4-pro`
- 設定：backend=`local`、memory=`on`、passes=1、model=`deepseek-v4-pro`、label=`v4pro`
- 測試集說明：Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF, whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications and an approved push, a cross-agent task where the needed price list lives only in another bot's private workspace, and a git merge with textual and semantic conflicts resolved by stated rules.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 8（8） |
| **整體目標完成率**（Goal Completion Rate） | **62.5%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **91.3%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 5 / 2 / 0 / 1 / 0 |
| 致命崩潰率 | 12.5% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 1362.7s / 170.3s / 54.8s / 968.3s / 968.3s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 223 / 4,190,812（92.5%）/ 205,719 |
| 估算花費 | $1.3985 |
| HITL 請求 / 委派次數 | 4 / 5 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 50.0% | 91.7% | 65.4s |
| files | 1 | 0.0% | 40.0% | 118.7s |
| git | 1 | 100.0% | 100.0% | 42.1s |
| hitl | 1 | 100.0% | 100.0% | 35.0s |
| team | 2 | 50.0% | 100.0% | 509.4s |
| web | 1 | 100.0% | 100.0% | 17.3s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 66.7% | 87.9% | 57.3s |
| team | 2 | 50.0% | 100.0% | 509.4s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hard-ttl-lru-cache` | coding/single | 部分完成 | 7/8 | 59.04s | 15 | 15(0) | 0 | 0 | 0 |
| 2 | `hard-debug-splitbill` | coding/single | 成功 | 4/4 | 71.73s | 26 | 46(0) | 0 | 0 | 1 |
| 3 | `hard-data-cleaning-shipments` | files/single | 部分完成 | 2/5 | 118.69s | 34 | 32(1) | 0 | 0 | 0 |
| 4 | `hard-research-django-matrix` | web/single | 成功 | 4/4 | 17.29s | 7 | 6(0) | 0 | 0 | 0 |
| 5 | `hard-team-semver-review` | team/team | 崩潰 | 9/9 | 968.34s | 83 | 81(16) | 1 | 5 | 4 |
| 6 | `hard-hitl-payout-run` | hitl/single | 成功 | 6/6 | 35.03s | 15 | 16(0) | 3 | 0 | 0 |
| 7 | `hard-team-private-pricing` | team/team | 成功 | 4/4 | 50.47s | 21 | 24(1) | 0 | 0 | 1 |
| 8 | `hard-git-merge-conflict` | git/single | 成功 | 6/6 | 42.11s | 22 | 20(0) | 0 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 2 |
| crash: stream from deepseek broke mid-response: peer closed connection without sending complete message body (incomplete chunke | 1 |

- `hard-ttl-lru-cache`（部分完成，wrong or incomplete result）
  - ✗ `hidden-callbacks`：python check failed: ASSERTION FAILED: callbacks must run after the operation has finished: [('a', 'capacity', 4, ['b', 'c', 'd']), ('b', 'capacity', 3, ['c', 'd'])]
- `hard-data-cleaning-shipments`（部分完成，wrong or incomplete result）
  - ✗ `shipments-exact`：python check failed: ASSERTION FAILED: shipments.csv: 18 data rows (expected 15); ['EU10010', '2026-09-26', 'Eva Novak', 'AT', '125.000'] != expected ['EU10011', '2026-09-27', 'Tom Baker', 'GB', '1000.250']; ['EU10011', 
  - ✗ `rejects-exact`：python check failed: ASSERTION FAILED: rejects.csv: 20 data rows (expected 23); ['eu_shipments.csv', '15', 'bad_date'] != expected ['eu_shipments.csv', '13', 'bad_weight']; ['eu_shipments.csv', '16', 'unknown_country'] !
  - ✗ `summary-exact`：python check failed: ASSERTION FAILED: summary.json valid = 18, expected 15
- `hard-team-semver-review`（崩潰，crash: stream from deepseek broke mid-response: peer closed connection without sending complete message body (incomplete chunke）
  - 錯誤：stream from deepseek broke mid-response: peer closed connection without sending complete message body (incomplete chunked read)

## 記憶與經驗演化

- 取用了過往經驗的任務：3 個，目標完成率 66.7%；未取用的任務：5 個，目標完成率 60.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `hard-ttl-lru-cache` | @default | 0/0 → 0/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `hard-debug-splitbill` | @default | 0/0 → 0/0 | 1 → 2（1/1/0） | 0 | 1 | 1 |
| `hard-data-cleaning-shipments` | @default | 0/0 → 0/0 | 2 → 3（1/2/0） | 0 | 1 | 0 |
| `hard-research-django-matrix` | @default | 0/0 → 0/0 | 3 → 4（2/2/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @lead | 0/0 → 1/0 | 0 → 1（0/0/1） | 0 | 1 | 0 |
| `hard-team-semver-review` | @implementer | 0/0 → 0/0 | 0 → 2（0/0/2） | 0 | 2 | 1 |
| `hard-team-semver-review` | @reviewer | 0/0 → 1/0 | 0 → 3（0/0/3） | 0 | 3 | 3 |
| `hard-hitl-payout-run` | @default | 0/0 → 0/0 | 4 → 5（3/2/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @billing | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @catalog | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `hard-git-merge-conflict` | @default | 0/0 → 0/0 | 5 → 6（4/2/0） | 0 | 1 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
