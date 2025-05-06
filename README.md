# Flight Calendar Updater

A Python tool that automatically fetches flight details and keeps your Google Calendar updated with comprehensive flight information from a Google Sheets tracker. Can run as a cron service with `scheduler.py` and `install/projects_flight_calendar_updater.service`

## Features

- Fetches detailed flight information using flight numbers
- Syncs flight details between Google Sheets and Google Calendar
- Includes rich flight information in calendar events:
  - Flight duration
  - Aircraft details
  - Terminal information
  - Local times with timezone offsets
  - Country flags for origin/destination
  - Formatted departure/arrival details

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/flight-calendar-updater.git
cd flight-calendar-updater
```

2. Install reqguired packages:
```bash
conda create -n flight_calendar_updater python=3.12 -y
pip install poetry
poetry install
```

3. Set up Google API credentials:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project
   - Enable the Google Sheets API and Google Calendar API
   - Create OAuth 2.0 credentials
   - Download the credentials JSON file

4. Create a `values.py` file with your configuration:
```python
from google.oauth2 import service_account

# Set up credentials
SERVICE_ACCOUNT_FILE = "google_application_credentials.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]

SPREADSHEET_ID = ""
RANGE_NAME = "raw!A:ZZ"
CALENDAR_ID = ""
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)

```

## Usage

1. Set up your Google Sheet with the following columns:
   - Year
   - Month
   - Day
   - Weekday
   - Date
   - Flight #
   - Departure Airport
   - Arrival Airport
   - Departure Time
   - Arrival Time
   - Duration
   - Origin
   - Destination
   - Flighty
   - gcal_event_id
   - note
   - duration_s
   - airline
   - aircraft
   - departure_country
   - arrival_country
   - departure_terminal
   - arrival_terminal

2. Run the script:
```bash
python main.py
```

The script will:
1. Read flight information from your Google Sheet
2. Fetch detailed flight information for each entry
3. Create or update Google Calendar events with comprehensive flight details
4. Update the Google Sheet with the fetched information

## Requirements

- Python 3.12+
- Google account with Calendar and Sheets access
- Required Python packages (see pyproject.toml) 