import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Ambiente
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")
GOOGLE_ACCESS_TOKEN = os.environ.get("GOOGLE_ACCESS_TOKEN", "")
GOOGLE_TOKEN_URI = os.environ.get("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")
GOOGLE_AUTH_URI = os.environ.get("GOOGLE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost")

# Caminho opcional para persistir o token renovado (ainda útil para evitar re-autenticação)
TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "token.json")


def _client_config():
    """Monta o dicionário de configuração OAuth a partir das variáveis de ambiente."""
    return {
        "installed": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


def _save_token(creds):
    """Persiste o token renovado em disco."""
    token_directory = os.path.dirname(TOKEN_PATH)
    if token_directory:
        os.makedirs(token_directory, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
        token_file.write(creds.to_json())


def _credentials_from_env():
    """Cria um objeto Credentials a partir das variáveis de ambiente, se disponíveis."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return None
    if not GOOGLE_REFRESH_TOKEN and not GOOGLE_ACCESS_TOKEN:
        return None

    creds = Credentials(
        token=GOOGLE_ACCESS_TOKEN or None,
        refresh_token=GOOGLE_REFRESH_TOKEN or None,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    return creds


def get_calendar_service():
    creds = None

    # 1. Tenta carregar token salvo em disco (versão mais recente após refresh)
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # 2. Fallback: monta credenciais a partir do .env
    if not creds:
        creds = _credentials_from_env()

    # 3. Se expirado, tenta renovar com refresh_token
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)

    # 4. Se ainda não tem credenciais válidas, faz o fluxo OAuth completo
    if not creds or not creds.valid:
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise RuntimeError(
                "Defina GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no arquivo .env "
                "ou forneça credentials.json."
            )
        flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
        creds = flow.run_local_server(port=0)
        _save_token(creds)

    return build("calendar", "v3", credentials=creds)


def create_event(event):
    # Validação: rejeita evento sem data/hora
    start = event.get("start", {})
    end = event.get("end", {})
    if not start.get("dateTime") or not end.get("dateTime"):
        raise ValueError(
            "Evento sem data/hora definida. "
            "Certifique-se de que o comando de voz incluiu data e horário."
        )

    print("Evento:", event)
    service = get_calendar_service()
    created_event = service.events().insert(calendarId="primary", body=event).execute()
    print("Evento criado com sucesso.")
    print("Link:", created_event.get("htmlLink"))
