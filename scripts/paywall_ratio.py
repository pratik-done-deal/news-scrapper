"""
Retroactive free-vs-paid (paywall) ratio per source.

Read-only. Does NOT touch the scraper or write anything back to Neo4j.
It inspects the `content` already stored on each Article node and classifies
it as "paid" (paywalled / truncated) or "free" (full body) using two signals:

  1. Paywall marker phrases in the content/title (strong signal).
  2. Very short body length (weak signal) — likely a truncated teaser.

Usage:
    python scripts/paywall_ratio.py [--min-chars 600] [--source NAME]

Env (read from .env / environment): NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE
"""
import argparse
import re
import sys
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ConfigError, add_config_arguments, load_config

# Strong paywall signals — phrases sites inject when the full body is gated.
_PAYWALL_MARKERS = [
    r"subscribe to read",
    r"already a subscriber",
    r"sign in to continue",
    r"to continue reading",
    r"continue reading",
    r"this (?:is a |article is )?premium",
    r"premium (?:article|content|story)",
    r"et\s*prime",
    r"for unlimited access",
    r"unlimited digital access",
    r"subscribe now",
    r"become a (?:member|subscriber)",
    r"unlock this (?:story|article)",
    r"members only",
    r"start your subscription",
]
_PAYWALL_RE = re.compile("|".join(_PAYWALL_MARKERS), re.IGNORECASE)


def classify(content: str, title: str, min_chars: int) -> tuple[str, str]:
    """Return (label, reason) where label is 'paid' or 'free'."""
    text = content or ""
    if _PAYWALL_RE.search(text) or _PAYWALL_RE.search(title or ""):
        return "paid", "paywall marker"
    if len(text.strip()) < min_chars:
        return "paid", f"short body (<{min_chars} chars)"
    return "free", "full body"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-chars", type=int, default=600,
                    help="bodies shorter than this are treated as truncated/paid")
    ap.add_argument("--source", default=None, help="limit to one source name")
    add_config_arguments(ap, only=("neo4j",))
    args = ap.parse_args()

    config = load_config(args)
    try:
        password = config.require_neo4j_password()
    except ConfigError as exc:
        raise SystemExit(f"Error: {exc}")

    uri = config.neo4j.uri
    user = config.neo4j.user
    database = config.neo4j.database

    driver = GraphDatabase.driver(uri, auth=(user, password))
    cypher = "MATCH (a:NewsArticle) RETURN a.source AS source, a.title AS title, a.content AS content"
    if args.source:
        cypher = ("MATCH (a:NewsArticle) WHERE a.source = $source "
                  "RETURN a.source AS source, a.title AS title, a.content AS content")

    # per-source tallies: {source: [free, paid]}
    stats: dict[str, list[int]] = {}
    reasons: dict[str, int] = {}
    with driver.session(database=database) as session:
        result = session.run(cypher, source=args.source)
        for rec in result:
            source = rec["source"] or "(unknown)"
            label, reason = classify(rec["content"], rec["title"], args.min_chars)
            stats.setdefault(source, [0, 0])
            stats[source][0 if label == "free" else 1] += 1
            if label == "paid":
                reasons[reason] = reasons.get(reason, 0) + 1
    driver.close()

    if not stats:
        print("No articles found.")
        return

    name_w = max(len(s) for s in stats) + 2
    print(f"{'SOURCE':<{name_w}}{'TOTAL':>8}{'FREE':>8}{'PAID':>8}{'PAID %':>9}")
    print("-" * (name_w + 33))
    tot_free = tot_paid = 0
    for source in sorted(stats, key=lambda s: -sum(stats[s])):
        free, paid = stats[source]
        total = free + paid
        tot_free += free
        tot_paid += paid
        pct = (paid / total * 100) if total else 0
        print(f"{source:<{name_w}}{total:>8}{free:>8}{paid:>8}{pct:>8.1f}%")
    grand = tot_free + tot_paid
    print("-" * (name_w + 33))
    gpct = (tot_paid / grand * 100) if grand else 0
    print(f"{'ALL SOURCES':<{name_w}}{grand:>8}{tot_free:>8}{tot_paid:>8}{gpct:>8.1f}%")

    print("\nPaid classified by reason:")
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>6}  {reason}")


if __name__ == "__main__":
    main()
