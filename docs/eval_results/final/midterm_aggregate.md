# 重複執行統計：midterm（正式，3 次）（3 次）

| 指標 | 平均 ± 標準差 |
|---|---|
| 整體目標完成率（%） | 95.5 ± 3.9 |
| 子任務完成率（%） | 97.3 ± 3.4 |
| 總執行時間（s） | 254.0 ± 107.9 |
| 每任務平均時間（s） | 16.9 ± 7.2 |
| 模型調用 | 170.0 ± 46.8 |
| 估算花費（美分） | 11.6 ± 6.3 |
| 快取命中率（%） | 85.9 ± 2.6 |

使用的運行：`midterm-official-r1-20261021-112927`（8b7bbf5-dirty）、`midterm-official-r2-20261021-113317`（5e79c4b）、`midterm-official-r3-20261021-113819`（29c1225）

## 逐任務成功次數

| 任務 | 成功 | 平均時間 | 失敗模式 |
|---|---|---|---|
| `mid-files-sales-report` | 3/3 | 7.8 ± 1.2s | — |
| `mid-coding-roman` | 3/3 | 8.0 ± 2.1s | — |
| `mid-debug-stats` | 3/3 | 7.0 ± 0.5s | — |
| `mid-web-example-title` | 3/3 | 7.4 ± 0.4s | — |
| `mid-web-pypi-versions` | 3/3 | 4.2 ± 0.8s | — |
| `mid-git-textutils` | 3/3 | 12.2 ± 1.4s | — |
| `mid-git-push-bare` | 3/3 | 9.3 ± 1.8s | — |
| `mid-hitl-clarify-temps` | 3/3 | 7.4 ± 0.9s | — |
| `mid-hitl-approve-delete` | 3/3 | 5.8 ± 0.8s | — |
| `mid-hitl-deny-delete` | 3/3 | 5.4 ± 0.4s | — |
| `mid-memory-pref-set` | 3/3 | 7.8 ± 1.0s | — |
| `mid-team-textkit` | 2/3 | 102.5 ± 112.3s | no real delegation / task tracking |
| `mid-team-http-clients` | 2/3 | 24.8 ± 5.3s | no real delegation / task tracking |
| `mid-team-payroll` | 3/3 | 37.4 ± 0.2s | — |
| `mid-memory-pref-recall` | 3/3 | 7.0 ± 0.8s | — |
