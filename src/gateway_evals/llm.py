"""Instrumented model calls: every action records model, tokens, cache behavior, latency and cost.

Cost is computed from the usage the API returns, including cache writes (1.25x input price) and cache
reads (0.1x). Each call is stored under a hash of its full request, so experiments can be re-scored
for free and CI can replay them without an API key. A hard spending cap stops a run before it
crosses the budget.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
from dataclasses import asdict, dataclass
from typing import Optional

import anthropic
from dotenv import load_dotenv

from .prompt import Action

ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

PRICES = {  # USD per million tokens: input, output
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
}
CACHE_WRITE, CACHE_READ = 1.25, 0.10
CACHE_DIR = ROOT / "runs" / "calls"
LEDGER = ROOT / "runs" / "spend.json"
BUDGET_USD = float(os.getenv("GATEWAY_BUDGET_USD", "1.50"))
MODE = os.getenv("GATEWAY_CACHE", "readwrite")  # readwrite | replay | off
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Call:
    model: str
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float
    uncached_cost_usd: float  # what the same call would cost with no prompt caching
    action: Optional[dict]
    error: Optional[str] = None
    replayed: bool = False


def price(model: str, inp: int, cw: int, cr: int, out: int) -> tuple[float, float]:
    pi, po = PRICES[model]
    cost = (inp * pi + cw * pi * CACHE_WRITE + cr * pi * CACHE_READ + out * po) / 1e6
    uncached = ((inp + cw + cr) * pi + out * po) / 1e6
    return cost, uncached


def spent() -> float:
    return json.loads(LEDGER.read_text())["usd"] if LEDGER.exists() else 0.0


def _charge(usd: float) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps({"usd": round(spent() + usd, 6)}))


_client: Optional[anthropic.Anthropic] = None


def call(model: str, system: str, user: str, cache: bool, effort: str = "low", run: int = 1) -> Call:
    # `run` only changes the record key, so repeated runs of the same request measure run-to-run variance
    key = hashlib.sha256(json.dumps([model, system, user, cache, effort, run]).encode()).hexdigest()[:24]
    path = CACHE_DIR / f"{key}.json"
    if MODE != "off" and path.exists():
        return Call(**{**json.loads(path.read_text()), "replayed": True})
    if MODE == "replay":
        return Call(model, 0, 0, 0, 0, 0.0, 0.0, 0.0, None, "not recorded")
    if spent() >= BUDGET_USD:
        raise BudgetExceeded(f"spent ${spent():.3f} of ${BUDGET_USD:.2f}; raise GATEWAY_BUDGET_USD to continue")

    global _client
    _client = _client or anthropic.Anthropic(max_retries=4)
    sys_block = {"type": "text", "text": system}
    if cache:
        sys_block["cache_control"] = {"type": "ephemeral"}
    extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model in FALLBACK_MODELS else {}
    t0 = time.perf_counter()
    try:
        resp = _client.beta.messages.parse(
            model=model, max_tokens=4000, system=[sys_block], output_config={"effort": effort},
            messages=[{"role": "user", "content": user}], output_format=Action, **extra)
    except anthropic.APIStatusError as exc:
        return Call(model, 0, 0, 0, 0, time.perf_counter() - t0, 0.0, 0.0, None, f"api_error {exc.status_code}")
    latency = time.perf_counter() - t0
    u = resp.usage
    cw, cr = u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0
    cost, uncached = price(resp.model if resp.model in PRICES else model, u.input_tokens, cw, cr, u.output_tokens)
    _charge(cost)
    action = resp.parsed_output.model_dump() if resp.parsed_output is not None else None
    err = "refusal" if resp.stop_reason == "refusal" else (None if action else "unparsed")
    rec = Call(resp.model, u.input_tokens, cw, cr, u.output_tokens, latency, cost, uncached, action, err)
    if MODE != "off" and action is not None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(rec)))
    return rec
