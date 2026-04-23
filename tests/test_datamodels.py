from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.datamodels import FlightInfo, GSheetRow
from tests.conftest import _SHEET_HEADER, make_sheet_row


class TestFlightInfoCountryValidator:
    def test_valid_alpha2_resolves_to_country_object(self, flight_info_raw):
        fi = FlightInfo.model_validate(flight_info_raw)
        assert fi.departure_country.alpha_2 == "GB"
        assert fi.arrival_country.alpha_2 == "DE"

    def test_country_object_passthrough(self, flight_info):

        # Validator accepts already-resolved country objects
        fi = FlightInfo.model_validate({**_flight_raw_with(departure_country="FR")})
        assert fi.departure_country.alpha_2 == "FR"

    def test_invalid_country_code_raises(self, flight_info_raw):
        flight_info_raw["departure_country"] = "XX"
        with pytest.raises(ValidationError, match="Unknown country"):
            FlightInfo.model_validate(flight_info_raw)


class TestFlightInfoTerminalValidator:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1", "Terminal 1"),
            ("A", "Terminal A"),
            ("Terminal 2", "Terminal 2"),
            (None, None),
            ("", None),
            ("  ", None),
        ],
    )
    def test_terminal_formatting(self, flight_info_raw, raw, expected):
        flight_info_raw["arrival_terminal"] = raw
        fi = FlightInfo.model_validate(flight_info_raw)
        assert fi.arrival_terminal == expected


class TestFlightInfoTimeParsing:
    def test_string_departure_time_is_localized_to_airport_timezone(self, flight_info):
        # BRS is Europe/London — BST (UTC+1) in June
        assert flight_info.departure_time.tzname() == "BST"
        assert flight_info.departure_time.hour == 14
        assert flight_info.departure_time.minute == 55

    def test_string_arrival_time_is_localized_to_airport_timezone(self, flight_info):
        # BER is Europe/Berlin — CEST (UTC+2) in June
        assert flight_info.arrival_time.tzname() == "CEST"
        assert flight_info.arrival_time.hour == 17
        assert flight_info.arrival_time.minute == 50

    def test_datetime_passthrough_skips_localization(self, flight_info_raw):
        import pytz

        already_localized = pytz.timezone("Europe/Paris").localize(datetime(2026, 6, 23, 14, 55))
        flight_info_raw["departure_time"] = already_localized
        fi = FlightInfo.model_validate(flight_info_raw)
        assert fi.departure_time == already_localized

    def test_iso_duration_string_parsed_to_timedelta(self, flight_info):
        assert flight_info.duration == timedelta(hours=1, minutes=55)

    def test_timedelta_passthrough(self, flight_info_raw):
        flight_info_raw["duration"] = timedelta(hours=2, minutes=30)
        fi = FlightInfo.model_validate(flight_info_raw)
        assert fi.duration == timedelta(hours=2, minutes=30)


class TestFlightInfoFormatters:
    def test_formatted_duration(self, flight_info):
        assert flight_info.formatted_duration == "01:55"

    def test_formatted_duration_over_one_hour(self, flight_info_raw):
        flight_info_raw["duration"] = "PT10H5M"
        fi = FlightInfo.model_validate(flight_info_raw)
        assert fi.formatted_duration == "10:05"


class TestGSheetRow:
    def test_valid_date_parsed(self):
        row = make_sheet_row(date="Jun 23, 2026")
        assert row.date == datetime(2026, 6, 23)

    def test_invalid_date_raises(self):
        with pytest.raises(ValidationError):
            make_sheet_row(date="2026-06-23")  # wrong format

    def test_short_values_list_pads_with_none(self):
        row = GSheetRow.from_sheet_row(
            header=_SHEET_HEADER,
            values=["2026", "6", "23", "Tue", "Jun 23, 2026", "U2 2933"],
        )
        assert row.flight_number == "U2 2933"
        assert row.departure_airport is None

    def test_empty_gcal_event_id_stored_as_empty_string(self):
        row = make_sheet_row(gcal_id="")
        assert row.gcal_event_id == ""


def _flight_raw_with(**overrides) -> dict:
    from tests.conftest import _FLIGHT_RAW

    return {**_FLIGHT_RAW, **overrides}
