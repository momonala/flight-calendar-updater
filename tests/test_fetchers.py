from datetime import datetime

import src.fetchers as fetchers


def test_falls_back_to_next_source_when_first_finds_nothing(monkeypatch, flight_info):
    monkeypatch.setattr(fetchers, "FETCHERS", (lambda d, fn: None, lambda d, fn: flight_info))
    assert fetchers.get_flight_info(datetime(2026, 6, 23), "U2 2933") is flight_info


def test_stops_at_first_source_that_finds_the_flight(monkeypatch, flight_info):
    def must_not_run(d, fn):
        raise AssertionError("second source should not run")

    monkeypatch.setattr(fetchers, "FETCHERS", (lambda d, fn: flight_info, must_not_run))
    assert fetchers.get_flight_info(datetime(2026, 6, 23), "U2 2933") is flight_info


def test_returns_none_when_every_source_finds_nothing(monkeypatch):
    monkeypatch.setattr(fetchers, "FETCHERS", (lambda d, fn: None, lambda d, fn: None))
    assert fetchers.get_flight_info(datetime(2026, 6, 23), "U2 2933") is None
