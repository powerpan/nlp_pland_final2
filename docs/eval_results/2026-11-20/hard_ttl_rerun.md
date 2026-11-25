# 評測報告：hard

- 執行時間：2026-11-21 00:14:26　|　輸出目錄：`/Users/remote/.pland/eval_runs/hard-refresh-ttl-20261121-001026`
- 程式版本：`f7209f6`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`refresh-ttl`
- 測試集說明：Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF, whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications and an approved push, a cross-agent task where the needed price list lives only in another bot's private workspace, and a git merge with textual and semantic conflicts resolved by stated rules.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 1（1） |
| **整體目標完成率**（Goal Completion Rate） | **100.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **100.0%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 1 / 0 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 234.0s / 234.0s / 234.0s / 234.0s / 234.0s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 33 / 1,043,952（98.4%）/ 37,497 |
| 估算花費 | $0.0561 |
| HITL 請求 / 委派次數 | 0 / 0 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 1 | 100.0% | 100.0% | 234.0s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 1 | 100.0% | 100.0% | 234.0s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hard-ttl-lru-cache` | coding/single | 成功 | 8/8 | 233.99s | 33 | 31(0) | 0 | 0 | 0 |

## 失敗模式

無。

## 記憶與經驗演化

- 取用了過往經驗的任務：0 個，目標完成率 —；未取用的任務：1 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `hard-ttl-lru-cache` | @default | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
