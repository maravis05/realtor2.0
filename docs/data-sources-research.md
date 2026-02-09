# Real Estate Data Sources Research

*Compiled 2026-02-09*

The goal: automatically get full Zillow listing data (price, beds, baths, sqft, lot size, year built, HOA, garage, basement, fireplace) into a spreadsheet, triggered by email alerts.

---

## Why Not Scrape Zillow Directly?

Zillow uses PerimeterX (now HUMAN Security) anti-bot protection. From a headless server:

- Direct HTTP (httpx, curl_cffi with Chrome TLS impersonation): **403 Forbidden**
- Playwright headless + stealth patches: **captcha page**
- Session-based approaches (homepage first for cookies): works intermittently, IP gets flagged after a few attempts

Zillow's ToS explicitly prohibit automated scraping. Practical risk for personal use is low (IP blocking is the main enforcement), but it's a fragile foundation.

---

## Zillow's Official API — Dead

| What | Status |
|------|--------|
| ZAWS (Zillow API Web Services) | **Deprecated Sept 2021** |
| ZTRAX (transaction data) | **Discontinued Sept 2023** |
| Replacement: Bridge Interactive | Invite-only, commercial/brokerage use. Not accessible for personal projects. |

Portal: https://www.zillowgroup.com/developers/
Bridge: https://www.bridgeinteractive.com/developers/zillow-group-data/

---

## Recommended: RentCast API

**Website:** https://www.rentcast.io/api
**Docs:** https://developers.rentcast.io/reference/property-data-schema

### Why it's the best fit
- 140M+ property records across all 50 states
- Lookup by **address** (which Zillow alert emails provide)
- Has **every field we need** in structured form:

| Our Field | RentCast Field | Available? |
|-----------|---------------|------------|
| Price | listing price | Yes |
| Beds | bedrooms | Yes |
| Baths | bathrooms | Yes |
| SqFt | squareFootage | Yes |
| Lot size | lotSize | Yes |
| Year built | yearBuilt | Yes |
| HOA | hoa.fee | Yes |
| Garage | garage, garageSpaces, garageType | Yes |
| Fireplace | fireplace, fireplaceType | Yes |
| Basement | foundationType | Yes (inferred) |

### Pricing

| Plan | Cost/mo | Requests/mo | Overage |
|------|---------|-------------|---------|
| **Developer (Free)** | **$0** | **50** | $0.20/req |
| Foundation | $74 | 1,000 | $0.06/req |
| Growth | $199 | 5,000 | $0.03/req |
| Scale | $449 | 25,000 | $0.015/req |

50 free requests/month is likely sufficient for daily email alerts (~1-5 new listings/day).

### Integration plan
```
Gmail alert → extract addresses + ZPIDs from email HTML
           → RentCast API lookup by address
           → score against weighted matrix
           → write to Google Sheets
```

No scraping. No anti-bot issues. No legal gray area.

---

## Alternatives Considered

### Unofficial Zillow APIs on RapidAPI

Third-party scraping wrappers that expose Zillow data through an API. **Not official — can break anytime.**

| API | Free Tier | Lookup By | Notes |
|-----|-----------|-----------|-------|
| **Real-Time Zillow Data** (letscrape) | Yes (limited) | ZPID, address | Most popular. Full property details. |
| **zillow56** (s.mahmoud97) | 30 req/mo | ZPID | Straightforward property details |
| **Zillow.com API** (apimaker) | — | — | **Deprecated Dec 2025** |

Links:
- https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-zillow-data
- https://rapidapi.com/s.mahmoud97/api/zillow56

### Scraping-as-a-Service

These companies handle anti-bot, proxies, and CAPTCHAs for you.

| Service | Zillow Support | Pricing | Notes |
|---------|---------------|---------|-------|
| **Apify** | Dedicated Zillow actors | ~$0.25/2K results + free trial | Best value. maxcopell/zillow-scraper actor. |
| **Bright Data** | Built-in scraper + datasets | Pay-per-result, 20 free calls | 98.4% success rate. Pre-scraped datasets at $250/100K records. |
| **HasData** | Zillow Scraper API | 1K free calls, then $0.75-2.45/1K rows | 50+ fields per listing |
| **Oxylabs** | Scraper API | From $8/GB | Free trial available |
| **ScrapFly** | General | $30/mo for 200K basic | Slow for Zillow (~19s/req) |

Links:
- https://apify.com/maxcopell/zillow-scraper
- https://brightdata.com/products/web-scraper/zillow
- https://hasdata.com/scrapers/zillow

### Enterprise Data APIs

Overkill for personal use but worth knowing about.

| API | Coverage | Pricing | Notes |
|-----|----------|---------|-------|
| **ATTOM Data** | 158M+ properties, 9K attributes each | Enterprise/custom (contact sales) | Most comprehensive. Acquired Estated. |
| **BatchData** | 150M+ properties, 240+ fields | $0.01/call or ~$500/mo | |
| **Mashvisor** | Investment-focused | $299-599/mo for 100-250 req | Expensive. Missing feature-level fields. |
| **Datafiniti** | 122M+ properties | Custom pricing | Less commonly used |

### No-Code / Low-Code Tools

| Tool | What It Does | Automation Level | Cost |
|------|-------------|-----------------|------|
| **Browse AI** | Pre-built Zillow monitoring robots → Sheets | Fully automatic monitoring | Free tier + paid |
| **Bardeen AI** | Browser extension, scrapes Zillow → Sheets | Semi-auto (requires browser visit) | Free tier + Pro |
| **n8n** (self-hosted) | Workflow engine with Zillow templates | Fully automatic | Free (self-hosted) + scraping API cost |
| **API Connector** (Sheets add-on) | Calls RapidAPI Zillow from inside Sheets | Manual trigger | Free + RapidAPI sub |
| **Parseur / Mailparser** | Parse Zillow email alerts → Sheets | Automatic (email trigger) | Paid plans |

Links:
- https://www.browse.ai/site/zillow
- https://www.bardeen.ai/integrations/zillow
- https://n8n.io/workflows/ (search "zillow")

### Browser Extensions

Require manually visiting Zillow pages. Not automatable.

| Extension | Output | Fields | Notes |
|-----------|--------|--------|-------|
| **Z Real Estate Scraper** | CSV, Google Sheets | Price, address, beds, baths, sqft, year built, agent | Active as of Jan 2026 |
| **Zillow Data Exporter** (Property Data Labs) | CSV, JSON, Excel | 40+ fields per listing | Credit-based |

### Open Source (GitHub)

| Project | Approach | Notes |
|---------|----------|-------|
| omkarcloud/zillow-scraper | Cloud-based scraping | Most popular. Paid tier after Dec 2025. |
| DarienNouri/Fast-Zillow-API-Scraper | Internal API extraction | Academic/research project |
| scrapehero-code/zillow-scraper | Web scraping with Python | Basic |
| luminati-io/zillow-scraper (Bright Data) | Free tool + enterprise API | |

---

## Decision Matrix

| Approach | Cost | Reliability | All Fields? | Fully Automatic? | Legal? |
|----------|------|------------|-------------|-----------------|--------|
| **RentCast API** | Free (50/mo) | High | Yes | Yes | Yes |
| RapidAPI (unofficial) | Free (30-50/mo) | Medium (can break) | Yes | Yes | Gray area |
| Apify | ~pennies | Medium-High | Yes | Yes | Gray area |
| Direct scraping | Free | Low (blocked) | Yes | Yes | Gray area |
| Browse AI | Free tier | Medium-High | Most | Yes | Gray area |
| Email parsing only | Free | High | **No** (missing lot, HOA, features) | Yes | Yes |
| Browser extension | Free | High | Yes | **No** (manual) | Yes |

**Winner: RentCast API** — free tier covers our volume, every field available, fully automatable, legally clean.
