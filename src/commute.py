"""Google Maps Distance Matrix API client for commute time lookups."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"


def get_commute_times(
    origin: str,
    destinations: dict[str, str],
    api_key: str,
) -> dict[str, int]:
    """Look up drive times from origin to multiple destinations in one API call.

    Args:
        origin: Property address or "lat,lng" string.
        destinations: Mapping of label to address, e.g. {"Work": "123 Office St"}.
        api_key: Google Maps API key.

    Returns:
        Dict of {label: minutes}, omitting destinations that failed.
        Returns empty dict on any error.
    """
    if not destinations:
        return {}

    labels = list(destinations.keys())
    dest_string = "|".join(destinations.values())

    try:
        resp = httpx.get(
            BASE_URL,
            params={
                "origins": origin,
                "destinations": dest_string,
                "key": api_key,
                "mode": "driving",
                "departure_time": "now",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK":
            logger.warning("Distance Matrix API status: %s", data.get("status"))
            return {}

        results: dict[str, int] = {}
        elements = data.get("rows", [{}])[0].get("elements", [])

        for label, element in zip(labels, elements):
            if element.get("status") == "OK":
                seconds = element["duration"]["value"]
                results[label] = round(seconds / 60)
            else:
                logger.warning(
                    "Commute to %s failed: %s", label, element.get("status")
                )

        return results

    except httpx.HTTPStatusError as e:
        logger.error("Distance Matrix HTTP error: %d", e.response.status_code)
        return {}
    except Exception as e:
        logger.error("Distance Matrix request failed: %s", e)
        return {}
