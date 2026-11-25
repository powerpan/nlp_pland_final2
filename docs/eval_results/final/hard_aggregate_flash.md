# 重複執行統計：hard（4 次）

| 指標 | 平均 ± 標準差 |
|---|---|
| 整體目標完成率（%） | 65.6 ± 6.2 |
| 子任務完成率（%） | 87.5 ± 6.9 |
| 總執行時間（s） | 1693.4 ± 1253.6 |
| 每任務平均時間（s） | 211.7 ± 156.7 |
| 模型調用 | 281.8 ± 24.0 |
| 估算花費（美分） | 65.4 ± 31.5 |
| 快取命中率（%） | 93.1 ± 1.9 |

使用的運行：`hard-official-r1-20261021-113232`（5e79c4b）、`hard-official-r2-20261021-113232`（5e79c4b）、`hard-final-r1-20261021-120824`（87f9e2b）、`hard-final-r2-20261021-120824`（87f9e2b）

## 逐任務成功次數

| 任務 | 成功 | 平均時間 | 失敗模式 |
|---|---|---|---|
| `hard-ttl-lru-cache` | 3/4 | 141.8 ± 107.7s | max_iterations |
| `hard-debug-splitbill` | 4/4 | 39.9 ± 17.9s | — |
| `hard-data-cleaning-shipments` | 1/4 | 217.8 ± 194.1s | wrong or incomplete result |
| `hard-research-django-matrix` | 4/4 | 12.4 ± 2.4s | — |
| `hard-team-semver-review` | 1/4 | 693.9 ± 325.7s | crash: stream from deepseek broke mid-response: peer closed connection without sending complete message body (incomplete chunke; no real delegation / task tracking |
| `hard-hitl-payout-run` | 4/4 | 26.3 ± 15.0s | — |
| `hard-team-private-pricing` | 1/4 | 541.5 ± 899.3s | timeout; wrong or incomplete result |
| `hard-git-merge-conflict` | 3/4 | 19.8 ± 5.9s | wrong or incomplete result |
