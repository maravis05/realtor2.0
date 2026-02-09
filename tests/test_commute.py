"""Tests for the Google Maps Distance Matrix commute client."""

from unittest.mock import patch, MagicMock

import httpx

from src.commute import get_commute_times


DESTINATIONS = {"Work": "123 Office Dr, Manchester, NH", "Family": "456 Family Rd, Concord, NH"}


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestGetCommuteTimes:
    @patch("src.commute.httpx.get")
    def test_successful_two_destinations(self, mock_get):
        mock_get.return_value = _mock_response({
            "status": "OK",
            "rows": [{
                "elements": [
                    {"status": "OK", "duration": {"value": 1920, "text": "32 mins"}},
                    {"status": "OK", "duration": {"value": 1680, "text": "28 mins"}},
                ],
            }],
        })
        result = get_commute_times("408 Manchester Rd, Auburn, NH", DESTINATIONS, "test-key")
        assert result == {"Work": 32, "Family": 28}

    @patch("src.commute.httpx.get")
    def test_partial_failure_one_not_found(self, mock_get):
        mock_get.return_value = _mock_response({
            "status": "OK",
            "rows": [{
                "elements": [
                    {"status": "OK", "duration": {"value": 1920, "text": "32 mins"}},
                    {"status": "NOT_FOUND"},
                ],
            }],
        })
        result = get_commute_times("408 Manchester Rd, Auburn, NH", DESTINATIONS, "test-key")
        assert result == {"Work": 32}
        assert "Family" not in result

    @patch("src.commute.httpx.get")
    def test_api_error_status(self, mock_get):
        mock_get.return_value = _mock_response({
            "status": "REQUEST_DENIED",
            "error_message": "Invalid key",
        })
        result = get_commute_times("408 Manchester Rd, Auburn, NH", DESTINATIONS, "bad-key")
        assert result == {}

    @patch("src.commute.httpx.get")
    def test_network_error(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        result = get_commute_times("408 Manchester Rd, Auburn, NH", DESTINATIONS, "test-key")
        assert result == {}

    @patch("src.commute.httpx.get")
    def test_http_error(self, mock_get):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=resp,
        )
        mock_get.return_value = resp
        result = get_commute_times("408 Manchester Rd, Auburn, NH", DESTINATIONS, "test-key")
        assert result == {}

    @patch("src.commute.httpx.get")
    def test_single_api_call_for_multiple_destinations(self, mock_get):
        mock_get.return_value = _mock_response({
            "status": "OK",
            "rows": [{
                "elements": [
                    {"status": "OK", "duration": {"value": 1800, "text": "30 mins"}},
                    {"status": "OK", "duration": {"value": 2400, "text": "40 mins"}},
                ],
            }],
        })
        get_commute_times("408 Manchester Rd, Auburn, NH", DESTINATIONS, "test-key")
        assert mock_get.call_count == 1
        # Check pipe-delimited destinations
        call_params = mock_get.call_args[1]["params"]
        assert "|" in call_params["destinations"]

    def test_empty_destinations(self):
        result = get_commute_times("408 Manchester Rd, Auburn, NH", {}, "test-key")
        assert result == {}

    @patch("src.commute.httpx.get")
    def test_rounding_seconds_to_minutes(self, mock_get):
        mock_get.return_value = _mock_response({
            "status": "OK",
            "rows": [{
                "elements": [
                    {"status": "OK", "duration": {"value": 1890, "text": "31 mins"}},
                ],
            }],
        })
        result = get_commute_times(
            "408 Manchester Rd, Auburn, NH",
            {"Work": "123 Office Dr"},
            "test-key",
        )
        # 1890 / 60 = 31.5, round = 32
        assert result == {"Work": 32}
