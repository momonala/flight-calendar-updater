from datetime import timedelta

import pytest

import src.extract_flight_scrape as scraper
from src.extract_flight_scrape import _utc_to_local, get_flight_data, get_flight_info


@pytest.fixture(autouse=True)
def clear_cache():
    scraper.memory.clear()
    yield
    scraper.memory.clear()


# ── _utc_to_local ────────────────────────────────────────────────────────────


class TestUtcToLocal:
    def test_brs_summer_converts_utc_plus_one(self):
        # BRS = Europe/London, BST = UTC+1 in June
        result = _utc_to_local("2026-06-23T13:55Z", "BRS")
        assert result.hour == 14
        assert result.minute == 55
        assert result.tzname() == "BST"

    def test_ber_summer_converts_utc_plus_two(self):
        # BER = Europe/Berlin, CEST = UTC+2 in June
        result = _utc_to_local("2026-06-23T15:50Z", "BER")
        assert result.hour == 17
        assert result.minute == 50
        assert result.tzname() == "CEST"


# ── get_flight_data ──────────────────────────────────────────────────────────

_FAKE_HTML = "<main>fake flight detail page</main>"

_FAKE_LLM = {
    "departure_airport": "BRS",
    "arrival_airport": "BER",
    "departure_city": "Bristol",
    "arrival_city": "Berlin",
    "departure_country": "GB",
    "arrival_country": "DE",
    "airline": "easyJet",
    "aircraft": "Airbus A320",
    "arrival_terminal": "1",
    "dep_utc_iso": "2026-06-23T13:55Z",  # 14:55 BST
    "arr_utc_iso": "2026-06-23T15:50Z",  # 17:50 CEST
}


def test_get_flight_data_assembles_correct_dict(monkeypatch):
    monkeypatch.setattr(scraper, "_scrape_main_html", lambda fn, dt: _FAKE_HTML)
    monkeypatch.setattr(scraper, "_extract_with_llm", lambda html: _FAKE_LLM)

    result = get_flight_data("U2 2933", "2026-06-23")

    assert result["flight_number"] == "U2 2933"
    assert result["departure_airport"] == "BRS"
    assert result["arrival_airport"] == "BER"
    assert result["airline"] == "easyJet"
    assert result["aircraft"] == "Airbus A320"
    assert result["arrival_terminal"] == "1"
    assert result["departure_terminal"] is None
    assert result["route_distance_km"] is None


def test_get_flight_data_computes_duration_from_utc_times(monkeypatch):
    monkeypatch.setattr(scraper, "_scrape_main_html", lambda fn, dt: _FAKE_HTML)
    monkeypatch.setattr(scraper, "_extract_with_llm", lambda html: _FAKE_LLM)

    result = get_flight_data("U2 2933", "2026-06-23")

    # 13:55Z → 15:50Z = 1h55m = 6900s
    assert result["duration"] == timedelta(seconds=6900)


def test_get_flight_data_localizes_departure_to_airport_timezone(monkeypatch):
    monkeypatch.setattr(scraper, "_scrape_main_html", lambda fn, dt: _FAKE_HTML)
    monkeypatch.setattr(scraper, "_extract_with_llm", lambda html: _FAKE_LLM)

    result = get_flight_data("U2 2933", "2026-06-23")

    assert result["departure_time"].hour == 14  # 13:55 UTC → 14:55 BST
    assert result["arrival_time"].hour == 17  # 15:50 UTC → 17:50 CEST


# ── get_flight_info ──────────────────────────────────────────────────────────


def test_get_flight_info_returns_flight_info_on_success(monkeypatch):
    from datetime import datetime

    from src.datamodels import FlightInfo

    monkeypatch.setattr(scraper, "_scrape_main_html", lambda fn, dt: _FAKE_HTML)
    monkeypatch.setattr(scraper, "_extract_with_llm", lambda html: _FAKE_LLM)

    result = get_flight_info(datetime(2026, 6, 23), "U2 2933")

    assert isinstance(result, FlightInfo)
    assert result.flight_number == "U2 2933"
    assert result.departure_airport == "BRS"


def test_get_flight_info_returns_none_on_scrape_failure(monkeypatch):
    from datetime import datetime

    monkeypatch.setattr(
        scraper, "_scrape_main_html", lambda fn, dt: (_ for _ in ()).throw(ValueError("scrape failed"))
    )

    result = get_flight_info(datetime(2026, 6, 23), "U2 9999")

    assert result is None
