"""RentCast API client for property lookups."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.rentcast.io/v1"


def lookup_property(address: str, api_key: str) -> dict | None:
    """Look up a property by address via /v1/properties.

    Returns the full property record (beds, baths, sqft, lot, year,
    features, HOA, etc.) or None on failure. One API call per property.
    """
    try:
        resp = httpx.get(
            f"{BASE_URL}/properties",
            params={"address": address},
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=15.0,
        )
        if resp.status_code == 404:
            logger.warning("No property record for %s", address)
            return None
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]
        return None
    except httpx.HTTPStatusError as e:
        logger.error("RentCast API error for %s: HTTP %d", address, e.response.status_code)
        return None
    except Exception as e:
        logger.error("RentCast API request failed for %s: %s", address, e)
        return None
