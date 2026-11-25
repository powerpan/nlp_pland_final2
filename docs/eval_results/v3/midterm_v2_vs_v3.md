# 評測比較

| 指標 | v2 | v3 |
|---|---|---|
| 任務數 | 15 | 15 |
| 整體目標完成率 | 100.0% | 100.0% |
| 子任務完成率 | 100.0% | 100.0% |
| 成功/部分/失敗/崩潰/逾時 | 15/0/0/0/0 | 15/0/0/0/0 |
| 總執行時間 | 289.6s | 314.5s |
| 平均 / 中位數執行時間 | 19.3s / 9.9s | 21.0s / 10.6s |
| 模型調用 | 168 | 184 |
| 輸入 / 輸出 tokens | 872,401 / 40,113 | 1,223,945 / 44,267 |
| 快取命中率 | 80.2% | 88.2% |
| 估算花費 | $0.1042 | $0.1031 |
| 取用經驗的任務數 | 4 | 7 |

## 逐任務

| 任務 | v2 | v3 |
|---|---|---|
| `mid-files-sales-report` | 成功 4/4 · 9.87s · 7 calls | 成功 4/4 · 10.61s · 7 calls |
| `mid-coding-roman` | 成功 4/4 · 12.84s · 6 calls | 成功 4/4 · 12.15s · 5 calls |
| `mid-debug-stats` | 成功 3/3 · 10.3s · 7 calls | 成功 3/3 · 11.75s · 7 calls |
| `mid-web-example-title` | 成功 2/2 · 8.47s · 6 calls | 成功 2/2 · 9.44s · 6 calls |
| `mid-web-pypi-versions` | 成功 2/2 · 5.46s · 4 calls | 成功 2/2 · 5.86s · 4 calls |
| `mid-git-textutils` | 成功 6/6 · 13.94s · 9 calls | 成功 6/6 · 15.42s · 10 calls |
| `mid-git-push-bare` | 成功 6/6 · 8.85s · 6 calls | 成功 6/6 · 8.74s · 6 calls |
| `mid-hitl-clarify-temps` | 成功 2/2 · 9.05s · 6 calls | 成功 2/2 · 9.95s · 7 calls |
| `mid-hitl-approve-delete` | 成功 4/4 · 8.34s · 7 calls | 成功 4/4 · 6.99s · 5 calls |
| `mid-hitl-deny-delete` | 成功 4/4 · 7.88s · 6 calls | 成功 4/4 · 8.79s · 6 calls |
| `mid-memory-pref-set` | 成功 4/4 · 8.37s · 6 calls | 成功 4/4 · 9.6s · 6 calls |
| `mid-team-textkit` | 成功 6/6 · 52.13s · 29 calls | 成功 6/6 · 67.7s · 40 calls |
| `mid-team-http-clients` | 成功 6/6 · 57.98s · 26 calls | 成功 6/6 · 35.07s · 18 calls |
| `mid-team-payroll` | 成功 6/6 · 66.1s · 36 calls | 成功 6/6 · 89.71s · 49 calls |
| `mid-memory-pref-recall` | 成功 3/3 · 9.99s · 7 calls | 成功 3/3 · 12.75s · 8 calls |
