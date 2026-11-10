from datetime import datetime

import pytest
from pydantic import ValidationError

from src.datamodels import FlightInfo
from src.datamodels import GSheetRow
from tests.conftest import _SHEET_HEADER
from tests.conftest import make_sheet_row


def test_invalid_country_code_raises(flight_info_raw):
    flight_info_raw["departure_country"] = "XX"
    with pytest.raises(ValidationError, match="Unknown country"):
        FlightInfo.model_validate(flight_info_raw)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1", "Terminal 1"),
        ("A", "Terminal A"),
        ("Terminal 2", "Terminal 2"),
        ("  ", None),
    ],
)
def test_terminal_formatting(flight_info_raw, raw, expected):
    flight_info_raw["arrival_terminal"] = raw
    fi = FlightInfo.model_validate(flight_info_raw)
    assert fi.arrival_terminal == expected


def test_string_times_are_localized_to_each_airport_timezone(flight_info):
    # BRS is Europe/London (BST, UTC+1) and BER is Europe/Berlin (CEST, UTC+2) in June
    assert (flight_info.departure_time.tzname(), flight_info.departure_time.hour) == ("BST", 14)
    assert (flight_info.arrival_time.tzname(), flight_info.arrival_time.hour) == ("CEST", 17)
    assert flight_info.departure_time.minute == 55
    assert flight_info.arrival_time.minute == 50


@pytest.mark.parametrize("iso, expected", [("PT1H55M", "01:55"), ("PT10H5M", "10:05")])
def test_formatted_duration(flight_info_raw, iso, expected):
    flight_info_raw["duration"] = iso
    fi = FlightInfo.model_validate(flight_info_raw)
    assert fi.formatted_duration == expected


class TestGSheetRow:
    def test_valid_date_parsed(self):
        row = make_sheet_row(date="Jun 23, 2026")
        assert row.date == datetime(2026, 6, 23)

    def test_invalid_date_raises(self):
        with pytest.raises(ValidationError):
            make_sheet_row(date="2026-06-23")

    def test_short_values_list_pads_with_none(self):
        row = GSheetRow.from_sheet_row(
            header=_SHEET_HEADER,
            values=["2026", "6", "23", "Tue", "Jun 23, 2026", "U2 2933"],
        )
        assert row.flight_number == "U2 2933"
        assert row.departure_airport is None
