from datetime import datetime
from datetime import timedelta

import src.fetchers.aviability as scraper

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


def test_get_flight_info_builds_local_times_and_duration_from_utc(monkeypatch):
    monkeypatch.setattr(scraper, "_scrape_main_html", lambda fn, dt: "<main></main>")
    monkeypatch.setattr(scraper, "_extract_with_llm", lambda html: _FAKE_LLM)

    info = scraper.get_flight_info(datetime(2026, 6, 23), "U2 2933 ")

    assert info.flight_number == "U2 2933"
    assert (info.departure_airport, info.arrival_airport, info.airline) == ("BRS", "BER", "easyJet")
    assert (info.departure_time.hour, info.departure_time.tzname()) == (14, "BST")
    assert (info.arrival_time.hour, info.arrival_time.tzname()) == (17, "CEST")
    assert info.duration == timedelta(hours=1, minutes=55)
    assert info.arrival_terminal == "Terminal 1"
    assert info.departure_terminal is None


def test_get_flight_info_returns_none_on_scrape_failure(monkeypatch):
    def fail(fn, dt):
        raise ValueError("scrape failed")

    monkeypatch.setattr(scraper, "_scrape_main_html", fail)

    assert scraper.get_flight_info(datetime(2026, 6, 23), "U2 9999") is None
