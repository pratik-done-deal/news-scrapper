"""
Side-by-side deal extraction: llama-3.3-70b-versatile (Groq) vs
gemini-3.5-flash-lite (Gemini), on real articles from Neo4j.

Read-only. Pulls M&A-relevant articles (`is_ma_funding_relevant = true`) that
already produced a Deal node, runs the SAME `EXTRACTION_PROMPT` through both
models, and prints every extracted field from both, article by article, so the
two outputs can be read against each other and against the article itself.

Two ways to get the llama side:

  live (default)  — call Groq now. The true apples-to-apples run: both models
                    see the identical prompt at the identical revision.
  --stored-llama  — read the Deal node llama already wrote for that article.
                    Costs no Groq quota, but those deals were extracted under
                    an OLDER prompt revision and their company names went
                    through `_normalize_company_name`, so a difference is not
                    necessarily the model's doing. Names are compared under
                    that same normalisation to keep the diff honest.

The DB is never written to.

Usage:
    python scripts/side_by_side_extraction.py --neo4j-password <pw> \
        --groq-api-key <groq_key> --gemini-api-key <gemini_key> -n 10

    python scripts/side_by_side_extraction.py --neo4j-password <pw> \
        --gemini-api-key <gemini_key> -n 10 --stored-llama

Keys can also come from the environment: GROQ_API_KEY, GEMINI_API_KEY.
"""

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Optional

from groq import Groq
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ConfigError, add_config_arguments, load_config
from src.db.repository import _normalize_company_name
from src.llm_client import create_llm_client
from src.paths import load_settings
from src.processor.extractor import (
    EXTRACTION_PROMPT,
    SECTORS,
    SUB_SECTORS,
    DealData,
)

FIELDS = [
    "buyer", "seller", "target_company", "deal_value",
    "sector", "sub_sector", "country", "deal_type",
]

# M&A-relevant articles that produced a deal. `duplicate_of IS NULL` keeps the
# canonical copy only, so the same story is not compared twice.
ARTICLE_QUERY = """
MATCH (a:NewsArticle)-[:HAS_DEAL]->(:NewsDeal)
WHERE a.is_ma_funding_relevant = true
  AND a.duplicate_of IS NULL
  AND a.content IS NOT NULL AND size(a.content) > 400
RETURN a.id AS id, a.title AS title, a.content AS content
ORDER BY a.scraped_at DESC
LIMIT $limit
"""

# What llama already extracted for these articles, as stored. Buyer/seller/target
# are relationships rather than properties: a funding round links its investors
# as INVESTED_IN and the recipient as INVOLVED_IN, an acquisition uses
# BOUGHT/SOLD, and ABOUT carries the subject of a stake sale.
STORED_DEAL_QUERY = """
MATCH (a:NewsArticle {id: $id})-[:HAS_DEAL]->(d:NewsDeal)
OPTIONAL MATCH (c:NewsCompany)-[r:BOUGHT|SOLD|INVESTED_IN|INVOLVED_IN|ABOUT]->(d)
RETURN d.deal_value AS deal_value, d.sector AS sector, d.sub_sector AS sub_sector,
       d.country AS country, d.deal_type AS deal_type, d.summary AS summary,
       collect({name: c.name, rel: type(r)}) AS parties
"""

# Relationship → the DealData field it came from.
REL_TO_FIELD = {
    "BOUGHT": "buyer",
    "INVESTED_IN": "buyer",
    "SOLD": "seller",
    "INVOLVED_IN": "seller",
    "ABOUT": "target_company",
}


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


def call_model(client, model: str, prompt: str) -> dict:
    """One extraction call. Both clients speak the same chat-completions API."""
    record = {"model": model, "ok": False, "raw": None, "fields": {}, "error": None,
              "latency": 0.0, "in_tokens": 0, "out_tokens": 0}
    start = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        record["latency"] = time.monotonic() - start
        record["raw"] = response.choices[0].message.content
        usage = response.usage
        if usage:
            record["in_tokens"] = usage.prompt_tokens or 0
            record["out_tokens"] = usage.completion_tokens or 0
        # Both the raw payload and the validated one are kept: the Pydantic
        # validators silently repair bad enums, so only comparing validated
        # output would hide a schema-adherence difference between the models.
        raw_fields = json.loads(record["raw"])
        record["raw_fields"] = raw_fields
        record["fields"] = DealData(**raw_fields).model_dump()
        record["ok"] = True
    except Exception as exc:
        record["latency"] = record["latency"] or (time.monotonic() - start)
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def fetch_stored_deal(session, article_id: str) -> dict:
    """The Deal node llama already wrote, shaped like a `call_model` record."""
    record = {"model": "llama-3.3-70b-versatile (stored)", "ok": False, "raw": None,
              "fields": {}, "error": None, "latency": 0.0, "in_tokens": 0, "out_tokens": 0}
    row = session.run(STORED_DEAL_QUERY, id=article_id).single()
    if not row:
        record["error"] = "no Deal node stored for this article"
        return record

    fields = {f: row[f] for f in ("deal_value", "sector", "sub_sector", "country",
                                  "deal_type", "summary")}
    names: dict[str, list[str]] = {"buyer": [], "seller": [], "target_company": []}
    for party in row["parties"]:
        field = REL_TO_FIELD.get(party.get("rel"))
        if field and party.get("name"):
            names[field].append(party["name"])
    for field, values in names.items():
        fields[field] = ", ".join(sorted(values)) or None

    record["fields"] = fields
    record["ok"] = True
    return record


def norm(value) -> Optional[str]:
    """Compare on semantics, not formatting: null == "" == "null", case-folded."""
    if value is None:
        return None
    text = str(value).strip().lower()
    return None if text in ("", "null", "none", "n/a") else text


NAME_FIELDS = ("buyer", "seller", "target_company")


def compare_key(field: str, value, normalise_names: bool):
    """The value a field is compared on.

    In stored mode the llama side has been through `_normalize_company_name`
    and lost its original ordering, so company names are compared as a set of
    normalised names on BOTH sides — otherwise every multi-investor round would
    read as a disagreement about nothing.
    """
    if normalise_names and field in NAME_FIELDS:
        if norm(value) is None:
            return None
        parts = [_normalize_company_name(p) for p in str(value).split(",") if p.strip()]
        return tuple(sorted(p.lower() for p in parts if p))
    return norm(value)


def agrees(field: str, a, b, normalise_names: bool) -> bool:
    return compare_key(field, a, normalise_names) == compare_key(field, b, normalise_names)


def show(value, width: int = 34) -> str:
    text = "—" if norm(value) is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def wrap(text: str, width: int, indent: str) -> str:
    words, lines, line = (text or "").split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return f"\n{indent}".join(lines) or "—"


def print_article(index: int, total: int, record: dict, labels: tuple[str, str],
                  normalise_names: bool) -> None:
    llama, gemini = record["llama"], record["gemini"]
    left, right = labels

    print("\n" + "=" * 100)
    print(f"[{index}/{total}] {(record['title'] or '(no title)')[:92]}")
    print(f"        id: {record['id']}")
    print("=" * 100)

    for res in (llama, gemini):
        if not res["ok"]:
            print(f"  !! {res['model']} failed: {res['error']}")

    print(f"\n  {'field':<15}{left:<36}{right:<36}{'':<4}")
    print("  " + "-" * 94)
    for field in FIELDS:
        a, b = llama["fields"].get(field), gemini["fields"].get(field)
        # The marker is the point of the whole run: it flags every field where
        # switching models would change what lands in Neo4j.
        mark = "" if agrees(field, a, b, normalise_names) else "  <-- differs"
        print(f"  {field:<15}{show(a):<36}{show(b):<36}{mark}")

    print(f"\n  summary (llama) : {wrap(llama['fields'].get('summary') or '—', 78, ' ' * 20)}")
    print(f"  summary (gemini): {wrap(gemini['fields'].get('summary') or '—', 78, ' ' * 20)}")
    if llama["latency"] or gemini["latency"]:
        print(
            f"\n  latency: llama {llama['latency']:.2f}s / gemini {gemini['latency']:.2f}s"
            f"   |   output tokens: llama {llama['out_tokens']} / gemini {gemini['out_tokens']}"
        )


def print_summary(records: list[dict], labels: tuple[str, str], normalise_names: bool) -> None:
    both_ok = [r for r in records if r["llama"]["ok"] and r["gemini"]["ok"]]
    print("\n" + "=" * 100)
    print(f"SUMMARY — {len(records)} articles, both models parsed {len(both_ok)}")
    print("=" * 100)

    if both_ok:
        print("\nField agreement")
        print("-" * 60)
        for field in FIELDS:
            matches = sum(
                1 for r in both_ok
                if agrees(field, r["llama"]["fields"].get(field),
                          r["gemini"]["fields"].get(field), normalise_names)
            )
            pct = matches / len(both_ok) * 100
            print(f"  {field:<16}{matches}/{len(both_ok)}  {pct:5.1f}%  {'#' * int(pct / 5)}")
        identical = sum(
            1 for r in both_ok
            if all(agrees(f, r["llama"]["fields"].get(f), r["gemini"]["fields"].get(f),
                          normalise_names)
                   for f in FIELDS)
        )
        print(f"\n  {'every field equal':<16}{identical}/{len(both_ok)}\n")

    print(f"\n{'':<26}{labels[0][:18]:>18}{labels[1][:24]:>24}")
    print("-" * 68)
    sides = {}
    for side in ("llama", "gemini"):
        ok = [r[side] for r in records if r[side]["ok"]]
        sides[side] = {
            "ok": len(ok),
            "failed": len(records) - len(ok),
            "p50": statistics.median([r["latency"] for r in ok]) if ok else 0.0,
            "in": sum(r["in_tokens"] for r in ok),
            "out": sum(r["out_tokens"] for r in ok),
        }
    rows = [
        ("parsed OK", "ok"), ("failures", "failed"),
        ("latency p50 (s)", "p50"), ("input tokens", "in"), ("output tokens", "out"),
    ]
    for label, key in rows:
        a, b = sides["llama"][key], sides["gemini"][key]
        fmt = (lambda v: f"{v:.2f}") if key == "p50" else (lambda v: f"{v:,}")
        print(f"{label:<26}{fmt(a):>18}{fmt(b):>24}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_config_arguments(parser, only=("neo4j", "groq"))
    parser.add_argument("-n", type=int, default=10, help="articles to compare (default 10)")
    parser.add_argument("--gemini-api-key", default=os.environ.get("GEMINI_API_KEY", ""))
    parser.add_argument("--gemini-model", default=None, help="default: groq.model from settings.yaml")
    parser.add_argument("--groq-model", default="llama-3.3-70b-versatile")
    parser.add_argument(
        "--stored-llama", action="store_true",
        help="read llama's side from the Deal nodes already in Neo4j instead of "
             "calling Groq (no Groq quota needed; older prompt revision)",
    )
    parser.add_argument("--dump", help="also write the full result set to this JSON file")
    args = parser.parse_args()

    try:
        config = load_config(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    settings = load_settings()
    gemini_model = args.gemini_model or settings["groq"]["model"]
    groq_key = config.groq.api_key or os.environ.get("GROQ_API_KEY", "")
    if not groq_key and not args.stored_llama:
        print("Groq API key missing. Pass --groq-api-key, set GROQ_API_KEY, or use "
              "--stored-llama.", file=sys.stderr)
        return 2
    if not args.gemini_api_key:
        print("Gemini API key missing. Pass --gemini-api-key or set GEMINI_API_KEY.", file=sys.stderr)
        return 2

    left_label = (f"{args.groq_model} (stored)" if args.stored_llama else args.groq_model)
    labels = (left_label, gemini_model)

    driver = GraphDatabase.driver(
        config.neo4j.uri, auth=(config.neo4j.user, config.neo4j.password)
    )
    gemini_client = create_llm_client(args.gemini_api_key, settings)
    groq_client = None if args.stored_llama else Groq(api_key=groq_key)

    try:
        with driver.session(database=config.neo4j.database) as session:
            articles = [dict(r) for r in session.run(ARTICLE_QUERY, limit=args.n)]
            if not articles:
                print("No M&A-relevant articles with deals matched the query.", file=sys.stderr)
                return 1

            print(f"Comparing {left_label} vs {gemini_model} on {len(articles)} article(s)")
            if args.stored_llama:
                print("  (llama side read from stored Deal nodes — extracted under an "
                      "older prompt revision)")

            records = []
            for i, article in enumerate(articles, 1):
                prompt = build_prompt(article["title"], article["content"])
                llama = (
                    fetch_stored_deal(session, article["id"]) if args.stored_llama
                    else call_model(groq_client, args.groq_model, prompt)
                )
                record = {
                    "id": article["id"],
                    "title": article["title"],
                    "llama": llama,
                    "gemini": call_model(gemini_client, gemini_model, prompt),
                }
                records.append(record)
                print_article(i, len(articles), record, labels, args.stored_llama)
    finally:
        driver.close()

    print_summary(records, labels, args.stored_llama)

    if args.dump:
        Path(args.dump).write_text(json.dumps(records, indent=2, default=str))
        print(f"Full results written to {args.dump}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
