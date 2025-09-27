from __future__ import print_function
import os.path
import pickle
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Το scope μας (μόνο ανάγνωση Gmail)
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def main():
    creds = None
    # Το token.json δημιουργείται αυτόματα μετά το πρώτο login
    if os.path.exists('secrets/token.json'):
        creds = Credentials.from_authorized_user_file('secrets/token.json', SCOPES)

    # Αν δεν υπάρχουν ή έχουν λήξει τα credentials, ξεκινά νέο login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'secrets/credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        # Σώσε το token.json για επόμενη φορά
        with open('secrets/token.json', 'w') as token:
            token.write(creds.to_json())

    # Σύνδεση στο Gmail API
    service = build('gmail', 'v1', credentials=creds)

    # Παίρνουμε τα 5 τελευταία μηνύματα
    results = service.users().messages().list(userId='me', maxResults=5).execute()
    messages = results.get('messages', [])

    if not messages:
        print("Δεν βρέθηκαν μηνύματα.")
    else:
        print("Τα 5 πιο πρόσφατα μηνύματα:")
        for msg in messages:
            m = service.users().messages().get(userId='me', id=msg['id']).execute()
            print("-", m['snippet'][:80])  # δείχνει το preview

if __name__ == '__main__':
    main()

