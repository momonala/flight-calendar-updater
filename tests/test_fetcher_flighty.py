from datetime import datetime
from pathlib import Path

import pytest

from src.datamodels import FlightInfo
from src.fetchers import flighty as fc

_FIXTURE = Path(__file__).parent / "fixtures" / "flighty_search_tk1730.bin"


def test_search_response_maps_to_flight_info():
    results = fc._first(fc._decode(_FIXTURE.read_bytes()), "2")["1"]
    info = FlightInfo.model_validate(fc._flight_info_from_record("TK1730", results[0]))

    assert (info.airline, info.departure_airport, info.arrival_airport) == (
        "Turkish Airlines",
        "BER",
        "IST",
    )
    assert info.departure_time == datetime.fromisoformat("2026-10-03T13:05+02:00")
    assert info.arrival_time == datetime.fromisoformat("2026-10-03T17:00+03:00")
    assert info.departure_terminal == "Terminal 1"
    assert info.aircraft == "Airbus A321neo"
    assert info.departure_country.alpha_2 == "DE"
    assert str(info.departure_time.tzinfo) == "Europe/Berlin"  # calendar_client sends this as the IANA zone


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("TK1730", ("TK", "1730")),
        ("tk 1730", ("TK", "1730")),
        ("U2 2933", ("U2", "2933")),
        ("3U7284", ("3U", "7284")),
    ],
)
def test_split_flight_number(raw, expected):
    assert fc._split_flight_number(raw) == expected


def test_split_flight_number_rejects_garbage():
    with pytest.raises(ValueError):
        fc._split_flight_number("TK")


def test_codec_round_trips_search_request():
    body = (
        fc._field(1, fc._field(1, "uuid") + fc._field(2, "1730"))
        + fc._field(3, "2026-10-03")
        + fc._field(4, "FLIGHT_NUMBER")
    )
    assert fc._decode(body) == {
        "1": [{"1": ["uuid"], "2": ["1730"]}],
        "3": ["2026-10-03"],
        "4": ["FLIGHT_NUMBER"],
    }


def test_airlines_does_not_cache_empty_table(monkeypatch, tmp_path):
    cache = tmp_path / "airlines.json"
    monkeypatch.setattr(fc, "_AIRLINES_CACHE", cache)
    monkeypatch.setattr(fc, "_fetch_airlines", lambda: {})

    assert fc._airlines() == {}
    assert not cache.exists()


def test_airlines_refetches_after_ttl(monkeypatch, tmp_path):
    cache = tmp_path / "airlines.json"
    cache.write_text('{"XX": []}')
    monkeypatch.setattr(fc, "_AIRLINES_CACHE", cache)
    monkeypatch.setattr(fc, "_fetch_airlines", lambda: {"TK": [{"uuid": "u", "name": "n", "rank": 1}]})

    assert fc._airlines() == {"XX": []}
    monkeypatch.setattr(fc.time, "time", lambda: cache.stat().st_mtime + fc._AIRLINES_CACHE_TTL_S + 1)
    assert fc._airlines() == {"TK": [{"uuid": "u", "name": "n", "rank": 1}]}


def test_check_credentials_fails_fast_when_unset(monkeypatch):
    monkeypatch.setattr(fc, "FLIGHTY_AUTH_TOKEN", "")
    with pytest.raises(RuntimeError):
        fc.check_credentials()


def test_get_flight_info_logs_http_error_as_one_line(monkeypatch, caplog):
    def rate_limited(*_):
        raise fc.requests.HTTPError("429 Client Error: Too Many Requests")

    monkeypatch.setattr(fc, "search_flight", rate_limited)
    assert fc.get_flight_info(datetime(2027, 1, 15), "GQ874") is None
    assert [r.exc_info for r in caplog.records] == [None]
    assert "429" in caplog.text
