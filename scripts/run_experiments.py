"""Run each gateway configuration over the regression suite and record every action.

Usage:
    python scripts/run_experiments.py haiku_full_cache sonnet_full_cache opus_full_cache
    GATEWAY_CACHE=replay python scripts/run_experiments.py --all     # free, no API key

Each action records: case, config, model, tokens (input / cache write / cache read / output), latency,
cost, the cost it would have had without caching, retries, and its grade. Output: results/actions.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gateway_evals import llm  # noqa: E402
from gateway_evals.cases import CASES  # noqa: E402
from gateway_evals.erp import tenants  # noqa: E402
from gateway_evals.gateway import run_read  # noqa: E402
from gateway_evals.prompt import system_prompt  # noqa: E402
from gateway_evals.score import grade  # noqa: E402

CONFIGS = {
    "haiku_full_cache": dict(model="claude-haiku-5-5", pruned=False, cache=True),
    "haiku_pruned": dict(model="claude-haiku-5-5", pruned=True, cache=False),
    "haiku_full_cache_r2": dict(model="claude-haiku-5-5", pruned=False, cache=True, run=2),
    "sonnet_full_cache": dict(model="claude-sonnet-5-5", pruned=False, cache=True),
    "opus_full_cache": dict(model="claude-opus-5-5", pruned=False, cache=True),
}
OUT = ROOT / "results" / "actions.jsonl"
T = tenants()


def run_case(name: str, cfg: dict, case: dict) -> dict:
    system = system_prompt(case["text"] if cfg["pruned"] else None)
    calls = [llm.call(cfg["model"], system, case["text"], cfg["cache"], run=cfg.get("run", 1))]
    action = calls[-1].action
    # one repair attempt when generated SQL fails to run: this is the retry loop that inflates cost
    if action and action["action"] == "query":
        res = run_read(T["A"], action.get("sql"))
        if not res.ok:
            retry_msg = f"{case['text']}\n\nYour previous SQL failed:\n{action.get('sql')}\nError: {res.error}\nReturn a corrected action."
            calls.append(llm.call(cfg["model"], system, retry_msg, cfg["cache"], run=cfg.get("run", 1)))
            action = calls[-1].action or action
    g = grade(case, action, T)
    return dict(config=name, **g, calls=len(calls), retried=len(calls) > 1,
                model=calls[0].model, action=action,
                input_tokens=sum(c.input_tokens for c in calls), cache_write=sum(c.cache_write_tokens for c in calls),
                cache_read=sum(c.cache_read_tokens for c in calls), output_tokens=sum(c.output_tokens for c in calls),
                latency_s=round(sum(c.latency_s for c in calls), 2), cost_usd=sum(c.cost_usd for c in calls),
                uncached_cost_usd=sum(c.uncached_cost_usd for c in calls),
                errors=[c.error for c in calls if c.error], tenant="A+B")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    names = list(CONFIGS) if args.all else args.configs
    existing = [json.loads(l) for l in OUT.open()] if OUT.exists() else []
    rows = [r for r in existing if r["config"] not in names]
    for name in names:
        cfg = CONFIGS[name]
        # first case alone so later calls can read the prompt cache it writes
        first = run_case(name, cfg, CASES[0])
        with ThreadPoolExecutor(max_workers=4) as pool:
            rest = list(pool.map(lambda c: run_case(name, cfg, c), CASES[1:]))
        batch = [first, *rest]
        errs = [e for r in batch for e in r["errors"]]
        if errs:
            sys.exit(f"{name}: {len(errs)} failed calls ({errs[0]}); nothing saved")
        rows += batch
        acc = sum(r["correct"] for r in batch) / len(batch)
        print(f"{name:<22} accuracy {acc:.0%}  cost ${sum(r['cost_usd'] for r in batch):.4f}  "
              f"(uncached ${sum(r['uncached_cost_usd'] for r in batch):.4f})  total spent ${llm.spent():.3f}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))


if __name__ == "__main__":
    main()
