import pytest

from src.datamodels import FlightInfo, GSheetRow

_FLIGHT_RAW = {
    "flight_number": "U2 2933",
    "airline": "easyJet",
    "departure_airport": "BRS",
    "arrival_airport": "BER",
    "departure_city": "Bristol",
    "arrival_city": "Berlin",
    "departure_country": "GB",
    "arrival_country": "DE",
    "departure_terminal": None,
    "arrival_terminal": "1",
    "departure_time": "2026-06-23T14:55",
    "arrival_time": "2026-06-23T17:50",
    "duration": "PT1H55M",
    "aircraft": "Airbus A320",
    "route_distance_km": None,
}

_SHEET_HEADER = [
    "Year",
    "Month",
    "Day",
    "Weekday",
    "Date",
    "Flight #",
    "Departure Airport",
    "Arrival Airport",
    "Departure Time",
    "Arrival Time",
    "Duration",
    "Origin",
    "Destination",
    "Flighty",
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


@pytest.fixture
def flight_info_raw() -> dict:
    return dict(_FLIGHT_RAW)


@pytest.fixture
def flight_info(flight_info_raw) -> FlightInfo:
    return FlightInfo.model_validate(flight_info_raw)


def make_sheet_row(
    date: str = "Jun 23, 2026", flight_number: str = "U2 2933", gcal_id: str = ""
) -> GSheetRow:
    values = [
        "2026",
        "6",
        "23",
        "Tue",
        date,
        flight_number,
        "BRS",
        "BER",
        "14:55",
        "17:50",
        "01:55",
        "Bristol",
        "Berlin",
        "",
        gcal_id,
        "",
        "6900",
        "easyJet",
        "Airbus A320",
        "United Kingdom",
        "Germany",
        "",
        "Terminal 1",
    ]
    return GSheetRow.from_sheet_row(header=_SHEET_HEADER, values=values)
