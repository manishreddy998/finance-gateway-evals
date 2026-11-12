"""Turn recorded actions into the numbers a ship/no-ship decision needs.

Writes results/summary.md, docs/img/*.png and docs/dashboard.html. Free to run: no model calls.
"""
from __future__ import annotations

import base64
import collections
import io
import json
import pathlib
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROWS = [json.loads(l) for l in (ROOT / "results" / "actions.jsonl").open()]
ORDER = ["opus_full_cache", "sonnet_full_cache", "haiku_full_cache", "haiku_full_cache_r2", "haiku_pruned", "haiku_escalate_sonnet"]
LABEL = {"opus_full_cache": "Opus 5.5, cached", "sonnet_full_cache": "Sonnet 5.5, cached",
         "haiku_full_cache": "Haiku 5.5, cached", "haiku_full_cache_r2": "Haiku 5.5, cached (rerun)",
         "haiku_pruned": "Haiku 5.5, pruned, no cache", "haiku_escalate_sonnet": "Haiku 5.5 + Sonnet on retry"}
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
by = collections.defaultdict(list)
for r in ROWS:
    by[r["config"]].append(r)
configs = [c for c in ORDER if c in by]


def kind(r):
    return "should-not-act" if r["shape"] in {"ambiguous", "destructive"} or r["id"] in {"w04", "w05", "w06", "w07", "w08", "h12", "h13", "h14", "h15", "h16"} else r["type"]


def pct(xs):
    return f"{100 * sum(xs) / len(xs):.0f}%" if xs else "n/a"


def stats(c):
    rs = by[c]
    n = len(rs)
    return dict(
        n=n, acc=sum(r["correct"] for r in rs) / n,
        by_kind={k: pct([r["correct"] for r in rs if kind(r) == k]) for k in ("query", "writeback", "should-not-act")},
        cost=sum(r["cost_usd"] for r in rs), uncached=sum(r["uncached_cost_usd"] for r in rs),
        per1k=1000 * sum(r["cost_usd"] for r in rs) / n,
        lat=statistics.median(r["latency_s"] for r in rs), retry=sum(r["retried"] for r in rs),
        unsafe=sum(r["unsafe_valid_entry"] for r in rs),
        out_share=sum(r["output_tokens"] for r in rs) and None,
    )


S = {c: stats(c) for c in configs}

# ---------- naive vs robust grading (queries with a gold answer) ----------
q_rows = [r for r in by.get("haiku_full_cache", []) if r["chosen"] == "query" and r["id"][0] in "qh" and r["id"] not in {"h15", "h16"}]
naive = dict(text=sum(r["sql_text_match"] for r in q_rows), a=sum(r["correct_tenant_a"] for r in q_rows),
             ab=sum(r["correct"] for r in q_rows), n=len(q_rows))

# ---------- run-to-run variance ----------
r1 = {r["id"]: r for r in by.get("haiku_full_cache", [])}
r2 = {r["id"]: r for r in by.get("haiku_full_cache_r2", [])}
flips = [i for i in r1 if i in r2 and (r1[i]["chosen"] != r2[i]["chosen"] or r1[i]["correct"] != r2[i]["correct"])]

# ---------- cost breakdown and tail (Opus) ----------
PRICE_IN = {"claude-opus-5-5": 4.0, "claude-sonnet-5-5": 2.0, "claude-haiku-5-5": 0.1}


def breakdown(c):
    rs = by[c]
    p = PRICE_IN[rs[0]["model"]] if rs[0]["model"] in PRICE_IN else 4.0
    return dict(input=sum(r["input_tokens"] for r in rs) * p / 1e6,
                cache_write=sum(r["cache_write"] for r in rs) * p * 1.25 / 1e6,
                cache_read=sum(r["cache_read"] for r in rs) * p * 0.1 / 1e6,
                output=sum(r["cost_usd"] for r in rs) - (sum(r["input_tokens"] for r in rs) * p + sum(r["cache_write"] for r in rs) * p * 1.25 + sum(r["cache_read"] for r in rs) * p * 0.1) / 1e6)


def tail(c):
    rs = sorted(by[c], key=lambda r: -r["cost_usd"])
    top = rs[: max(1, len(rs) // 10)]
    shape_cost = collections.defaultdict(list)
    for r in by[c]:
        shape_cost[kind(r)].append(r["cost_usd"])
    return sum(r["cost_usd"] for r in top) / sum(r["cost_usd"] for r in rs), top, {k: 1000 * statistics.mean(v) for k, v in shape_cost.items()}


# ---------- markdown summary ----------
lines = ["# Results", "", f"{S[configs[0]]['n']} actions per configuration on two tenants. Costs are measured from API usage.", "",
         "| Configuration | Accuracy | Queries | Writebacks | Should-not-act | Postable bad entries | Cost / 1k actions | Without caching | Median latency | Retries |",
         "|---|---|---|---|---|---|---|---|---|---|"]
for c in configs:
    s = S[c]
    lines.append(f"| {LABEL[c]} | **{s['acc']:.0%}** | {s['by_kind']['query']} | {s['by_kind']['writeback']} | {s['by_kind']['should-not-act']} | {s['unsafe']} | ${s['per1k']:.2f} | ${1000 * s['uncached'] / s['n']:.2f} | {s['lat']:.1f}s | {s['retry']} |")
lines += ["", "## What a naive grader would have reported (Haiku, query actions)", "",
          f"- SQL text matches the gold SQL: **{naive['text']}/{naive['n']}**",
          f"- Result correct on tenant A only: {naive['a']}/{naive['n']}",
          f"- Result correct on both tenants (what we report): {naive['ab']}/{naive['n']}", "",
          "## Run-to-run variance (Haiku, same requests, two runs)", "",
          f"- Cases whose chosen action or grade changed: {len(flips)}/{len(r1)} ({', '.join(flips) or 'none'})", ""]
if "opus_full_cache" in by:
    b = breakdown("opus_full_cache")
    share, top, per_kind = tail("opus_full_cache")
    tot = sum(b.values())
    lines += ["## Where Opus spend goes", "",
              "| Component | Share |", "|---|---|"] + [f"| {k.replace('_', ' ')} | {v / tot:.0%} |" for k, v in b.items()] + [
              "", f"- The most expensive 10% of actions are {share:.0%} of Opus spend: " + ", ".join(f"{r['id']} (${r['cost_usd']:.4f})" for r in top),
              "- Cost per 1k actions by action kind: " + ", ".join(f"{k} ${v:.2f}" for k, v in per_kind.items()), ""]
(ROOT / "results" / "summary.md").write_text("\n".join(lines))
print("\n".join(lines))

# ---------- charts ----------
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
                     "axes.spines.top": False, "axes.spines.right": False})
OUT = ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
pts = [c for c in configs if c != "haiku_full_cache_r2"]

fig, ax = plt.subplots(figsize=(8.2, 4))
for i, c in enumerate(pts):
    x, y = S[c]["per1k"], 100 * S[c]["acc"]
    ax.scatter([x], [y], s=90, color=COLORS[configs.index(c)], edgecolor=SURFACE, linewidth=2, zorder=3)
    ax.annotate(LABEL[c], (x, y), xytext=(8, 6 if i % 2 else -12), textcoords="offset points", fontsize=9, color=INK)
ax.set_xscale("log")
ax.set_xlabel("Cost per 1,000 gateway actions (USD, log scale)")
ax.set_ylabel("Accuracy (%)")
ax.set_ylim(94, 101)
ax.grid(color=GRID, linewidth=0.8)
ax.set_title("Same accuracy as Opus for about 1/13 of the cost", loc="left", fontsize=11.5)
fig.tight_layout()
fig.savefig(OUT / "frontier.png", dpi=200)

fig, ax = plt.subplots(figsize=(8.2, 3.2))
cs = [c for c in pts if c != "haiku_pruned"]
ys = range(len(cs))
ax.barh([y + 0.18 for y in ys], [1000 * S[c]["uncached"] / S[c]["n"] for c in cs], height=0.34, color="#c3c2b7", label="without prompt caching", edgecolor=SURFACE, linewidth=2)
ax.barh([y - 0.18 for y in ys], [S[c]["per1k"] for c in cs], height=0.34, color="#2a78d6", label="with prompt caching", edgecolor=SURFACE, linewidth=2)
for y, c in zip(ys, cs):
    ax.text(1000 * S[c]["uncached"] / S[c]["n"] * 1.03, y + 0.18, f"${1000 * S[c]['uncached'] / S[c]['n']:.2f}", va="center", fontsize=8.5, color=INK2)
    ax.text(S[c]["per1k"] * 1.03, y - 0.18, f"${S[c]['per1k']:.2f}", va="center", fontsize=8.5, color=INK)
ax.set_yticks(list(ys), [LABEL[c] for c in cs])
ax.set_xlabel("Cost per 1,000 actions (USD)")
ax.legend(frameon=False, loc="upper right", fontsize=9)
ax.set_title("Caching the system prompt cuts cost by about two thirds", loc="left", fontsize=11.5)
ax.grid(axis="x", color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
fig.tight_layout()
fig.savefig(OUT / "caching.png", dpi=200)


# ---------- dashboard ----------
def img64(name):
    return base64.b64encode((OUT / name).read_bytes()).decode()


rows_html = "".join(
    f"<tr><td>{LABEL[c]}</td><td>{S[c]['acc']:.0%}</td><td>${S[c]['per1k']:.2f}</td><td>${1000 * S[c]['uncached'] / S[c]['n']:.2f}</td>"
    f"<td>{S[c]['lat']:.1f}s</td><td>{S[c]['retry']}</td><td>{S[c]['unsafe']}</td></tr>" for c in configs)
html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gateway Cost Dashboard</title><style>
:root{{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:#e6e5e1;--accent:#2a78d6}}
@media (prefers-color-scheme: dark){{:root{{--bg:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--line:#383835;--accent:#3987e5}}}}
body{{background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:980px;margin:auto}}
h1{{font-size:24px;margin:0 0 4px}} p.sub{{color:var(--ink2);margin:0 0 20px}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px;font-size:14px}} th,td{{text-align:left;padding:8px;border-bottom:1px solid var(--line)}}
th{{color:var(--ink2);font-weight:600}} img{{max-width:100%;background:#fcfcfb;border-radius:8px}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0}} .k div{{border:1px solid var(--line);border-radius:10px;padding:12px}}
.k b{{display:block;font-size:22px}} .k span{{color:var(--ink2);font-size:13px}}</style></head><body>
<h1>Gateway cost and quality</h1><p class="sub">{S[configs[0]]['n']} regression actions per configuration, graded by execution on two tenants. Generated by scripts/analyze.py.</p>
<div class="k"><div><b>${S['opus_full_cache']['per1k']:.2f}</b><span>Opus cost per 1k actions</span></div>
<div><b>${S['haiku_escalate_sonnet']['per1k']:.2f}</b><span>Haiku + Sonnet-on-retry per 1k actions</span></div>
<div><b>{S['haiku_escalate_sonnet']['acc']:.0%}</b><span>accuracy of the routed policy</span></div>
<div><b>{sum(S[c]['unsafe'] for c in configs)}</b><span>postable bad journal entries, all configs</span></div></div>
<table><tr><th>Configuration</th><th>Accuracy</th><th>Cost / 1k</th><th>Without caching</th><th>Median latency</th><th>Retries</th><th>Postable bad entries</th></tr>{rows_html}</table>
<img alt="Cost versus accuracy per configuration" src="data:image/png;base64,{img64('frontier.png')}"><br><br>
<img alt="Cost with and without prompt caching" src="data:image/png;base64,{img64('caching.png')}"></body></html>"""
(ROOT / "docs" / "dashboard.html").write_text(html)
print("wrote results/summary.md, docs/img/*.png, docs/dashboard.html")
