import logging

from googleapiclient.discovery import build

from src.config import CALENDAR_ID, google_credentials
from src.datamodels import FlightInfo

logger = logging.getLogger(__name__)

_gcal_client = None


def _get_gcal_client():
    global _gcal_client
    if _gcal_client is None:
        service = build("calendar", "v3", credentials=google_credentials, cache_discovery=False)
        _gcal_client = service.events()
    return _gcal_client


def create_or_update_gcal_event(flight_info: FlightInfo, event_id: str | None) -> str:
    event_description = (
        f"✈️ {flight_info.departure_airport} → {flight_info.arrival_airport} {flight_info.flight_number}"
    )
    start = flight_info.departure_time
    end = flight_info.arrival_time
    if end <= start:
        end = start + flight_info.duration
    event = {
        "summary": event_description,
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": start.tzinfo.zone,
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": end.tzinfo.zone,
        },
        "description": flight_info.as_gcal_description(),
    }

    if event_id:
        event = _get_gcal_client().update(calendarId=CALENDAR_ID, eventId=event_id, body=event).execute()
        logger.info(f'📅 Updated event: {event_description} with ID {event["id"]}')
    else:
        event = _get_gcal_client().insert(calendarId=CALENDAR_ID, body=event).execute()
        logger.info(f'📅 Created event: {event_description} with ID {event["id"]}')
    return event["id"]
