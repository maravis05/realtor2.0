# Realtor 2.0

Automated Zillow property evaluation pipeline. Monitors Gmail for Zillow alert emails, enriches listings via the RentCast API, looks up commute times via Google Maps, scores them against a configurable weighted matrix, and ranks them by **value ratio** (score per $100k) in Google Sheets.

## How It Works

```
Cron (5x daily)
  |
  v
Gmail IMAP ──> Extract listings from Zillow alert emails
  |               (ZPID, address, price per listing)
  v
Dedup ────────> Skip ZPIDs already in Google Sheet
  |
  v
RentCast API ─> Enrich with beds, baths, sqft, lot, features, taxes, etc.
  |
  v
Google Maps ──> Look up drive times to configured destinations
  |
  v
Scorer ───────> Score against weighted matrix, compute value ratio
  |               value_ratio = score / (price / $100k)
  v
Sheets ───────> Write to Listings tab + rebuild ranked Scores tab
```

Every run re-scores **all** historical listings, so changes to `scoring.yaml` retroactively apply without losing any data.

## What You'll Need

| Service | Cost | Purpose |
|---------|------|---------|
| **Gmail** | Free | Receives Zillow alert emails |
| **RentCast API** | Free (50 lookups/month) | Property data enrichment |
| **Google Sheets API** | Free | Database / dashboard |
| **Google Maps API** | Free ($200/month credit) | Commute time lookups (optional) |

Total cost for typical use: **$0/month**.

## Quick Start

```bash
# 1. Clone and configure
cp config/config.yaml.example config/config.yaml
# Edit config.yaml with your API keys (see Setup below)

# 2. Install dependencies
pip install pyyaml httpx beautifulsoup4 lxml gspread google-auth

# 3. Run
python -m src.main

# 4. (Optional) Install cron for automated runs
bash setup_cron.sh
```

## Project Structure

```
realtor2.0/
├── src/
│   ├── main.py              Pipeline orchestrator
│   ├── email_monitor.py     Gmail IMAP polling, Zillow email parsing
│   ├── rentcast.py          RentCast API client
│   ├── commute.py           Google Maps Distance Matrix client
│   ├── parser.py            RentCast JSON -> Property dataclass
│   ├── scorer.py            Weighted scoring engine
│   └── sheets.py            Google Sheets two-tab database
├── tests/                   82 test cases
├── config/
│   ├── config.yaml.example  Configuration template
│   ├── scoring.yaml         Scoring matrix (edit this!)
│   └── credentials/         Google service account key (gitignored)
├── logs/                    Pipeline logs (gitignored)
└── setup_cron.sh            Cron job installer
```

## Setup

### 1. Configuration

```bash
cp config/config.yaml.example config/config.yaml
```

Then fill in your credentials. See `config.yaml.example` for documentation on each field.

### 2. Google Sheets

1. Create a Google Cloud project and enable the **Sheets API** and **Drive API**.
2. Create a service account and download the JSON key to `config/credentials/`.
3. Create a new Google Sheets spreadsheet.
4. Share the spreadsheet with the service account email (Editor access).
5. Copy the spreadsheet ID into `config.yaml`.

The pipeline automatically creates **Listings** and **Scores** tabs on first run.

### 3. Gmail

1. Enable IMAP in Gmail settings (Settings > See all settings > Forwarding and POP/IMAP).
2. Enable 2-factor authentication on the Google account.
3. Generate an [app password](https://myaccount.google.com/apppasswords) and paste it into `config.yaml`.
4. Set up [Zillow email alerts](https://www.zillow.com/howto/SetAlerts.htm) for your desired search criteria.

### 4. Google Maps (Optional)

Commute scoring is optional. To enable it:

1. In your Google Cloud project, enable the **Distance Matrix API**.
2. Create an API key at https://console.cloud.google.com/apis/credentials.
3. Add it to `config.yaml` with your commute destinations:

```yaml
google_maps:
  api_key: "YOUR_KEY"
  destinations:
    - label: "Work"
      address: "123 Main St, Your City, ST 00000"
    - label: "School"
      address: "456 Oak Ave, Your City, ST 00000"
```

All destinations are looked up in a **single API call** per property. Cost is ~$0.005 per destination per property, covered by Google's $200/month free credit.

### 5. RentCast

Sign up at https://www.rentcast.io/api and paste your API key into `config.yaml`. The free tier allows 50 property lookups per month.

### 6. Cron (Automated Scheduling)

```bash
bash setup_cron.sh
```

Installs a cron job that runs at **7am, 11am, 3pm, 7pm, 11pm** daily.

## Scoring System

The scoring system is fully configurable via `config/scoring.yaml`. It answers one question: **"How much of what I want does this house have?"**

Price is deliberately excluded from the score. Instead, it's used as the denominator in a **value ratio**:

```
value_ratio = score / (price / $100,000)
```

This ranks houses by bang-for-buck. A $200k house scoring 50 (ratio 25.0) outranks a $400k house scoring 80 (ratio 20.0).

### Scoring Modes

The scorer supports three normalization modes, so you can model different types of preferences:

| Mode | Config | Example |
|------|--------|---------|
| **Linear** | `direction: higher_is_better` | Lot size: more land = higher score |
| **Threshold** | `scoring: threshold` | Commute: full points under 20 min, zero above 46, linear between |
| **Peak** | `scoring: peak` | Bedrooms: 3 is ideal, 2 and 4 score lower, 5 scores zero |

### Default Configuration

The included `scoring.yaml` is tuned for a rural/suburban home search. Adjust the weights, thresholds, and bonuses to match your own priorities:

**Criteria (weighted, total = 100):**

| Criterion | Weight | Type | Default Config |
|-----------|--------|------|----------------|
| `lot_size_acres` | 40 | Linear | 0.5 to 5.0 acres |
| `commute` | 25 | Threshold | Full <=20 min, zero >=46 min |
| `bedrooms` | 20 | Peak | Ideal = 3 |
| `bathrooms` | 15 | Linear | 0 to 2 |

**Bonuses (flat points added to score):**

| Feature | Points |
|---------|--------|
| `has_garage` | +15 |
| `has_basement` | +5 |
| `has_fireplace` | +3 |

Final score = min(100, weighted_average + bonus_total).

To customize: edit `scoring.yaml` and run the pipeline. All existing listings are re-scored automatically.

### Adding New Criteria

The scorer reads criteria dynamically from the config. To add a new criterion:

1. Add it to `scoring.yaml` with a weight and normalization config
2. Add a mapping in `scorer.py:_get_property_value()` that returns the value from the `Property` dataclass
3. The Property dataclass already captures 30+ fields from RentCast -- most are available without any API changes

## Google Sheets Output

### Listings Tab

Append-only raw data. Every property ever processed is stored here with 32 columns of data (address, price, beds, baths, sqft, lot, features, taxes, commute times, etc.). This tab is never modified after a row is written.

### Scores Tab

Rebuilt from scratch every run. Sorted by value ratio descending with color-coding:

| Score | Color |
|-------|-------|
| >= 75 | Green |
| >= 50 | Yellow |
| < 50 | No highlight |

Columns adapt dynamically based on your configured commute destinations.

## Tests

```bash
python -m pytest tests/ -v
```

82 test cases covering email parsing, property parsing, all three scoring modes, commute lookups, value ratio calculation, and API error handling.

## Example Log Output

```
07:00:01 [INFO] === Pipeline run a3f8c21e starting ===
07:00:02 [INFO] Commute lookups enabled: Work, School
07:00:02 [INFO] Listings tab has 42 existing ZPIDs
07:00:04 [INFO] Extracted 6 unique listing(s) from emails
07:00:04 [INFO] Skipped 3 listing(s) already in sheet
07:00:04 [INFO] 3 new listing(s) to look up (3 API call(s))
07:00:05 [INFO] [1/3] Processing ZPID 12345678 -- 100 Example Rd, Anytown, NH
07:00:05 [INFO] [1/3]  Commutes: {'Work': 14, 'School': 29}
07:00:06 [INFO] [1/3]  100 Example Rd, Anytown, NH 03000 | $375,000 | 3bd/2.0br | 1,850 sqft | 1.5 acres
07:00:06 [INFO] [1/3]  Stored in Listings
...
07:00:12 [INFO] Scores tab rebuilt with 45 listings
07:00:12 [INFO] Top value ratios:
07:00:12 [INFO]   ratio=25.30  score=63.2  50 Sample St, Somewhere, NH  $250,000
07:00:12 [INFO]   ratio=22.10  score=82.5  100 Example Rd, Anytown, NH  $375,000
07:00:12 [INFO]   ratio=19.80  score=68.9  200 Demo Ln, Otherville, NH  $348,000
07:00:12 [INFO] Run a3f8c21e summary -- New: 6 | Added: 3 | Dup: 3 | Failed: 0 | Total: 45
07:00:12 [INFO] === Pipeline run a3f8c21e finished in 11.4s ===
```

Logs are written to `logs/pipeline.log` with rotation (5 MB x 5 files).
