# Flight Calendar Updater

A Python tool that automatically fetches flight details and keeps your Google Calendar updated with comprehensive flight information from a Google Sheets tracker.

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

2. Install required packages:
```bash
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
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os

# If modifying these scopes, delete the token.pickle file.
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/calendar'
]

# Your Google Calendar ID (found in calendar settings)
CALENDAR_ID = 'your_calendar_id@group.calendar.google.com'

# Your Google Sheets ID (from the URL)
SPREADSHEET_ID = 'your_spreadsheet_id'

# The range in your sheet (including the header row)
RANGE_NAME = 'raw!A1:ZZ'

def get_credentials():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

credentials = get_credentials()
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

- Python 3.9+
- Google account with Calendar and Sheets access
- Required Python packages (see requirements.txt) 