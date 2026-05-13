#!/usr/bin/env python3
"""
Test that every article fetched from Economic Times falls within the requested date range.

Usage:
    python test_date_range.py --start-date 2025-02-01 --end-date 2025-02-28
    python test_date_range.py --start-date 2025-02-01 --end-date 2025-02-28 --max-pages 3
"""

import argparse
import sys
from datetime import datetime, timezone, timedelta

from src.scraper.web_scraper import WebScraper

IST = timezone(timedelta(hours=5, minutes=30))

ET_SOURCE = {
    "url": "https://economictimes.indiatimes.com/news/company/corporate-trends",
    "domain": "economictimes.indiatimes.com",
    "link_contains": "/news/company/",
}

GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def to_ist(date_str: str, end_of_day: bool = False) -> datetime:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.replace(tzinfo=IST)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--end-date",   required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--max-pages",  type=int, default=3,
                        help="Listing pages to walk (default: 3)")
    parser.add_argument("--delay",      type=float, default=1.5,
                        help="Seconds between requests (default: 1.5)")
    args = parser.parse_args()

    start = to_ist(args.start_date)
    end   = to_ist(args.end_date, end_of_day=True)

    print(f"\nDate range : {args.start_date}  →  {args.end_date} (IST)")
    print(f"Max pages  : {args.max_pages}")
    print("-" * 60)

    scraper = WebScraper(request_timeout=30, delay=args.delay)

    # Step 1 — collect article URLs from listing pages
    print("\n[1] Collecting article links …")
    links = scraper.get_article_links_in_date_range(
        source_url=ET_SOURCE["url"],
        domain=ET_SOURCE["domain"],
        link_contains=ET_SOURCE["link_contains"],
        start_date=start,
        end_date=end,
        max_pages=args.max_pages,
    )
    print(f"    → {len(links)} links collected\n")

    if not links:
        print(f"{YELLOW}No links found. Try wider dates or more pages.{RESET}")
        sys.exit(1)

    # Step 2 — fetch each article and check its date
    print("[2] Fetching articles and checking dates …\n")

    passed = 0
    failed = 0
    no_date = 0

    for i, url in enumerate(links, 1):
        title, content, pub_date = scraper.extract_article(url)

        short_url = url.split("economictimes.indiatimes.com")[-1][:70]

        if pub_date is None:
            status = f"{YELLOW}NO DATE{RESET}"
            no_date += 1
        elif start <= pub_date <= end:
            status = f"{GREEN}PASS{RESET}  {pub_date.strftime('%Y-%m-%d %I:%M %p IST')}"
            passed += 1
        else:
            status = f"{RED}FAIL{RESET}  {pub_date.strftime('%Y-%m-%d %I:%M %p IST')}  ← outside range"
            failed += 1

        print(f"  [{i:>3}] {status}")
        print(f"         {short_url}")
        if not content:
            print(f"         {YELLOW}(no content extracted){RESET}")
        print()

    # Step 3 — summary
    total = len(links)
    print("-" * 60)
    print(f"Results : {total} articles fetched")
    print(f"  {GREEN}PASS   : {passed}{RESET}")
    print(f"  {RED}FAIL   : {failed}{RESET}  ← wrong date range")
    print(f"  {YELLOW}NO DATE: {no_date}{RESET}  ← date could not be extracted")
    print()

    if failed > 0:
        print(f"{RED}✗ {failed} article(s) were outside the requested date range.{RESET}")
        sys.exit(1)
    elif no_date == total:
        print(f"{YELLOW}⚠ Could not extract dates from any article. Check selectors.{RESET}")
        sys.exit(1)
    else:
        print(f"{GREEN}✓ All dated articles are within the requested range.{RESET}")


if __name__ == "__main__":
    main()
