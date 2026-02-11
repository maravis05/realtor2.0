"""Tests for the email monitor — listing data extraction from Zillow alert HTML."""

from pathlib import Path

from src.email_monitor import (
    ListingLink,
    _extract_listing_data_from_html,
    _extract_price_from_block,
    _address_from_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_real_email() -> str:
    return (FIXTURES / "zillow_alert_email.html").read_text()


# Minimal synthetic HTML where <a> hrefs contain direct Zillow URLs
SYNTHETIC_ALERT_HTML = """
<html>
<body>
<table class="mw502">
  <tr><td>
    <a href="https://www.zillow.com/homedetails/408-Manchester-Rd-Auburn-NH-03032/87654321_zpid/">
      <img src="photo.jpg" />
    </a>
  </td></tr>
  <tr><td>
    <h5>$375,000</h5>
    <p>408 Manchester Road, Auburn, NH 03032</p>
  </td></tr>
</table>
</body>
</html>
"""

# HTML without mw502 tables — should fall back to link scanning
SIMPLE_LINK_HTML = """
<html>
<body>
<a href="https://www.zillow.com/homedetails/99-Pine-Ave-Nashua-NH/55555555_zpid/">View</a>
</body>
</html>
"""


class TestRealZillowEmail:
    """Tests against a saved real Zillow alert email."""

    def test_extracts_four_listings(self):
        links = _extract_listing_data_from_html(_load_real_email())
        assert len(links) == 4

    def test_zpids_extracted(self):
        links = _extract_listing_data_from_html(_load_real_email())
        zpids = {l.zpid for l in links}
        assert "86814380" in zpids
        assert "86808454" in zpids
        assert "117794945" in zpids
        assert "92866854" in zpids

    def test_addresses_extracted(self):
        links = _extract_listing_data_from_html(_load_real_email())
        addresses = {l.zpid: l.address for l in links}
        assert "408 Manchester Road" in addresses["86814380"]
        assert "Auburn" in addresses["86814380"]
        assert "378 Chester Road" in addresses["86808454"]

    def test_urls_are_canonical_zillow(self):
        links = _extract_listing_data_from_html(_load_real_email())
        for link in links:
            assert "zillow.com/homedetails/" in link.url
            assert link.url.endswith("_zpid/")

    def test_prices_extracted(self):
        links = _extract_listing_data_from_html(_load_real_email())
        prices = {l.zpid: l.price for l in links}
        assert prices["86814380"] == 485000
        assert prices["86808454"] == 400000
        assert prices["117794945"] == 399999
        assert prices["92866854"] == 325000

    def test_no_duplicates(self):
        links = _extract_listing_data_from_html(_load_real_email())
        zpids = [l.zpid for l in links]
        assert len(zpids) == len(set(zpids))


class TestSyntheticEmail:
    """Tests with minimal synthetic HTML."""

    def test_extracts_from_direct_links(self):
        links = _extract_listing_data_from_html(SYNTHETIC_ALERT_HTML)
        assert len(links) == 1
        assert links[0].zpid == "87654321"

    def test_address_from_mw502_block(self):
        links = _extract_listing_data_from_html(SYNTHETIC_ALERT_HTML)
        assert "408 Manchester Road" in links[0].address

    def test_price_from_mw502_block(self):
        links = _extract_listing_data_from_html(SYNTHETIC_ALERT_HTML)
        assert links[0].price == 375000

    def test_fallback_to_link_scanning(self):
        links = _extract_listing_data_from_html(SIMPLE_LINK_HTML)
        assert len(links) == 1
        assert links[0].zpid == "55555555"

    def test_fallback_extracts_address_from_url(self):
        links = _extract_listing_data_from_html(SIMPLE_LINK_HTML)
        assert "99 Pine Ave Nashua NH" in links[0].address

    def test_empty_html_returns_empty(self):
        links = _extract_listing_data_from_html("<html><body></body></html>")
        assert links == []

    def test_deduplicates_zpids(self):
        html = SYNTHETIC_ALERT_HTML + SYNTHETIC_ALERT_HTML
        links = _extract_listing_data_from_html(html)
        zpids = [l.zpid for l in links]
        assert len(zpids) == len(set(zpids))


def _load_new_listing_email() -> str:
    return (FIXTURES / "zillow_new_listing_email.html").read_text()


class TestNewListingEmail:
    """Tests against a saved real Zillow 'New Listing:' alert email."""

    def test_extracts_only_primary_listing(self):
        links = _extract_listing_data_from_html(_load_new_listing_email())
        assert len(links) == 1

    def test_primary_zpid(self):
        links = _extract_listing_data_from_html(_load_new_listing_email())
        assert links[0].zpid == "113449928"

    def test_primary_address(self):
        links = _extract_listing_data_from_html(_load_new_listing_email())
        assert "13 Birchdale Road" in links[0].address
        assert "Bow" in links[0].address

    def test_primary_price(self):
        links = _extract_listing_data_from_html(_load_new_listing_email())
        assert links[0].price == 479000

    def test_canonical_url(self):
        links = _extract_listing_data_from_html(_load_new_listing_email())
        assert links[0].url == "https://www.zillow.com/homedetails/113449928_zpid/"

    def test_excludes_recommendations(self):
        """The email has 6 'recommended' listings that should NOT be extracted."""
        links = _extract_listing_data_from_html(_load_new_listing_email())
        zpids = {l.zpid for l in links}
        # These are recommendation ZPIDs that should be excluded
        assert "117800723" not in zpids
        assert "124632182" not in zpids


def _load_search_result_email() -> str:
    return (FIXTURES / "zillow_search_result_email.html").read_text()


class TestSearchResultEmail:
    """Tests against a saved real Zillow 'N Results for' search alert email."""

    def test_extracts_only_primary_listing(self):
        links = _extract_listing_data_from_html(_load_search_result_email())
        assert len(links) == 1

    def test_primary_zpid(self):
        links = _extract_listing_data_from_html(_load_search_result_email())
        assert links[0].zpid == "120666053"

    def test_primary_address(self):
        links = _extract_listing_data_from_html(_load_search_result_email())
        assert "Molly Stark" in links[0].address
        assert "New Boston" in links[0].address

    def test_primary_price(self):
        links = _extract_listing_data_from_html(_load_search_result_email())
        assert links[0].price == 460000

    def test_excludes_recommendations(self):
        """The email has 3 recommended listings that should NOT be extracted."""
        links = _extract_listing_data_from_html(_load_search_result_email())
        zpids = {l.zpid for l in links}
        # These are recommendation ZPIDs that should be excluded
        assert "2090198051" not in zpids  # 2 Larch St condo
        assert "74282506" not in zpids
        assert "74321529" not in zpids


class TestAddressFromUrl:
    def test_extracts_address_slug(self):
        url = "https://www.zillow.com/homedetails/408-Manchester-Rd-Auburn-NH-03032/87654321_zpid/"
        result = _address_from_url(url)
        assert result == "408 Manchester Rd Auburn NH 03032"

    def test_returns_empty_for_bad_url(self):
        assert _address_from_url("https://example.com/") == ""
