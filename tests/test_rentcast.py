"""Tests for the RentCast API client."""

from unittest.mock import patch, MagicMock

import httpx

from src.rentcast import lookup_property


def _mock_response(status_code: int = 200, json_data=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


SAMPLE_RESPONSE = [
    {
        "id": "def456",
        "formattedAddress": "408 Manchester Rd, Auburn, NH 03032",
        "bedrooms": 3,
        "bathrooms": 2.0,
        "squareFootage": 1850,
        "lotSize": 65340,
        "yearBuilt": 1998,
        "lastSalePrice": 375000,
        "features": {"garage": True, "fireplace": True, "foundationType": "Full Basement"},
    }
]


class TestLookupProperty:
    @patch("src.rentcast.httpx.get")
    def test_returns_first_result(self, mock_get):
        mock_get.return_value = _mock_response(200, SAMPLE_RESPONSE)
        result = lookup_property("408 Manchester Road, Auburn, NH", "test-key")
        assert result is not None
        assert result["bedrooms"] == 3
        assert result["features"]["garage"] is True
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["headers"]["X-Api-Key"] == "test-key"

    @patch("src.rentcast.httpx.get")
    def test_returns_none_on_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(200, [])
        result = lookup_property("Nowhere, XX", "test-key")
        assert result is None

    @patch("src.rentcast.httpx.get")
    def test_returns_none_on_404(self, mock_get):
        mock_get.return_value = _mock_response(404, None)
        result = lookup_property("Nowhere, XX", "test-key")
        assert result is None

    @patch("src.rentcast.httpx.get")
    def test_returns_none_on_500(self, mock_get):
        mock_get.return_value = _mock_response(500, None)
        result = lookup_property("Test", "test-key")
        assert result is None

    @patch("src.rentcast.httpx.get")
    def test_returns_none_on_network_error(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("connection failed")
        result = lookup_property("Test", "test-key")
        assert result is None
