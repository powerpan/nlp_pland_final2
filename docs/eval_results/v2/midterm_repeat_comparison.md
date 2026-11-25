# 評測比較

| 指標 | 第1次 | 第2次 |
|---|---|---|
| 任務數 | 15 | 15 |
| 整體目標完成率 | 100.0% | 86.7% |
| 子任務完成率 | 100.0% | 96.8% |
| 成功/部分/失敗/崩潰/逾時 | 15/0/0/0/0 | 13/2/0/0/0 |
| 總執行時間 | 289.6s | 247.1s |
| 平均 / 中位數執行時間 | 19.3s / 9.9s | 16.5s / 10.1s |
| 模型調用 | 168 | 148 |
| 輸入 / 輸出 tokens | 872,401 / 40,113 | 734,639 / 33,958 |
| 快取命中率 | 80.2% | 78.5% |
| 估算花費 | $0.1042 | $0.0915 |
| 取用經驗的任務數 | 4 | 4 |

## 逐任務

| 任務 | 第1次 | 第2次 |
|---|---|---|
| `mid-files-sales-report` | 成功 4/4 · 9.87s · 7 calls | 成功 4/4 · 9.26s · 6 calls |
| `mid-coding-roman` | 成功 4/4 · 12.84s · 6 calls | 成功 4/4 · 11.63s · 5 calls |
| `mid-debug-stats` | 成功 3/3 · 10.3s · 7 calls | 部分完成 2/3 · 10.26s · 7 calls |
| `mid-web-example-title` | 成功 2/2 · 8.47s · 6 calls | 成功 2/2 · 11.96s · 6 calls |
| `mid-web-pypi-versions` | 成功 2/2 · 5.46s · 4 calls | 成功 2/2 · 5.37s · 4 calls |
| `mid-git-textutils` | 成功 6/6 · 13.94s · 9 calls | 成功 6/6 · 16.28s · 10 calls |
| `mid-git-push-bare` | 成功 6/6 · 8.85s · 6 calls | 成功 6/6 · 9.18s · 6 calls |
| `mid-hitl-clarify-temps` | 成功 2/2 · 9.05s · 6 calls | 成功 2/2 · 10.11s · 7 calls |
| `mid-hitl-approve-delete` | 成功 4/4 · 8.34s · 7 calls | 成功 4/4 · 8.57s · 7 calls |
| `mid-hitl-deny-delete` | 成功 4/4 · 7.88s · 6 calls | 成功 4/4 · 6.82s · 5 calls |
| `mid-memory-pref-set` | 成功 4/4 · 8.37s · 6 calls | 成功 4/4 · 8.08s · 6 calls |
| `mid-team-textkit` | 成功 6/6 · 52.13s · 29 calls | 成功 6/6 · 56.03s · 31 calls |
| `mid-team-http-clients` | 成功 6/6 · 57.98s · 26 calls | 部分完成 5/6 · 17.2s · 9 calls |
| `mid-team-payroll` | 成功 6/6 · 66.1s · 36 calls | 成功 6/6 · 58.81s · 33 calls |
| `mid-memory-pref-recall` | 成功 3/3 · 9.99s · 7 calls | 成功 3/3 · 7.55s · 6 calls |
