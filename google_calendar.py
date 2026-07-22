import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "token.json")
CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")


def get_calendar_service():
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        token_directory = os.path.dirname(TOKEN_PATH)
        if token_directory:
            os.makedirs(token_directory, exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def create_event(event):
    print("Evento:", event)
    service = get_calendar_service()
    created_event = service.events().insert(calendarId="primary", body=event).execute()
    print("Evento criado com sucesso.")
    print("Link:", created_event.get("htmlLink"))
