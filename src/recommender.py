import os
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Φόρτωσε .env (αν υπάρχει)
load_dotenv()

# ONLY read-only πρόσβαση στο Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Paths από .env (με ασφαλή defaults)
CREDENTIALS_PATH = os.getenv('GMAIL_CREDENTIALS_PATH', 'secrets/credentials.json')
TOKEN_PATH       = os.getenv('GMAIL_TOKEN_PATH',       'secrets/token.json')

def get_gmail_service():
    """Επιστρέφει authenticated Gmail API service με Desktop OAuth flow (localhost)."""
    # σιγουρέψου ότι υπάρχει ο φάκελος για τα μυστικά
    os.makedirs(os.path.dirname(CREDENTIALS_PATH) or ".", exist_ok=True)

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
import os
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Φόρτωσε .env (αν υπάρχει)
load_dotenv()

# ONLY read-only πρόσβαση στο Gmail
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Paths από .env (με ασφαλή defaults)
CREDENTIALS_PATH = os.getenv('GMAIL_CREDENTIALS_PATH', 'secrets/credentials.json')
TOKEN_PATH       = os.getenv('GMAIL_TOKEN_PATH',       'secrets/token.json')

def get_gmail_service():
    """Επιστρέφει authenticated Gmail API service με Desktop OAuth flow (localhost)."""
    # σιγουρέψου ότι υπάρχει ο φάκελος για τα μυστικά
    os.makedirs(os.path.dirname(CREDENTIALS_PATH) or ".", exist_ok=True)

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Χρησιμοποιεί το Desktop client JSON (installed)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=8080)  # σταθερό & ασφαλές για desktop
        with open(TOKEN_PATH, 'w') as token_file:
            token_file.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)

def main():
    service = get_gmail_service()

    # Παίρνουμε τα 5 πιο πρόσφατα μηνύματα ως δοκιμή
    results = service.users().messages().list(userId='me', maxResults=5).execute()
    messages = results.get('messages', [])

    if not messages:
        print("Δεν βρέθηκαν μηνύματα.")
        return

    print("Τα 5 πιο πρόσφατα μηνύματα:")
    for msg in messages:
        m = service.users().messages().get(userId='me', id=msg['id']).execute()
        print("-", m.get('snippet', '')[:120])

if __name__ == '__main__':
    main()

