"""Markdown report for one suite run (Traditional Chinese, technical terms in English)."""

from __future__ import annotations

from typing import Any

OUTCOME_ZH = {"success": "成功", "partial": "部分完成", "failed": "失敗", "crashed": "崩潰", "timeout": "逾時", "unverified": "未驗證"}


def _fmt(v: Any, suffix: str = "") -> str:
    return "—" if v is None else f"{v}{suffix}"


def render_report(s: dict[str, Any], records: list[dict[str, Any]]) -> str:
    o = s["outcomes"]
    t = s["time"]
    u = s["usage"]
    opts = s.get("options") or {}
    L = [
        f"# 評測報告：{s.get('suite')}",
        "",
        f"- 執行時間：{s.get('started')}　|　輸出目錄：`{s.get('run_dir')}`",
        f"- 程式版本：`{s.get('code_version', '?')}`　|　模型：`{s.get('model', '?')}`",
        f"- 設定：backend=`{opts.get('backend')}`、memory=`{opts.get('memory')}`、passes={opts.get('passes')}"
        + (f"、model=`{opts.get('model')}`" if opts.get("model") else "")
        + (f"、thinking=`{opts.get('thinking')}`" if opts.get("thinking") is not None else "")
        + (f"、reasoning=`{opts.get('reasoning')}`" if opts.get("reasoning") else "")
        + (f"、label=`{opts.get('label')}`" if opts.get("label") else ""),
    ]
    if s.get("description"):
        L += [f"- 測試集說明：{' '.join(str(s['description']).split())}"]
    L += [
        "",
        "## 總覽",
        "",
        "| 指標 | 數值 |",
        "|---|---|",
        f"| 任務數（可驗證） | {s['tasks']}（{s['verified_tasks']}） |",
        f"| **整體目標完成率**（Goal Completion Rate） | **{_fmt(s['goal_completion_rate'], '%')}** |",
        f"| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **{_fmt(s['subtask_completion_rate'], '%')}** |",
        f"| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | {o['success']} / {o['partial']} / {o['failed']} / {o['crashed']} / {o['timeout']} |",
        f"| 致命崩潰率 | {_fmt(s['crash_rate'], '%')} |",
        f"| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | {t['total_s']}s / {_fmt(t['mean_s'], 's')} / {_fmt(t['median_s'], 's')} / {_fmt(t['p90_s'], 's')} / {_fmt(t['max_s'], 's')} |",
        f"| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | {u['calls']} / {u['prompt_tokens']:,}（{u['cache_hit_rate'] * 100:.1f}%）/ {u['completion_tokens']:,} |",
        f"| 估算花費 | ${u['cost_usd']:.4f} |",
        f"| HITL 請求 / 委派次數 | {s['hitl_requests']} / {s['delegations']} |",
        "",
        "判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；"
        "「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。",
        "",
    ]
    for title, key in (("依類別", "by_category"), ("依模式", "by_mode")):
        rows = s.get(key) or {}
        if rows:
            L += [f"## {title}", "", "| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |", "|---|---|---|---|---|"]
            for k, v in rows.items():
                L.append(f"| {k} | {v['tasks']} | {_fmt(v['goal_rate'], '%')} | {_fmt(v['subtask_rate'], '%')} | {v['mean_time_s']}s |")
            L.append("")
    if len(s.get("by_pass") or {}) > 1:
        L += ["## 多輪執行（記憶跨輪保留）", "", "| 輪次 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |", "|---|---|---|---|---|"]
        for k, v in s["by_pass"].items():
            L.append(f"| 第 {k} 輪 | {v['tasks']} | {_fmt(v['goal_rate'], '%')} | {_fmt(v['subtask_rate'], '%')} | {v['mean_time_s']}s |")
        L.append("")
    L += ["## 任務明細", "", "| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(records, 1):
        n_exp = sum(len(x.get("ids") or []) for x in r.get("experiences_retrieved") or [])
        L.append(
            f"| {i} | `{r['task_id']}`{' (p' + str(r['pass']) + ')' if r.get('pass', 1) > 1 else ''} | {r['category']}/{r['mode']} | "
            f"{OUTCOME_ZH.get(r['outcome'], r['outcome'])} | {r.get('checks_passed', 0)}/{r.get('checks_total', 0)} | "
            f"{r.get('duration_s')}s | {(r.get('usage') or {}).get('calls', 0)} | {r.get('tool_calls', 0)}({r.get('tool_errors', 0)}) | "
            f"{len(r.get('hitl') or [])} | {len(r.get('delegations') or [])} | {n_exp} |")
    L.append("")
    fm = s.get("failure_modes") or {}
    L += ["## 失敗模式", ""]
    if fm:
        L += ["| 失敗模式 | 次數 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(fm.items(), key=lambda kv: -kv[1])]
        L.append("")
        for r in records:
            if r["outcome"] in ("success", "unverified"):
                continue
            failed = [c for c in r.get("checks") or [] if not c["passed"]]
            L.append(f"- `{r['task_id']}`（{OUTCOME_ZH.get(r['outcome'])}，{r.get('failure_mode')}）")
            for c in failed[:4]:
                msg = " ".join(c["message"].split())[:220]
                L.append(f"  - ✗ `{c['id']}`：{msg}")
            if r.get("error"):
                L.append(f"  - 錯誤：{' '.join(r['error'].split())[:220]}")
    else:
        L.append("無。")
    recovered = [r for r in records if r.get("internal_errors")]
    if recovered:
        L += ["", "**團隊內部的錯誤**（某個成員或受託者的運行失敗，但由主導者接手處理，任務結果仍以檢查項判定）："]
        for r in recovered:
            L.append(f"- `{r['task_id']}`（{OUTCOME_ZH.get(r['outcome'], r['outcome'])}）：" + "；".join(
                " ".join(e.split())[:160] for e in r["internal_errors"][:3]))
    L.append("")
    me = s.get("memory_effect") or {}
    L += ["## 記憶與經驗演化", "",
          f"- 取用了過往經驗的任務：{me.get('tasks_with_retrieved_experience')} 個，目標完成率 {_fmt(me.get('goal_rate_with_experience'), '%')}；"
          f"未取用的任務：{me.get('tasks_without_retrieved_experience')} 個，目標完成率 {_fmt(me.get('goal_rate_without_experience'), '%')}。",
          "", "| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |",
          "|---|---|---|---|---|---|---|"]
    for r in records:
        for name, after in (r.get("memory_after") or {}).items():
            before = (r.get("memory_before") or {}).get(name, {})
            eo = after.get("experience_outcomes", {})
            added = [x for x in r.get("experiences_added") or [] if x.get("profile") == name]
            used = sum(len(x.get("ids") or []) for x in r.get("experiences_retrieved") or [] if x.get("profile") == name)
            L.append(
                f"| `{r['task_id']}` | @{name} | {before.get('memory_entries', 0)}/{before.get('user_entries', 0)} → "
                f"{after.get('memory_entries', 0)}/{after.get('user_entries', 0)} | {before.get('experiences', 0)} → {after.get('experiences', 0)}"
                f"（{eo.get('success', 0)}/{eo.get('partial', 0)}/{eo.get('failure', 0)}） | {after.get('skills', 0)} | {len(added)} | {used} |")
    L += ["", "經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。", ""]
    return "\n".join(L)


def render_comparison(runs: list[tuple[str, dict[str, Any]]]) -> str:
    """Side-by-side comparison of several runs (e.g. memory on vs off, pass 1 vs pass 2)."""
    L = ["# 評測比較", "", "| 指標 | " + " | ".join(name for name, _ in runs) + " |", "|---|" + "---|" * len(runs)]

    def row(label, fn):
        L.append(f"| {label} | " + " | ".join(fn(d["summary"]) for _, d in runs) + " |")

    row("任務數", lambda s: str(s["tasks"]))
    row("整體目標完成率", lambda s: _fmt(s["goal_completion_rate"], "%"))
    row("子任務完成率", lambda s: _fmt(s["subtask_completion_rate"], "%"))
    row("成功/部分/失敗/崩潰/逾時", lambda s: "/".join(str(s["outcomes"][k]) for k in ("success", "partial", "failed", "crashed", "timeout")))
    row("總執行時間", lambda s: f"{s['time']['total_s']}s")
    row("平均 / 中位數執行時間", lambda s: f"{_fmt(s['time']['mean_s'], 's')} / {_fmt(s['time']['median_s'], 's')}")
    row("模型調用", lambda s: str(s["usage"]["calls"]))
    row("輸入 / 輸出 tokens", lambda s: f"{s['usage']['prompt_tokens']:,} / {s['usage']['completion_tokens']:,}")
    row("快取命中率", lambda s: f"{s['usage']['cache_hit_rate'] * 100:.1f}%")
    row("估算花費", lambda s: f"${s['usage']['cost_usd']:.4f}")
    row("取用經驗的任務數", lambda s: str((s.get("memory_effect") or {}).get("tasks_with_retrieved_experience", 0)))
    ids: list[str] = []
    for _, d in runs:
        for t in d["tasks"]:
            key = f"{t['task_id']}" + (f" (p{t['pass']})" if t.get("pass", 1) > 1 else "")
            if key not in ids:
                ids.append(key)
    L += ["", "## 逐任務", "", "| 任務 | " + " | ".join(name for name, _ in runs) + " |", "|---|" + "---|" * len(runs)]
    for key in ids:
        cells = []
        for _, d in runs:
            t = next((t for t in d["tasks"] if f"{t['task_id']}" + (f" (p{t['pass']})" if t.get("pass", 1) > 1 else "") == key), None)
            cells.append("—" if t is None else f"{OUTCOME_ZH.get(t['outcome'], t['outcome'])} {t.get('checks_passed', 0)}/{t.get('checks_total', 0)} · {t.get('duration_s')}s · {(t.get('usage') or {}).get('calls', 0)} calls")
        L.append(f"| `{key}` | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"


def render_aggregate(name: str, runs: list[tuple[str, dict[str, Any]]]) -> str:
    """Mean ± sample std over repeated runs of the same suite, plus per-task success frequency."""
    import statistics as st

    def ms(values: list[float]) -> str:
        vals = [v for v in values if v is not None]
        if not vals:
            return "—"
        if len(vals) == 1:
            return f"{vals[0]:.1f}"
        return f"{st.mean(vals):.1f} ± {st.stdev(vals):.1f}"

    sums = [d["summary"] for _, d in runs]
    L = [f"# 重複執行統計：{name}（{len(runs)} 次）", "",
         "| 指標 | 平均 ± 標準差 |", "|---|---|",
         f"| 整體目標完成率（%） | {ms([s['goal_completion_rate'] for s in sums])} |",
         f"| 子任務完成率（%） | {ms([s['subtask_completion_rate'] for s in sums])} |",
         f"| 總執行時間（s） | {ms([s['time']['total_s'] for s in sums])} |",
         f"| 每任務平均時間（s） | {ms([s['time']['mean_s'] for s in sums])} |",
         f"| 模型調用 | {ms([s['usage']['calls'] for s in sums])} |",
         f"| 估算花費（美分） | {ms([100 * s['usage']['cost_usd'] for s in sums])} |",
         f"| 快取命中率（%） | {ms([100 * s['usage']['cache_hit_rate'] for s in sums])} |",
         "", "使用的運行：" + "、".join(f"`{n}`（{d['summary'].get('code_version', '?')}）" for n, d in runs), "",
         "## 逐任務成功次數", "", "| 任務 | 成功 | 平均時間 | 失敗模式 |", "|---|---|---|---|"]
    tasks: dict[str, list[dict[str, Any]]] = {}
    for _, d in runs:
        for t in d["tasks"]:
            tasks.setdefault(t["task_id"], []).append(t)
    for tid, ts in tasks.items():
        ok = sum(t["outcome"] == "success" for t in ts)
        modes = sorted({t["failure_mode"] for t in ts if t.get("failure_mode")})
        L.append(f"| `{tid}` | {ok}/{len(ts)} | {ms([t['duration_s'] for t in ts])}s | {'; '.join(modes) or '—'} |")
    return "\n".join(L) + "\n"
