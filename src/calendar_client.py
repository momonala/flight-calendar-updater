import logging

from googleapiclient.discovery import build

from src.datamodels import FlightInfo
from src.values import CALENDAR_ID, credentials

logger = logging.getLogger(__name__)

_calendar_service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
_gcal_client = _calendar_service.events()


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
        event = _gcal_client.update(calendarId=CALENDAR_ID, eventId=event_id, body=event).execute()
        logger.info(f'📅 Updated event: {event_description} with ID {event["id"]}')
    else:
        event = _gcal_client.insert(calendarId=CALENDAR_ID, body=event).execute()
        logger.info(f'📅 Created event: {event_description} with ID {event["id"]}')
    return event["id"]
