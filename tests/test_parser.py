"""Tests for the RentCast-to-Property parser."""

from src.parser import Property, parse_from_rentcast, _most_recent_value

# Sample RentCast /v1/properties response
SAMPLE_PROPERTY = {
    "id": "def456",
    "formattedAddress": "408 Manchester Rd, Auburn, NH 03032",
    "lastSalePrice": 350000,
    "lastSaleDate": "2020-06-15T00:00:00.000Z",
    "bedrooms": 3,
    "bathrooms": 2.0,
    "squareFootage": 1850,
    "lotSize": 65340,  # sqft
    "yearBuilt": 1998,
    "propertyType": "Single Family",
    "county": "Rockingham",
    "latitude": 43.0045,
    "longitude": -71.3456,
    "hoa": {"fee": 0},
    "features": {
        "garage": True,
        "garageSpaces": 2,
        "fireplace": True,
        "foundationType": "Full Basement",
        "pool": False,
        "cooling": True,
        "heating": True,
        "floorCount": 2,
        "roomCount": 7,
        "exteriorType": "Vinyl",
        "roofType": "Asphalt",
    },
    "propertyTaxes": {
        "2024": {"year": 2024, "total": 6800},
        "2023": {"year": 2023, "total": 6500},
    },
    "taxAssessments": {
        "2024": {"year": 2024, "value": 380000, "land": 120000, "improvements": 260000},
        "2023": {"year": 2023, "value": 360000},
    },
}


class TestParseFromRentcast:
    def test_listing_price_from_email(self):
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "1", "", listing_price=485000)
        assert prop.price == 485000

    def test_last_sale_price_from_api(self):
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "1", "")
        assert prop.last_sale_price == 350000
        assert "2020-06-15" in prop.last_sale_date

    def test_basic_fields(self):
        prop = parse_from_rentcast(
            SAMPLE_PROPERTY, "12345678",
            "https://www.zillow.com/homedetails/408-Manchester-Rd/12345678_zpid/",
            listing_price=485000,
        )
        assert prop.zpid == "12345678"
        assert prop.address == "408 Manchester Rd, Auburn, NH 03032"
        assert prop.bedrooms == 3
        assert prop.bathrooms == 2.0
        assert prop.sqft == 1850
        assert prop.year_built == 1998
        assert prop.property_type == "Single Family"
        assert prop.hoa_monthly == 0

    def test_lot_size_conversion(self):
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "1", "")
        assert 1.49 <= prop.lot_size_acres <= 1.51

    def test_features(self):
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "1", "")
        assert prop.has_garage is True
        assert prop.has_fireplace is True
        assert prop.has_basement is True
        assert prop.has_pool is False
        assert prop.has_cooling is True
        assert prop.has_heating is True
        assert prop.garage_spaces == 2
        assert prop.floor_count == 2
        assert prop.room_count == 7
        assert prop.foundation_type == "Full Basement"
        assert prop.exterior_type == "Vinyl"
        assert prop.roof_type == "Asphalt"

    def test_location_fields(self):
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "1", "")
        assert prop.county == "Rockingham"
        assert prop.latitude == 43.0045
        assert prop.longitude == -71.3456

    def test_tax_fields(self):
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "1", "")
        assert prop.property_tax == 6800  # most recent year
        assert prop.tax_assessment == 380000

    def test_no_features_when_missing(self):
        data = {k: v for k, v in SAMPLE_PROPERTY.items() if k != "features"}
        prop = parse_from_rentcast(data, "1", "")
        assert prop.has_garage is False
        assert prop.has_fireplace is False
        assert prop.has_basement is False
        assert prop.garage_spaces == 0

    def test_hoa_fee_nested(self):
        data = {**SAMPLE_PROPERTY, "hoa": {"fee": 150}}
        prop = parse_from_rentcast(data, "1", "")
        assert prop.hoa_monthly == 150

    def test_missing_fields_default_gracefully(self):
        minimal = {"formattedAddress": "123 Test St"}
        prop = parse_from_rentcast(minimal, "999", "")
        assert prop.zpid == "999"
        assert prop.address == "123 Test St"
        assert prop.price == 0
        assert prop.bedrooms == 0
        assert prop.lot_size_acres == 0.0
        assert prop.property_tax == 0

    def test_basement_detection_case_insensitive(self):
        data = {**SAMPLE_PROPERTY, "features": {
            "foundationType": "WALK-OUT BASEMENT", "garage": False, "fireplace": False,
        }}
        prop = parse_from_rentcast(data, "1", "")
        assert prop.has_basement is True

    def test_no_basement_when_slab(self):
        data = {**SAMPLE_PROPERTY, "features": {
            "foundationType": "Slab", "garage": False, "fireplace": False,
        }}
        prop = parse_from_rentcast(data, "1", "")
        assert prop.has_basement is False

    def test_listing_url_preserved(self):
        url = "https://www.zillow.com/homedetails/test/12345_zpid/"
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "12345", url)
        assert prop.listing_url == url

    def test_commute_minutes_defaults_to_empty_dict(self):
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "1", "")
        assert prop.commute_minutes == {}

    def test_commute_minutes_can_be_set(self):
        prop = parse_from_rentcast(SAMPLE_PROPERTY, "1", "")
        prop.commute_minutes = {"Work": 32, "Family": 28}
        assert prop.commute_minutes == {"Work": 32, "Family": 28}


class TestMostRecentValue:
    def test_picks_latest_year(self):
        taxes = {"2023": {"total": 6500}, "2024": {"total": 6800}}
        assert _most_recent_value(taxes, "total") == 6800

    def test_returns_zero_for_none(self):
        assert _most_recent_value(None, "total") == 0

    def test_returns_zero_for_empty(self):
        assert _most_recent_value({}, "total") == 0
