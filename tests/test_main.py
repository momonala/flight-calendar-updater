from datetime import timedelta
from unittest.mock import MagicMock

import pytest

import src.main as main_module
from src.datamodels import GSheetIndexedRow
from tests.conftest import _SHEET_HEADER, make_sheet_row

# ── row filtering ────────────────────────────────────────────────────────────


class TestShouldSkipRow:
    def test_missing_flight_number_skips(self):
        row = make_sheet_row(flight_number="")
        row.flight_number = None
        assert main_module._should_skip_row(row) is True

    def test_missing_date_skips(self):
        row = make_sheet_row()
        row.date = None
        assert main_module._should_skip_row(row) is True

    def test_before_cutoff_skips(self):
        row = make_sheet_row(date="Oct 01, 2024")
        assert main_module._should_skip_row(row) is True

    def test_on_cutoff_date_skips(self):
        row = make_sheet_row(date="Sep 29, 2024")
        assert main_module._should_skip_row(row) is True

    def test_past_date_skips(self):
        row = make_sheet_row(date="Jan 01, 2025")
        assert main_module._should_skip_row(row) is True

    def test_future_date_is_processed(self, monkeypatch):
        monkeypatch.setattr(main_module, "_is_in_the_past", lambda _: False)
        row = make_sheet_row(date="Jun 23, 2026")
        assert main_module._should_skip_row(row) is False


class TestGetRowsForProcessing:
    def _make_raw_rows(self, *sheet_rows):
        rows = [_SHEET_HEADER]
        for sr in sheet_rows:
            rows.append(
                [
                    getattr(sr, col, None) or ""
                    for col in [
                        "year",
                        "month",
                        "day",
                        "weekday",
                        "date",
                        "flight_number",
                        "departure_airport",
                        "arrival_airport",
                        "departure_time",
                        "arrival_time",
                        "duration",
                        "origin",
                        "destination",
                        "flighty",
                        "gcal_event_id",
                        "note",
                        "duration_s",
                        "airline",
                        "aircraft",
                        "departure_country",
                        "arrival_country",
                        "departure_terminal",
                        "arrival_terminal",
                    ]
                ]
            )
        return rows

    def test_row_number_starts_at_two(self, monkeypatch):
        monkeypatch.setattr(main_module, "_should_skip_row", lambda _: False)
        rows = [
            _SHEET_HEADER,
            ["2026", "6", "23", "Tue", "Jun 23, 2026", "U2 2933"] + [None] * 17,
        ]
        result = main_module._get_rows_for_processing(rows)
        assert result[0].row_number == 2

    def test_skipped_rows_excluded(self, monkeypatch):
        monkeypatch.setattr(main_module, "_should_skip_row", lambda _: True)
        rows = [
            _SHEET_HEADER,
            ["2026", "6", "23", "Tue", "Jun 23, 2026", "U2 2933"] + [None] * 17,
        ]
        result = main_module._get_rows_for_processing(rows)
        assert result == []

    def test_row_number_accounts_for_header_offset(self, monkeypatch):
        monkeypatch.setattr(main_module, "_should_skip_row", lambda _: False)
        rows = [
            _SHEET_HEADER,
            ["2026", "6", "23", "Tue", "Jun 23, 2026", "U2 2933"] + [None] * 17,
            ["2026", "6", "24", "Wed", "Jun 24, 2026", "BY 6303"] + [None] * 17,
        ]
        result = main_module._get_rows_for_processing(rows)
        assert [r.row_number for r in result] == [2, 3]


# ── _build_updated_row ───────────────────────────────────────────────────────


class TestBuildUpdatedRow:
    def test_maps_flight_info_fields(self, flight_info):
        row = make_sheet_row()
        result = main_module._build_updated_row(row, flight_info, event_id="evt123")

        assert result.departure_airport == "BRS"
        assert result.arrival_airport == "BER"
        assert result.airline == "easyJet"
        assert result.aircraft == "Airbus A320"
        assert result.arrival_terminal == "Terminal 1"
        assert result.departure_terminal is None
        assert result.gcal_event_id == "evt123"
        assert result.duration_s == pytest.approx(timedelta(hours=1, minutes=55).total_seconds())

    def test_preserves_original_row_metadata(self, flight_info):
        row = make_sheet_row()
        row.flighty = "FLY123"
        row.note = "window seat"

        result = main_module._build_updated_row(row, flight_info, event_id="evt123")

        assert result.flighty == "FLY123"
        assert result.note == "window seat"
        assert result.flight_number == row.flight_number


# ── _process_flight ──────────────────────────────────────────────────────────


class TestProcessFlight:
    def test_skips_calendar_and_sheet_when_flight_info_is_none(self, monkeypatch):
        monkeypatch.setattr(main_module, "get_flight_info", lambda date, fn: None)
        create_mock = MagicMock()
        update_mock = MagicMock()
        monkeypatch.setattr(main_module, "create_or_update_gcal_event", create_mock)
        monkeypatch.setattr(main_module, "update_row_with_formulas", update_mock)

        indexed = GSheetIndexedRow(row_number=2, row=make_sheet_row())
        main_module._process_flight(indexed, _SHEET_HEADER)

        create_mock.assert_not_called()
        update_mock.assert_not_called()

    def test_creates_calendar_event_and_updates_sheet_on_success(self, monkeypatch, flight_info):
        monkeypatch.setattr(main_module, "get_flight_info", lambda date, fn: flight_info)
        monkeypatch.setattr(main_module, "create_or_update_gcal_event", lambda fi, eid: "evt999")
        update_mock = MagicMock()
        monkeypatch.setattr(main_module, "update_row_with_formulas", update_mock)

        indexed = GSheetIndexedRow(row_number=2, row=make_sheet_row())
        main_module._process_flight(indexed, _SHEET_HEADER)

        update_mock.assert_called_once()
        call_kwargs = update_mock.call_args
        assert call_kwargs.kwargs["new_row"].gcal_event_id == "evt999"
