# M&A News Intelligence Platform — Product Overview

> **For:** Non-technical stakeholders
> **Purpose:** Understand what the platform does, how information flows through it, and what value it delivers

---

## What Is This Product?

This platform **automatically reads financial news, identifies merger and acquisition (M&A) activity, and turns unstructured news articles into organized, searchable deal intelligence** — without anyone having to manually read through hundreds of articles.

Think of it as a tireless analyst that monitors Indian financial news sources 24/7, spots deals, and neatly files them for your team to query and analyze.

---

## The Problem It Solves

| Without This Platform | With This Platform |
|---|---|
| Analysts manually read news every day | News is automatically monitored and processed |
| Deals are discovered late or missed | Every relevant deal is captured as it's published |
| Data lives in emails and spreadsheets | All deals are in a searchable, structured database |
| Hard to spot trends across sectors | Analytics dashboards show patterns instantly |

---

## News Sources Monitored

The platform currently tracks **4 major Indian financial news sources**:

- Economic Times
- Financial Express
- CNBC TV18
- India Infoline

---

## How the Platform Works — The Big Picture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        NEWS SOURCES                                  │
│   Economic Times │ Financial Express │ CNBC TV18 │ India Infoline   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  Articles collected automatically
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     INTELLIGENCE ENGINE                              │
│                                                                      │
│   1. Read article   →   2. Is it M&A related?   →   3. Extract deal │
│                              (Yes / No)               details        │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  Structured deal data
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       DEAL DATABASE                                  │
│          Articles  │  Deals  │  Companies  │  Relationships          │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     USER-FACING FEATURES                             │
│   Browse Deals │ Search Companies │ View Analytics │ Export Data     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Flow

### Step 1 — Collect News Articles

```
 ┌──────────────┐     Fetch latest articles     ┌──────────────────┐
 │  Scheduler   │ ──────────────────────────────▶│   News Websites  │
 │ (runs daily  │                                │ (ET, FE, CNBC,   │
 │  or on-demand│ ◀──────────────────────────────│  India Infoline) │
 └──────────────┘     Returns article content    └──────────────────┘
         │
         │  Saves raw articles
         ▼
 ┌──────────────┐
 │  Article     │  — Headline, full text, source, date, URL
 │  Storage     │
 └──────────────┘
```

The platform respects website rate limits (waits between requests) to ensure responsible scraping.

---

### Step 2 — Filter for M&A Relevance

```
 ┌──────────────────┐
 │  Raw Article     │
 │  (could be about │
 │  anything)       │
 └────────┬─────────┘
          │
          ▼
 ┌──────────────────────────────────────────┐
 │         AI RELEVANCE CHECK               │
 │                                          │
 │  "Does this article mention a merger,    │
 │   acquisition, investment, or deal?"     │
 └──────────────┬───────────────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
   ┌─────────┐      ┌──────────┐
   │  YES    │      │    NO    │
   │ Process │      │  Archive │
   │ further │      │ (stored  │
   └────┬────┘      │ but not  │
        │           │ analyzed)│
        │           └──────────┘
        ▼
 Moves to Step 3
```

---

### Step 3 — Extract Deal Details

```
 ┌──────────────────────────────────────────────────────────────┐
 │  AI reads the M&A article and extracts:                      │
 │                                                              │
 │   • Who is buying?          →  Acquirer Company              │
 │   • Who is being acquired?  →  Target Company                │
 │   • What type of deal?      →  Acquisition / Investment /    │
 │                                Merger / Partnership          │
 │   • What industry/sector?   →  Tech / Healthcare / Finance…  │
 │   • Deal amount (if stated) →  ₹ value                       │
 └──────────────────────────────────────────────────────────────┘
          │
          ▼
 ┌────────────────────┐
 │  Structured Deal   │  — Saved to database, linked to the
 │  Record Created    │    original article and both companies
 └────────────────────┘
```

---

### Step 4 — Users Access the Intelligence

Once deals are stored, your team can access them through five areas:

```
                    ┌──────────────────┐
                    │   Deal Database  │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────────┐
          │                  │                       │
          ▼                  ▼                       ▼
  ┌───────────────┐  ┌───────────────┐    ┌──────────────────┐
  │  Browse       │  │  Search       │    │  Analytics       │
  │  Articles     │  │  Companies    │    │  Dashboard       │
  │               │  │               │    │                  │
  │ Filter by:    │  │ Find a        │    │ • Deals by sector │
  │ • Date range  │  │ company and   │    │ • Top acquirers  │
  │ • News source │  │ see all their │    │ • Deal volume    │
  │ • M&A only    │  │ deals         │    │   over time      │
  └───────────────┘  └───────────────┘    └──────────────────┘

  ┌───────────────┐  ┌───────────────┐
  │  Browse       │  │  On-Demand    │
  │  Deals        │  │  Scraping     │
  │               │  │               │
  │ Filter by:    │  │ Trigger a     │
  │ • Sector      │  │ fresh scrape  │
  │ • Deal type   │  │ for any date  │
  │ • Company     │  │ range         │
  └───────────────┘  └───────────────┘
```

---

## Key Features at a Glance

### 1. Deal Discovery
Automatically identifies M&A deals from news — no manual reading required. Every deal is tagged with the companies involved, deal type, and sector.

### 2. Company Intelligence
Search any company name and instantly see all deals they've been part of — as a buyer, seller, or investor.

### 3. Analytics & Trends
See which sectors are the most active for deals, who the top acquirers are, and how deal volumes trend over time.

### 4. Article Archive
Every article that was read is stored with a flag indicating whether it was M&A-relevant — providing a full audit trail.

### 5. Flexible Scraping
The team can trigger a fresh news collection run at any time, targeting a specific date range if needed (e.g., "fetch everything from last week").

---

## What Gets Stored

```
┌────────────────────────────────────────────────────────────────┐
│                        DATABASE                                 │
│                                                                 │
│  ┌─────────────┐       ┌─────────────┐      ┌──────────────┐   │
│  │  ARTICLES   │  1:N  │    DEALS    │  N:M │  COMPANIES   │   │
│  │─────────────│───────│─────────────│──────│──────────────│   │
│  │ Headline    │       │ Deal Type   │      │ Company Name │   │
│  │ Full Text   │       │ Sector      │      │              │   │
│  │ Source      │       │ Amount      │      │ ← linked to  │   │
│  │ Date        │       │ Date        │      │   every deal │   │
│  │ URL         │       │             │      │   they're in │   │
│  │ M&A? Yes/No │       └─────────────┘      └──────────────┘   │
│  └─────────────┘                                                │
└────────────────────────────────────────────────────────────────┘

  One article can contain multiple deals.
  One deal involves two or more companies.
```

---

## Typical Day in the Life of This Platform

```
 Morning (Scheduled Run)
 ────────────────────────────────────────────────────────────────
  6:00 AM  →  Platform fetches latest articles from all 4 sources
  6:05 AM  →  AI reviews each article for M&A relevance
  6:10 AM  →  Relevant articles are processed; deals extracted
  6:15 AM  →  New deals appear in the database, ready to query

 During the Day (On-Demand)
 ────────────────────────────────────────────────────────────────
  Any time  →  Team queries deals by sector, company, or date
  Any time  →  Analytics dashboard reflects latest data
  Any time  →  Analyst triggers a manual scrape if needed
```

---

## Limitations & Boundaries

| What It Does Well | What It Doesn't Do |
|---|---|
| Detects publicly announced deals in news | Cannot access paywalled content |
| Extracts deal details when mentioned in text | Cannot verify deal amounts not stated in the article |
| Covers 4 major Indian financial news sources | Does not monitor global news sources (yet) |
| Near real-time when triggered | Scheduled runs depend on how often scraping is configured |

---

## Summary

This platform replaces hours of daily manual news monitoring with an automated pipeline that:

1. **Collects** news from major Indian financial sources
2. **Identifies** which articles are M&A-relevant using AI
3. **Extracts** structured deal data (who, what type, which sector)
4. **Stores** everything in a searchable database
5. **Surfaces** insights through browsing, search, and analytics

The result is faster deal discovery, a permanent structured record of M&A activity, and the ability to spot trends that would be invisible in raw news feeds.
