"""Google Sheets integration — two-tab design.

Listings tab: raw property data, append-only, never changes.
Scores tab:   rebuilt from scratch every run using the current scoring matrix.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from src.parser import Property
from src.scorer import ScoreBreakdown

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LISTINGS_HEADERS = [
    "Link",
    "Date Added",
    "Status",
    "ZPID",
    "Town",
    "Address",
    "Listing Price",
    "Property Tax",
    "Beds",
    "Baths",
    "SqFt",
    "Lot (acres)",
    "Commutes",
    "Garage",
    "Basement",
    "Fireplace",
    "Year Built",
    "HOA",
    "Last Sale Price",
    "Last Sale Date",
    "Property Type",
    "County",
    "Tax Assessment",
    "Pool",
    "Heating",
    "Cooling",
    "Floors",
    "Rooms",
    "Exterior",
    "Roof",
    "Latitude",
    "Longitude",
    "Garage Spaces",
    "Foundation",
]


def _build_scores_headers(commute_labels: list[str]) -> list[str]:
    """Build Scores tab headers dynamically based on configured commute destinations."""
    headers = [
        "Value Ratio",
        "Score",
        "Address",
        "Listing Price",
    ]
    for label in commute_labels:
        headers.append(f"Commute ({label})")
    headers += [
        "Beds",
        "Baths",
        "SqFt",
        "Lot (acres)",
        "Garage",
        "Basement",
        "Fireplace",
        "Score Breakdown",
        "ZPID",
        "Link",
    ]
    return headers


def _bool_to_cell(val: bool | None) -> str:
    """Convert three-valued bool to sheet cell: True→'Yes', False→'No', None→''."""
    if val is True:
        return "Yes"
    if val is False:
        return "No"
    return ""


def _cell_to_bool(val: str) -> bool | None:
    """Convert sheet cell to three-valued bool: 'yes'→True, 'no'→False, ''→None."""
    s = str(val).strip().lower()
    if s == "yes":
        return True
    if s == "no":
        return False
    return None


def _col_letter(n: int) -> str:
    """Convert 1-based column number to letter(s): 1→A, 26→Z, 27→AA."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


class SheetsClient:
    def __init__(
        self,
        credentials_file: str | Path,
        spreadsheet_id: str,
        listings_tab: str = "Listings",
        scores_tab: str = "Scores",
    ):
        creds = Credentials.from_service_account_file(
            str(credentials_file), scopes=SCOPES
        )
        self.gc = gspread.authorize(creds)
        self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
        self.listings_tab_name = listings_tab
        self.scores_tab_name = scores_tab
        self._ensure_listings_tab()

    # ------------------------------------------------------------------ #
    #  Listings tab — raw data, append-only
    # ------------------------------------------------------------------ #

    def _ensure_listings_tab(self) -> None:
        """Create the Listings tab with headers if it doesn't exist."""
        try:
            self.listings_ws = self.spreadsheet.worksheet(self.listings_tab_name)
        except gspread.exceptions.WorksheetNotFound:
            self.listings_ws = self.spreadsheet.add_worksheet(
                title=self.listings_tab_name,
                rows=1000,
                cols=len(LISTINGS_HEADERS),
            )

        existing = self.listings_ws.row_values(1)
        if not existing or existing != LISTINGS_HEADERS:
            self.listings_ws.update("A1", [LISTINGS_HEADERS])
            self._bold_row(self.listings_ws, len(LISTINGS_HEADERS))

        self._apply_currency_format(self.listings_ws)

    def get_existing_zpids(self) -> set[str]:
        """Return the set of ZPIDs already in the Listings tab."""
        try:
            col = LISTINGS_HEADERS.index("ZPID") + 1
            zpids = self.listings_ws.col_values(col)
            return set(zpids[1:])  # skip header
        except Exception as e:
            logger.warning("Could not read ZPIDs: %s", e)
            return set()

    def add_listing(self, prop: Property) -> bool:
        """Append raw property data to Listings. Returns False if duplicate."""
        existing = self.get_existing_zpids()
        if prop.zpid in existing:
            logger.info("ZPID %s already in Listings, skipping", prop.zpid)
            return False

        row = [
            prop.listing_url,
            date.today().isoformat(),
            "",  # Status — user-editable
            prop.zpid,
            prop.town,
            prop.address,
            prop.price,
            prop.property_tax,
            prop.bedrooms,
            prop.bathrooms,
            prop.sqft,
            prop.lot_size_acres,
            json.dumps(prop.commute_minutes) if prop.commute_minutes else "",
            _bool_to_cell(prop.has_garage),
            _bool_to_cell(prop.has_basement),
            _bool_to_cell(prop.has_fireplace),
            prop.year_built,
            prop.hoa_monthly,
            prop.last_sale_price,
            prop.last_sale_date,
            prop.property_type,
            prop.county,
            prop.tax_assessment,
            "Yes" if prop.has_pool else "No",
            "Yes" if prop.has_heating else "No",
            "Yes" if prop.has_cooling else "No",
            prop.floor_count,
            prop.room_count,
            prop.exterior_type,
            prop.roof_type,
            prop.latitude,
            prop.longitude,
            prop.garage_spaces,
            prop.foundation_type,
        ]

        self.listings_ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info("Added %s to Listings tab", prop.address)
        return True

    def read_all_listings(self) -> list[Property]:
        """Read all properties back from the Listings tab."""
        rows = self.listings_ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
        properties: list[Property] = []

        for row in rows:
            try:
                # Parse commute data from JSON string
                commute_raw = row.get("Commutes", "")
                if commute_raw and isinstance(commute_raw, str):
                    try:
                        commute_minutes = json.loads(commute_raw)
                    except (json.JSONDecodeError, TypeError):
                        commute_minutes = {}
                else:
                    commute_minutes = {}

                properties.append(Property(
                    zpid=str(row.get("ZPID", "")),
                    address=str(row.get("Address", "")),
                    town=str(row.get("Town", "")),
                    price=int(row.get("Listing Price", 0) or 0),
                    bedrooms=int(row.get("Beds", 0) or 0),
                    bathrooms=float(row.get("Baths", 0) or 0),
                    sqft=int(row.get("SqFt", 0) or 0),
                    lot_size_acres=float(row.get("Lot (acres)", 0) or 0),
                    year_built=int(row.get("Year Built", 0) or 0),
                    hoa_monthly=int(row.get("HOA", 0) or 0),
                    has_garage=_cell_to_bool(row.get("Garage", "")),
                    has_basement=_cell_to_bool(row.get("Basement", "")),
                    has_fireplace=_cell_to_bool(row.get("Fireplace", "")),
                    property_type=str(row.get("Property Type", "")),
                    listing_url=str(row.get("Link", "")),
                    last_sale_price=int(row.get("Last Sale Price", 0) or 0),
                    last_sale_date=str(row.get("Last Sale Date", "")),
                    county=str(row.get("County", "")),
                    latitude=float(row.get("Latitude", 0) or 0),
                    longitude=float(row.get("Longitude", 0) or 0),
                    has_pool=str(row.get("Pool", "")).lower() == "yes",
                    has_cooling=str(row.get("Cooling", "")).lower() == "yes",
                    has_heating=str(row.get("Heating", "")).lower() == "yes",
                    garage_spaces=int(row.get("Garage Spaces", 0) or 0),
                    floor_count=int(row.get("Floors", 0) or 0),
                    room_count=int(row.get("Rooms", 0) or 0),
                    foundation_type=str(row.get("Foundation", "")),
                    exterior_type=str(row.get("Exterior", "")),
                    roof_type=str(row.get("Roof", "")),
                    property_tax=int(row.get("Property Tax", 0) or 0),
                    tax_assessment=int(row.get("Tax Assessment", 0) or 0),
                    commute_minutes=commute_minutes,
                    status=str(row.get("Status", "")),
                ))
            except (ValueError, TypeError) as e:
                logger.warning("Skipping malformed Listings row (ZPID %s): %s", row.get("ZPID"), e)

        return properties

    # ------------------------------------------------------------------ #
    #  Scores tab — rebuilt from scratch every run
    # ------------------------------------------------------------------ #

    def rebuild_scores(
        self,
        scored: list[tuple[Property, ScoreBreakdown]],
        commute_labels: list[str] | None = None,
    ) -> None:
        """Clear and rewrite the Scores tab with current rankings.

        `scored` should already be sorted by value_ratio descending.
        `commute_labels` is the list of destination labels for commute columns.
        """
        if commute_labels is None:
            commute_labels = []

        headers = _build_scores_headers(commute_labels)

        # Get or create the Scores tab
        try:
            scores_ws = self.spreadsheet.worksheet(self.scores_tab_name)
        except gspread.exceptions.WorksheetNotFound:
            scores_ws = self.spreadsheet.add_worksheet(
                title=self.scores_tab_name,
                rows=1000,
                cols=len(headers),
            )

        last_col = _col_letter(len(headers))

        # Build all rows (header + data) in one batch
        rows: list[list[Any]] = [headers]
        for prop, breakdown in scored:
            row: list[Any] = [
                breakdown.value_ratio,
                breakdown.final_score,
                prop.address,
                prop.price,
            ]
            for label in commute_labels:
                row.append(prop.commute_minutes.get(label, ""))
            row += [
                prop.bedrooms,
                prop.bathrooms,
                prop.sqft,
                prop.lot_size_acres,
                _bool_to_cell(prop.has_garage),
                _bool_to_cell(prop.has_basement),
                _bool_to_cell(prop.has_fireplace),
                breakdown.summary(),
                prop.zpid,
                prop.listing_url,
            ]
            rows.append(row)

        # Clear the entire sheet and write in one call
        scores_ws.clear()
        if rows:
            scores_ws.update(f"A1:{last_col}{len(rows)}", rows, value_input_option="USER_ENTERED")

        self._bold_row(scores_ws, len(headers))
        self._color_score_rows(scores_ws, scored, len(headers))

        logger.info("Scores tab rebuilt with %d listings", len(scored))

    def _color_score_rows(
        self,
        ws: gspread.Worksheet,
        scored: list[tuple[Property, ScoreBreakdown]],
        num_cols: int,
    ) -> None:
        """Batch color-code rows on the Scores tab by relative ranking (thirds)."""
        last_col = _col_letter(num_cols)
        n = len(scored)
        if n == 0:
            return
        top_cutoff = n // 3 or 1  # at least 1 row in top tier
        mid_cutoff = 2 * n // 3 or top_cutoff + 1
        try:
            formats = []
            for i in range(n):
                row_num = i + 2  # 1-indexed, skip header
                if i < top_cutoff:
                    bg = {"red": 0.85, "green": 0.95, "blue": 0.85}
                elif i < mid_cutoff:
                    bg = {"red": 1.0, "green": 0.97, "blue": 0.8}
                else:
                    continue
                formats.append({"range": f"A{row_num}:{last_col}{row_num}", "format": {"backgroundColor": bg}})

            if formats:
                ws.batch_format(formats)
        except Exception as e:
            logger.debug("Could not color-code Scores tab: %s", e)

    # ------------------------------------------------------------------ #
    #  Shared helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _bold_row(ws: gspread.Worksheet, num_cols: int) -> None:
        col_letter = _col_letter(num_cols)
        try:
            ws.format(f"A1:{col_letter}1", {"textFormat": {"bold": True}})
        except Exception as e:
            logger.debug("Could not bold header: %s", e)

    @staticmethod
    def _apply_currency_format(ws: gspread.Worksheet) -> None:
        """Apply currency format ($#,##0) to Listing Price and Property Tax columns."""
        currency_fmt = {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0"}}
        price_col = _col_letter(LISTINGS_HEADERS.index("Listing Price") + 1)
        tax_col = _col_letter(LISTINGS_HEADERS.index("Property Tax") + 1)
        try:
            ws.batch_format([
                {"range": f"{price_col}2:{price_col}1000", "format": currency_fmt},
                {"range": f"{tax_col}2:{tax_col}1000", "format": currency_fmt},
            ])
        except Exception as e:
            logger.debug("Could not apply currency format: %s", e)
