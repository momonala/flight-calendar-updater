from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import src.main as main_module
from src.datamodels import GSheetIndexedRow
from tests.conftest import _SHEET_HEADER
from tests.conftest import make_sheet_row

FUTURE = "Jan 01, 2099"

# ── row filtering ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("missing", ["date", "flight_number"])
def test_row_missing_date_or_flight_number_is_skipped(missing):
    row = make_sheet_row(date=FUTURE)
    setattr(row, missing, None)
    assert main_module._should_skip_row(row, update_all=True) is True


@pytest.mark.parametrize("date", ["Sep 29, 2024", "Jan 01, 2025"])
def test_pre_cutoff_or_past_row_is_skipped_even_when_updating_all(date):
    row = make_sheet_row(date=date)
    assert main_module._should_skip_row(row, update_all=True) is True


@pytest.mark.parametrize(
    "filled, update_all, skipped",
    [
        (False, False, False),
        (True, False, True),
        (True, True, False),
    ],
)
def test_future_row_is_skipped_only_when_filled_and_not_updating(filled, update_all, skipped):
    row = make_sheet_row(date=FUTURE)
    row.departure_time = "10:00" if filled else None
    row.arrival_time = None
    assert main_module._should_skip_row(row, update_all=update_all) is skipped


def test_rows_for_processing_keep_sheet_row_numbers():
    rows = [
        _SHEET_HEADER,
        ["2025", "1", "1", "Wed", "Jan 01, 2025", "U2 2933"],
        ["2099", "1", "1", "Thu", FUTURE, "U2 2933"],
        ["2099", "1", "2", "Fri", "Jan 02, 2099", "BY 6303"],
    ]
    result = main_module._get_rows_for_processing(rows, update_all=False)
    assert [r.row_number for r in result] == [3, 4]


# ── _build_updated_row ───────────────────────────────────────────────────────


def test_build_updated_row_takes_flight_info_and_keeps_user_columns(flight_info):
    row = make_sheet_row()
    row.flighty = "FLY123"
    row.note = "window seat"

    result = main_module._build_updated_row(row, flight_info, event_id="evt123")

    assert result.departure_airport == "BRS"
    assert result.arrival_airport == "BER"
    assert result.airline == "easyJet"
    assert result.aircraft == "Airbus A320"
    assert result.arrival_terminal == "Terminal 1"
    assert result.departure_terminal is None
    assert result.gcal_event_id == "evt123"
    assert result.duration_s == pytest.approx(timedelta(hours=1, minutes=55).total_seconds())
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


# ── interactive update selection ─────────────────────────────────────────────


def test_select_rows_keeps_unfilled_and_confirmed_rows(monkeypatch):
    def indexed(row_number: int, filled: bool) -> GSheetIndexedRow:
        row = make_sheet_row()
        row.departure_time = "10:00" if filled else None
        row.arrival_time = None
        return GSheetIndexedRow(row_number=row_number, row=row)

    keys = iter(["x", "U", "s"])
    monkeypatch.setattr(main_module.typer, "getchar", lambda: next(keys))
    rows = [indexed(2, filled=False), indexed(3, filled=True), indexed(4, filled=True)]

    result = main_module._select_rows_to_update(rows)

    assert [r.row_number for r in result] == [2, 3]


def test_all_without_update_is_rejected():
    result = CliRunner().invoke(main_module.app, ["--all"])
    assert result.exit_code != 0
    assert "--update" in result.output
