"""
Validation script — compares AI filter vs keyword filter side by side.
No data is written to the database.

Run:
    python validate_filter.py
"""

import json
import os
import sys

from dotenv import load_dotenv
from groq import Groq

from src.agent import SCRAPER_REGISTRY
from src.paths import ENV_PATH, load_settings, load_sources_config
from src.processor.filter import NewsFilter

load_dotenv(ENV_PATH)

AI_PROMPT = """\
You are a financial news classifier. Determine if the article is about M&A or business deal activity.

This INCLUDES:
- Company acquisitions or mergers
- Funding rounds (seed, Series A/B/C, growth equity)
- Joint ventures with financial transactions
- Asset sales or divestitures
- Private equity or venture capital investments
- Strategic partnerships with a disclosed financial component

This EXCLUDES:
- General market commentary or stock price movements
- Product launches or earnings reports (unless tied to a deal)
- Regulatory or policy news not tied to a transaction

Respond ONLY with valid JSON: {{"is_ma_relevant": true or false, "reason": "one short sentence"}}

Title: {title}
Content (truncated): {content}
"""

SEP = "─" * 70


def ai_check(client: Groq, model: str, title: str | None, content: str | None) -> tuple[bool, str]:
    try:
        prompt = AI_PROMPT.format(
            title=title or "(no title)",
            content=(content or "")[:2000],
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=80,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return bool(result.get("is_ma_relevant", False)), result.get("reason", "")
    except Exception as e:
        return False, f"AI error: {e}"


def main() -> None:
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        sys.exit("GROQ_API_KEY not set in .env")

    settings = load_settings()
    sources = load_sources_config()["sources"]

    kw_filter = NewsFilter()
    groq_client = Groq(api_key=groq_api_key)
    model = settings["groq"]["model"]
    max_articles = settings["scraping"]["max_articles_per_source"]
    scraper_kwargs = {
        "request_timeout": settings["scraping"]["request_timeout"],
        "delay": settings["scraping"]["delay_between_requests"],
    }
    scrapers = {}

    total = agree = ai_yes_kw_no = ai_no_kw_yes = 0

    for source in sources:
        scraper_key = source.get("scraper", "et")
        if scraper_key not in scrapers:
            scrapers[scraper_key] = SCRAPER_REGISTRY[scraper_key](**scraper_kwargs)
        scraper = scrapers[scraper_key]

        print(f"\n{'=' * 70}")
        print(f"  SOURCE: {source['name']}")
        print(f"{'=' * 70}")

        links = scraper.get_article_links(
            source_url=source["url"],
            domain=source["domain"],
            link_contains=source["link_contains"],
            max_articles=max_articles,
        )

        if not links:
            print("  No links found — source may be paywalled or unreachable.")
            continue

        print(f"  {len(links)} links found\n")

        for url in links:
            title, content, _published_date = scraper.extract_article(url)

            if not content:
                print(f"  SKIP (no content): {url}\n")
                continue

            ai_result, ai_reason = ai_check(groq_client, model, title, content)
            kw_result = kw_filter.is_ma_funding_relevant(title, content)

            total += 1
            if ai_result == kw_result:
                agree += 1
                match_label = "✅ AGREE"
            elif ai_result and not kw_result:
                ai_yes_kw_no += 1
                match_label = "❌ DISAGREE  ← AI says relevant, keywords missed it"
            else:
                ai_no_kw_yes += 1
                match_label = "❌ DISAGREE  ← keywords too broad, AI says not relevant"

            print(f"URL:      {url}")
            print(f"Title:    {title or '(no title)'}")
            print(f"AI:       {'✅ relevant' if ai_result else '❌ not relevant'}  [{ai_reason}]")
            print(f"Keywords: {'✅ relevant' if kw_result else '❌ not relevant'}")
            print(f"Match:    {match_label}")
            print(SEP)

    print(f"\n{'=' * 70}")
    print("  FINAL SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total articles checked : {total}")
    print(f"  Both agree             : {agree}  ({agree * 100 // total if total else 0}%)")
    print(f"  AI=yes, KW=no          : {ai_yes_kw_no}  ← add these keywords")
    print(f"  AI=no,  KW=yes         : {ai_no_kw_yes}  ← keywords too broad")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
