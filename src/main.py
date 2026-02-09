"""Pipeline orchestrator: email → RentCast API → parse → score → sheet."""

from __future__ import annotations

import logging
import platform
import sys
import time
import traceback
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

from src.commute import get_commute_times
from src.email_monitor import ListingLink, connect, disconnect, fetch_new_listing_urls
from src.parser import Property, parse_from_rentcast
from src.rentcast import lookup_property
from src.scorer import ScoreBreakdown, load_scoring_config, score_property
from src.sheets import SheetsClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_config() -> dict:
    config_path = PROJECT_ROOT / "config" / "config.yaml"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found. Copy config.yaml.example and fill in values.")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def _setup_logging(log_file: str | None) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Console: INFO and above, compact format
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # File: DEBUG and above, full detail, with rotation
    if log_file:
        log_path = PROJECT_ROOT / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=5,             # keep 5 old files (~25 MB total)
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        ))
        root.addHandler(file_handler)


def run() -> None:
    run_id = uuid.uuid4().hex[:8]
    t_start = time.monotonic()

    config = _load_config()
    _setup_logging(config.get("pipeline", {}).get("log_file"))

    logger = logging.getLogger("realtor")
    logger.info(
        "=== Pipeline run %s starting | Python %s | %s ===",
        run_id, platform.python_version(), platform.node(),
    )

    try:
        _run_pipeline(config, logger, run_id)
    except Exception:
        logger.critical("Unhandled exception in pipeline run %s:\n%s", run_id, traceback.format_exc())
    finally:
        elapsed = time.monotonic() - t_start
        logger.info("=== Pipeline run %s finished in %.1fs ===\n", run_id, elapsed)


def _run_pipeline(config: dict, logger: logging.Logger, run_id: str) -> None:
    scoring_config = load_scoring_config(PROJECT_ROOT / "config" / "scoring.yaml")
    max_per_run = config.get("pipeline", {}).get("max_listings_per_run", 20)

    # RentCast API key
    rentcast_key = config.get("rentcast", {}).get("api_key", "")
    if not rentcast_key:
        logger.error("No RentCast API key configured. Add rentcast.api_key to config.yaml.")
        return

    # Google Maps commute config
    gmaps_cfg = config.get("google_maps", {})
    gmaps_key = gmaps_cfg.get("api_key", "")
    destinations: dict[str, str] = {}
    commute_labels: list[str] = []
    if gmaps_key and gmaps_cfg.get("destinations"):
        for dest in gmaps_cfg["destinations"]:
            label = dest.get("label", "")
            address = dest.get("address", "")
            if label and address:
                destinations[label] = address
                commute_labels.append(label)
        logger.info("Commute lookups enabled: %s", ", ".join(commute_labels))
    else:
        logger.warning("No google_maps config — commute times will not be looked up")

    # --- 1. Connect to Google Sheets (our database of record) ---
    sheets_cfg = config["google_sheets"]
    logger.info("Connecting to Google Sheet %s", sheets_cfg["spreadsheet_id"])
    try:
        sheets = SheetsClient(
            credentials_file=PROJECT_ROOT / sheets_cfg["credentials_file"],
            spreadsheet_id=sheets_cfg["spreadsheet_id"],
        )
    except Exception:
        logger.error("Failed to connect to Google Sheets:\n%s", traceback.format_exc())
        return

    existing_zpids = sheets.get_existing_zpids()
    logger.info("Listings tab has %d existing ZPIDs", len(existing_zpids))

    # --- 2. Fetch listing data from email ---
    gmail_cfg = config["gmail"]
    logger.info("Connecting to Gmail as %s", gmail_cfg["email"])
    try:
        imap = connect(gmail_cfg["email"], gmail_cfg["app_password"])
    except Exception:
        logger.error("Failed to connect to Gmail:\n%s", traceback.format_exc())
        return

    try:
        links: list[ListingLink] = fetch_new_listing_urls(imap)
    except Exception:
        logger.error("Failed to fetch emails:\n%s", traceback.format_exc())
        return
    finally:
        disconnect(imap)
        logger.debug("IMAP connection closed")

    # --- 3. Filter to only new listings, then look up via RentCast ---
    # Dedup against our sheet BEFORE making any API calls
    new_links = [l for l in links if l.zpid not in existing_zpids]
    skipped_dup = len(links) - len(new_links)
    if skipped_dup:
        logger.info("Skipped %d listing(s) already in sheet", skipped_dup)

    added = 0
    failed = 0

    if not new_links:
        logger.info("No new listings to look up.")
    else:
        to_process = new_links[:max_per_run]
        logger.info(
            "%d new listing(s) to look up (%d API call(s))",
            len(to_process), len(to_process),
        )
        for i, link in enumerate(to_process):
            step = f"[{i + 1}/{len(to_process)}]"
            logger.info("%s Processing ZPID %s — %s", step, link.zpid, link.address or link.url)

            address = link.address
            if not address:
                logger.warning("%s  No address extracted, skipping", step)
                failed += 1
                continue

            logger.info("%s  Looking up: %s", step, address)
            property_data = lookup_property(address, rentcast_key)
            if not property_data:
                logger.warning("%s  RentCast lookup failed", step)
                failed += 1
                continue

            # Parse into Property
            try:
                prop = parse_from_rentcast(property_data, link.zpid, link.url, link.price)
            except Exception:
                logger.error("%s  Parse exception:\n%s", step, traceback.format_exc())
                failed += 1
                continue

            # Look up commute times
            if destinations and prop.address:
                commutes = get_commute_times(prop.address, destinations, gmaps_key)
                if commutes:
                    prop.commute_minutes = commutes
                    logger.info("%s  Commutes: %s", step, commutes)

            logger.info(
                "%s  %s | $%s | %dbd/%sbr | %s sqft | %.1f acres",
                step, prop.address, f"{prop.price:,}",
                prop.bedrooms, prop.bathrooms,
                f"{prop.sqft:,}", prop.lot_size_acres,
            )

            # Add raw data to Listings tab
            try:
                sheets.add_listing(prop)
                added += 1
                existing_zpids.add(link.zpid)
                logger.info("%s  Stored in Listings", step)
            except Exception:
                logger.error("%s  Failed to write to Listings:\n%s", step, traceback.format_exc())
                failed += 1

        logger.info(
            "Lookup phase — Added: %d | Dup: %d | Failed: %d",
            added, skipped_dup, failed,
        )

    # --- 4. Re-score ALL listings and rebuild Scores tab ---
    logger.info("Re-scoring all listings with current scoring matrix")
    all_properties = sheets.read_all_listings()
    logger.info("Read %d listings from Listings tab", len(all_properties))

    # Backfill commute data for existing listings missing it
    if destinations:
        backfilled = 0
        for prop in all_properties:
            if not prop.commute_minutes and prop.address:
                commutes = get_commute_times(prop.address, destinations, gmaps_key)
                if commutes:
                    prop.commute_minutes = commutes
                    backfilled += 1
                time.sleep(0.1)
        if backfilled:
            logger.info("Backfilled commute data for %d listing(s)", backfilled)

    scored: list[tuple[Property, ScoreBreakdown]] = []
    for prop in all_properties:
        breakdown = score_property(prop, config=scoring_config)
        scored.append((prop, breakdown))

    scored.sort(key=lambda x: x[1].value_ratio, reverse=True)

    try:
        sheets.rebuild_scores(scored, commute_labels=commute_labels)
    except Exception:
        logger.error("Failed to rebuild Scores tab:\n%s", traceback.format_exc())

    # --- Summary ---
    top3 = scored[:3]
    if top3:
        logger.info("Top value ratios:")
        for prop, bd in top3:
            logger.info(
                "  ratio=%.2f  score=%.1f  %s  $%s",
                bd.value_ratio, bd.final_score, prop.address, f"{prop.price:,}",
            )

    logger.info(
        "Run %s summary — New emails: %d | Added: %d | Dup: %d | Failed: %d | Total scored: %d",
        run_id, len(links), added, skipped_dup, failed, len(scored),
    )


if __name__ == "__main__":
    run()
