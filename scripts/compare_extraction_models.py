"""
A/B the deal extractor across two models: Groq llama-3.3-70b-versatile vs
Gemini gemini-2.5-flash-lite.

Read-only. Pulls Article nodes out of Neo4j, runs the SAME `EXTRACTION_PROMPT`
through both providers, and field-by-field diffs the resulting DealData. It
never writes to Neo4j and never touches stored Deal nodes — stored deals were
extracted under older prompt revisions, so re-running both models on the same
text is the only apples-to-apples comparison.

Gemini is called over its OpenAI-compatible endpoint with plain `requests`, so
this adds no dependency. That is also the exact call shape a real migration
would use, which makes this script a rehearsal of the swap.

Sampling is stratified by default: half the articles already produced a Deal
("deal" stratum), half were filtered as irrelevant ("non-deal" stratum). Those
are the two classes that fail differently — a cheap model tends to lose the
harder role assignments on real deals, and to hallucinate deals out of earnings
or product-launch stories. A flat random sample hides both.

Usage:
    python scripts/compare_extraction_models.py --gemini-api-key KEY -n 200
    python scripts/compare_extraction_models.py --gemini-api-key KEY -n 40 --stratum deal
    python scripts/compare_extraction_models.py --gemini-api-key KEY --dump results.json

Keys:
    Groq   — from the usual config plumbing (--groq-api-key, or NEWS_SCRAPPER_CONFIG).
    Gemini — --gemini-api-key, or the GEMINI_API_KEY environment variable.
"""
import argparse
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests
from groq import Groq
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ConfigError, add_config_arguments, load_config
from src.processor.extractor import (
    EXTRACTION_PROMPT,
    SECTORS,
    SUB_SECTORS,
    DealData,
)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# Fields compared for exact equality. `summary` is excluded on purpose: it is
# free prose and will never match across models, so it is scored separately on
# null-vs-populated agreement only.
COMPARED_FIELDS = [
    "buyer", "seller", "target_company", "deal_value",
    "sector", "sub_sector", "country", "deal_type",
]

# Published $/1M tokens. Only used to price the observed token counts; override
# if the vendors have moved since. See --no-cost to skip entirely.
PRICING = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "gemini-2.5-flash-lite": (0.10, 0.40),   # retired for new API keys
    "gemini-3.1-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
}

VALID_SUB_SECTORS = {s for subs in SUB_SECTORS.values() for s in subs}
VALID_DEAL_TYPES = {
    "acquisition", "merger", "joint_venture",
    "funding_round", "divestiture", "partnership", "other",
}


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------

# Deal stratum: canonical articles that already produced a Deal.
DEAL_SAMPLE = """
MATCH (a:NewsArticle)-[:HAS_DEAL]->(:NewsDeal)
WHERE a.duplicate_of IS NULL
  AND a.content IS NOT NULL AND size(a.content) > 400
RETURN a.id AS id, a.title AS title, a.content AS content, 'deal' AS stratum
ORDER BY a.scraped_at DESC
LIMIT $limit
"""

# Non-deal stratum: articles the filter judged irrelevant. These should extract
# to all-nulls; anything else is a false positive.
NON_DEAL_SAMPLE = """
MATCH (a:NewsArticle)
WHERE a.is_ma_funding_relevant = false
  AND a.content IS NOT NULL AND size(a.content) > 400
RETURN a.id AS id, a.title AS title, a.content AS content, 'non-deal' AS stratum
ORDER BY a.scraped_at DESC
LIMIT $limit
"""


def fetch_articles(driver, database: str, n: int, stratum: str) -> list[dict]:
    plan = []
    if stratum in ("both", "deal"):
        plan.append((DEAL_SAMPLE, n // 2 if stratum == "both" else n))
    if stratum in ("both", "non-deal"):
        plan.append((NON_DEAL_SAMPLE, n - n // 2 if stratum == "both" else n))

    rows: list[dict] = []
    with driver.session(database=database) as session:
        for cypher, limit in plan:
            if limit > 0:
                rows.extend(dict(r) for r in session.run(cypher, limit=limit))
    return rows


# --------------------------------------------------------------------------
# Model calls — both build the identical prompt
# --------------------------------------------------------------------------

def build_prompt(title: Optional[str], content: Optional[str]) -> str:
    """Byte-identical to DealExtractor.extract, including the 4000-char cap."""
    return EXTRACTION_PROMPT.format(
        sectors=", ".join(SECTORS),
        d2c_sub=", ".join(SUB_SECTORS["D2C"]),
        fintech_sub=", ".join(SUB_SECTORS["Fintech"]),
        others_sub=", ".join(SUB_SECTORS["Others"]),
        title=title or "(no title)",
        content=(content or "")[:4000],
    )


def with_retry(fn, attempts: int = 5):
    """Retry 429s with backoff, honouring the wait the provider asks for.

    Both free tiers throttle hard, and an unretried 429 silently shrinks the
    sample — which is worse than a slow run, because the report still prints
    and looks valid. Per-DAY quotas are NOT retried: no backoff outlasts them,
    and pretending otherwise just hangs the run.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            text = str(exc)
            is_429 = "429" in text or "rate_limit" in text.lower()
            if not is_429 or attempt == attempts - 1:
                raise
            if "per day" in text.lower() or "TPD" in text:
                raise
            m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", text)
            wait = (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else 2 ** attempt * 5
            time.sleep(min(wait + 1, 90))
    raise RuntimeError("unreachable")


def call_groq(client: Groq, model: str, prompt: str) -> dict:
    start = time.monotonic()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=600,
        response_format={"type": "json_object"},
    )
    return {
        "raw": resp.choices[0].message.content,
        "latency": time.monotonic() - start,
        "in_tokens": resp.usage.prompt_tokens,
        "out_tokens": resp.usage.completion_tokens,
    }


def call_gemini(api_key: str, model: str, prompt: str, thinking: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 600,
        "response_format": {"type": "json_object"},
    }
    # Thinking tokens bill as output. Off by default: this job is fixed-schema
    # field extraction, not reasoning. Raise it only if `target_company`
    # regresses — that is the one field with a genuinely hard inference.
    if thinking != "default":
        body["reasoning_effort"] = thinking

    start = time.monotonic()
    resp = requests.post(
        f"{GEMINI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=90,
    )
    # Not every model accepts reasoning_effort — gemini-3.5-flash-lite rejects
    # it with a bare "invalid argument" that names no field — so retry once
    # without it rather than losing the run. A bad key is also a 400, but that
    # one names the key, so let it surface instead of retrying into itself.
    if (resp.status_code == 400 and "reasoning_effort" in body
            and "API key" not in resp.text):
        body.pop("reasoning_effort")
        start = time.monotonic()
        resp = requests.post(
            f"{GEMINI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=90,
        )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage") or {}
    return {
        "raw": data["choices"][0]["message"]["content"],
        "latency": time.monotonic() - start,
        "in_tokens": usage.get("prompt_tokens", 0),
        "out_tokens": usage.get("completion_tokens", 0),
    }


def parse(result: dict) -> dict:
    """Parse a raw response into a comparable record.

    Deliberately records BOTH the pre-validation payload and the post-DealData
    one. The Pydantic validators in extractor.py silently repair bad enums, so
    comparing only validated output would hide exactly the schema-adherence
    difference this test exists to measure.
    """
    out = {**result, "ok": False, "raw_fields": {}, "fields": {}, "error": None}
    try:
        raw = json.loads(result["raw"])
        out["raw_fields"] = {k: raw.get(k) for k in COMPARED_FIELDS + ["summary"]}
        out["fields"] = DealData(**raw).model_dump()
        out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def run_one(article: dict, groq_client, groq_model, gemini_key, gemini_model, thinking) -> dict:
    prompt = build_prompt(article["title"], article["content"])
    record = {
        "id": article["id"],
        "title": (article["title"] or "")[:120],
        "stratum": article["stratum"],
    }
    for name, fn in (
        ("groq", lambda: call_groq(groq_client, groq_model, prompt)),
        ("gemini", lambda: call_gemini(gemini_key, gemini_model, prompt, thinking)),
    ):
        try:
            record[name] = parse(with_retry(fn))
        except Exception as exc:
            record[name] = {
                "ok": False, "fields": {}, "raw_fields": {},
                "latency": 0.0, "in_tokens": 0, "out_tokens": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
    return record


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def norm(v) -> Optional[str]:
    """Compare on semantics, not formatting: null == "" == "null", case-folded."""
    if v is None:
        return None
    s = str(v).strip().lower()
    return None if s in ("", "null", "none", "n/a") else s


def is_empty(fields: dict) -> bool:
    """True when the model called this a non-deal (every field null)."""
    return all(norm(fields.get(f)) is None for f in COMPARED_FIELDS)


def schema_violations(raw_fields: dict) -> list[str]:
    """Enum values the model invented, BEFORE Pydantic repairs them."""
    bad = []
    sector, sub, dtype = (raw_fields.get(k) for k in ("sector", "sub_sector", "deal_type"))
    if norm(sector) is not None and sector not in SECTORS:
        bad.append(f"sector={sector!r}")
    if norm(sub) is not None and sub not in VALID_SUB_SECTORS:
        bad.append(f"sub_sector={sub!r}")
    if norm(dtype) is not None and dtype not in VALID_DEAL_TYPES:
        bad.append(f"deal_type={dtype!r}")
    return bad


def summarise(records: list[dict], args) -> dict:
    both_ok = [r for r in records if r["groq"]["ok"] and r["gemini"]["ok"]]

    agree = {f: 0 for f in COMPARED_FIELDS}
    for r in both_ok:
        for f in COMPARED_FIELDS:
            if norm(r["groq"]["fields"].get(f)) == norm(r["gemini"]["fields"].get(f)):
                agree[f] += 1

    n = len(both_ok) or 1
    stats = {
        "articles": len(records),
        "both_parsed": len(both_ok),
        "field_agreement": {f: agree[f] / n for f in COMPARED_FIELDS},
        "full_record_agreement": sum(
            1 for r in both_ok
            if all(norm(r["groq"]["fields"].get(f)) == norm(r["gemini"]["fields"].get(f))
                   for f in COMPARED_FIELDS)
        ) / n,
    }

    for side in ("groq", "gemini"):
        rs = [r for r in records if r[side]["ok"]]
        lat = [r[side]["latency"] for r in rs] or [0]
        in_tok = sum(r[side]["in_tokens"] for r in rs)
        out_tok = sum(r[side]["out_tokens"] for r in rs)
        model = args.groq_model if side == "groq" else args.gemini_model
        pin, pout = PRICING.get(model, (0.0, 0.0))
        stats[side] = {
            "model": model,
            "parsed": len(rs),
            "failed": len(records) - len(rs),
            "latency_p50": statistics.median(lat),
            "latency_p95": sorted(lat)[int(len(lat) * 0.95) - 1] if len(lat) > 1 else lat[0],
            "in_tokens": in_tok,
            "out_tokens": out_tok,
            "schema_violations": sum(1 for r in rs if schema_violations(r[side]["raw_fields"])),
            "called_non_deal": sum(1 for r in rs if is_empty(r[side]["fields"])),
            "cost_per_1k": ((in_tok * pin + out_tok * pout) / 1_000_000 / max(len(rs), 1)) * 1000,
        }

    # Disagreements that actually matter: the two models disagree on whether
    # the article describes a deal at all.
    stats["deal_vs_nondeal_conflicts"] = [
        {"id": r["id"], "title": r["title"], "stratum": r["stratum"],
         "groq_found_deal": not is_empty(r["groq"]["fields"]),
         "gemini_found_deal": not is_empty(r["gemini"]["fields"])}
        for r in both_ok
        if is_empty(r["groq"]["fields"]) != is_empty(r["gemini"]["fields"])
    ]
    return stats


def print_report(stats: dict, records: list[dict], args) -> None:
    g, m = stats["groq"], stats["gemini"]
    print("\n" + "=" * 74)
    print(f"  {stats['articles']} articles | both parsed: {stats['both_parsed']}")
    print("=" * 74)

    print(f"\n{'':<26}{g['model'][:20]:>22}{m['model'][:22]:>24}")
    print("-" * 74)
    rows = [
        ("parsed OK", f"{g['parsed']}", f"{m['parsed']}"),
        ("JSON/parse failures", f"{g['failed']}", f"{m['failed']}"),
        ("invalid enum values", f"{g['schema_violations']}", f"{m['schema_violations']}"),
        ("called it a non-deal", f"{g['called_non_deal']}", f"{m['called_non_deal']}"),
        ("latency p50", f"{g['latency_p50']:.2f}s", f"{m['latency_p50']:.2f}s"),
        ("latency p95", f"{g['latency_p95']:.2f}s", f"{m['latency_p95']:.2f}s"),
        ("input tokens (total)", f"{g['in_tokens']:,}", f"{m['in_tokens']:,}"),
        ("output tokens (total)", f"{g['out_tokens']:,}", f"{m['out_tokens']:,}"),
    ]
    if not args.no_cost:
        rows.append(("cost / 1k articles", f"${g['cost_per_1k']:.2f}", f"${m['cost_per_1k']:.2f}"))
    for label, a, b in rows:
        print(f"{label:<26}{a:>22}{b:>24}")

    if not args.no_cost and g["cost_per_1k"]:
        delta = (m["cost_per_1k"] - g["cost_per_1k"]) / g["cost_per_1k"] * 100
        print(f"{'':<26}{'':>22}{f'{delta:+.0f}%':>24}")

    print("\nField agreement (gemini vs llama)")
    print("-" * 74)
    for f in COMPARED_FIELDS:
        pct = stats["field_agreement"][f] * 100
        bar = "#" * int(pct / 4)
        flag = "  <-- review" if pct < 85 else ""
        print(f"  {f:<18}{pct:6.1f}%  {bar:<25}{flag}")
    print(f"\n  {'ALL FIELDS MATCH':<18}{stats['full_record_agreement'] * 100:6.1f}%")

    conflicts = stats["deal_vs_nondeal_conflicts"]
    if conflicts:
        print(f"\nDeal / non-deal disagreements ({len(conflicts)}) — the costly class")
        print("-" * 74)
        for c in conflicts[:15]:
            who = "gemini only" if c["gemini_found_deal"] else "llama only"
            print(f"  [{c['stratum']:<8}] {who:<12} {c['title'][:44]}")
        if len(conflicts) > 15:
            print(f"  ... and {len(conflicts) - 15} more (see --dump)")

    print(f"\nField-level disagreements (first {args.show})")
    print("-" * 74)
    shown = 0
    for r in records:
        if not (r["groq"]["ok"] and r["gemini"]["ok"]):
            continue
        diffs = [
            (f, r["groq"]["fields"].get(f), r["gemini"]["fields"].get(f))
            for f in COMPARED_FIELDS
            if norm(r["groq"]["fields"].get(f)) != norm(r["gemini"]["fields"].get(f))
        ]
        if not diffs:
            continue
        print(f"\n  [{r['stratum']}] {r['title'][:66]}")
        for f, a, b in diffs:
            print(f"      {f:<16} llama: {str(a)[:28]:<30} gemini: {str(b)[:28]}")
        shown += 1
        if shown >= args.show:
            break
    if shown == 0:
        print("  (none)")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_config_arguments(ap, only=("neo4j", "groq"))
    ap.add_argument("-n", type=int, default=100, help="articles to sample (default 100)")
    ap.add_argument("--stratum", choices=("both", "deal", "non-deal"), default="both")
    ap.add_argument("--gemini-api-key", default=os.environ.get("GEMINI_API_KEY", ""))
    ap.add_argument("--gemini-model", default="gemini-3.5-flash-lite")
    ap.add_argument("--groq-model", default="llama-3.3-70b-versatile")
    # 'default' omits reasoning_effort entirely. That is the right default here:
    # gemini-3.5-flash-lite rejects reasoning_effort=none outright, and measured
    # unprompted it emits no thinking-token inflation anyway.
    ap.add_argument("--thinking", default="default", choices=("none", "low", "medium", "high", "default"),
                    help="Gemini reasoning_effort; 'default' omits the parameter (default)")
    ap.add_argument("--workers", type=int, default=4, help="parallel articles (lower if rate-limited)")
    ap.add_argument("--show", type=int, default=20, help="disagreement examples to print")
    ap.add_argument("--dump", help="write the full per-article result set to this JSON file")
    ap.add_argument("--no-cost", action="store_true", help="skip cost estimates")
    args = ap.parse_args()

    try:
        config = load_config(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if not args.gemini_api_key:
        print("Gemini API key missing. Pass --gemini-api-key or set GEMINI_API_KEY.", file=sys.stderr)
        return 2
    if not config.groq.api_key:
        print("Groq API key missing. Pass --groq-api-key.", file=sys.stderr)
        return 2

    driver = GraphDatabase.driver(
        config.neo4j.uri, auth=(config.neo4j.user, config.neo4j.password)
    )
    try:
        articles = fetch_articles(driver, config.neo4j.database, args.n, args.stratum)
    finally:
        driver.close()

    if not articles:
        print("No articles matched the sample query.", file=sys.stderr)
        return 1

    print(f"Sampled {len(articles)} articles "
          f"({sum(1 for a in articles if a['stratum'] == 'deal')} deal / "
          f"{sum(1 for a in articles if a['stratum'] == 'non-deal')} non-deal)")
    print(f"Running {args.groq_model} vs {args.gemini_model} "
          f"(thinking={args.thinking}, workers={args.workers})...")

    groq_client = Groq(api_key=config.groq.api_key)
    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(run_one, a, groq_client, args.groq_model,
                        args.gemini_api_key, args.gemini_model, args.thinking)
            for a in articles
        ]
        for i, fut in enumerate(futures, 1):
            records.append(fut.result())
            print(f"\r  {i}/{len(futures)}", end="", flush=True)
    print()

    stats = summarise(records, args)
    print_report(stats, records, args)

    if args.dump:
        Path(args.dump).write_text(json.dumps({"stats": stats, "records": records}, indent=2, default=str))
        print(f"Full results written to {args.dump}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
