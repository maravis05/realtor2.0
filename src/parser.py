"""Parse property data from RentCast API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SQFT_PER_ACRE = 43_560


@dataclass
class Property:
    zpid: str = ""
    address: str = ""
    price: int = 0  # listing price from Zillow email
    bedrooms: int = 0
    bathrooms: float = 0.0
    sqft: int = 0
    lot_size_acres: float = 0.0
    year_built: int = 0
    hoa_monthly: int = 0
    has_garage: bool | None = None
    has_basement: bool | None = None
    has_fireplace: bool | None = None
    days_on_zillow: int = 0
    property_type: str = ""
    listing_url: str = ""
    # Additional fields from RentCast /v1/properties
    last_sale_price: int = 0
    last_sale_date: str = ""
    county: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    has_pool: bool = False
    has_cooling: bool = False
    has_heating: bool = False
    garage_spaces: int = 0
    floor_count: int = 0
    room_count: int = 0
    foundation_type: str = ""
    exterior_type: str = ""
    roof_type: str = ""
    property_tax: int = 0  # most recent year
    tax_assessment: int = 0  # most recent year
    commute_minutes: dict[str, int] = field(default_factory=dict)  # {"Work": 32, "Family": 28}


def _dig(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dict keys."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _most_recent_value(yearly_dict: dict | None, field: str = "total") -> int:
    """Extract the most recent year's value from a dict keyed by year strings."""
    if not yearly_dict or not isinstance(yearly_dict, dict):
        return 0
    try:
        latest_key = max(yearly_dict.keys())
        entry = yearly_dict[latest_key]
        if isinstance(entry, dict):
            return _safe_int(entry.get(field) or entry.get("value"))
        return _safe_int(entry)
    except (ValueError, TypeError):
        return 0


def parse_from_rentcast(
    data: dict,
    zpid: str,
    listing_url: str,
    listing_price: int = 0,
) -> Property:
    """Build a Property from a single RentCast /v1/properties response.

    Args:
        data: Response from /v1/properties endpoint.
        zpid: Zillow property ID from the email alert.
        listing_url: Original Zillow listing URL.
        listing_price: Current asking price extracted from Zillow email.
    """
    # Lot size: RentCast reports in sqft — convert to acres
    lot_sqft = _safe_float(_dig(data, "lotSize"))
    lot_acres = round(lot_sqft / SQFT_PER_ACRE, 2) if lot_sqft else 0.0

    # Features
    features = data.get("features", {}) or {}
    foundation = str(features.get("foundationType", "") or "").lower()

    # Three-valued garage: explicit flag > garageSpaces > None
    garage_flag = features.get("garage")
    if garage_flag is True or garage_flag is False:
        has_garage = garage_flag
    elif _safe_int(features.get("garageSpaces")) > 0:
        has_garage = True
    else:
        has_garage = None

    # Three-valued basement: foundation string > None
    NON_BASEMENT = {"slab", "crawl space", "crawl", "pier", "pillar", "post"}
    if "basement" in foundation:
        has_basement = True
    elif foundation and any(nb in foundation for nb in NON_BASEMENT):
        has_basement = False
    else:
        has_basement = None

    # Three-valued fireplace: explicit flag > None
    fireplace_flag = features.get("fireplace")
    if fireplace_flag is True or fireplace_flag is False:
        has_fireplace = fireplace_flag
    else:
        has_fireplace = None

    return Property(
        zpid=zpid,
        address=str(_dig(data, "formattedAddress") or ""),
        price=listing_price,
        bedrooms=_safe_int(_dig(data, "bedrooms")),
        bathrooms=_safe_float(_dig(data, "bathrooms")),
        sqft=_safe_int(_dig(data, "squareFootage")),
        lot_size_acres=lot_acres,
        year_built=_safe_int(_dig(data, "yearBuilt")),
        hoa_monthly=_safe_int(_dig(data, "hoa", "fee")),
        has_garage=has_garage,
        has_basement=has_basement,
        has_fireplace=has_fireplace,
        property_type=str(_dig(data, "propertyType") or ""),
        listing_url=listing_url,
        # Additional API fields
        last_sale_price=_safe_int(_dig(data, "lastSalePrice")),
        last_sale_date=str(_dig(data, "lastSaleDate") or ""),
        county=str(_dig(data, "county") or ""),
        latitude=_safe_float(_dig(data, "latitude")),
        longitude=_safe_float(_dig(data, "longitude")),
        has_pool=bool(features.get("pool")),
        has_cooling=bool(features.get("cooling")),
        has_heating=bool(features.get("heating")),
        garage_spaces=_safe_int(features.get("garageSpaces")),
        floor_count=_safe_int(features.get("floorCount")),
        room_count=_safe_int(features.get("roomCount")),
        foundation_type=str(features.get("foundationType", "") or ""),
        exterior_type=str(features.get("exteriorType", "") or ""),
        roof_type=str(features.get("roofType", "") or ""),
        property_tax=_most_recent_value(_dig(data, "propertyTaxes"), "total"),
        tax_assessment=_most_recent_value(_dig(data, "taxAssessments"), "value"),
    )
