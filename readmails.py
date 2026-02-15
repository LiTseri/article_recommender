import os
import datetime as dt
from typing import Optional, List, Dict

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

# =========================
# ENV + CONFIG
# =========================
load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "secrets/credentials.json")
TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "secrets/token.json")


# =========================
# Helpers
# =========================
def parse_date_yyyy_mm_dd(s: str) -> Optional[str]:
    """
    Returns the same date string if valid (YYYY/MM/DD), otherwise None.
    Gmail query needs YYYY/MM/DD format.
    """
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt.datetime.strptime(s, "%Y/%m/%d")
        return s
    except ValueError:
        return None


def get_header(payload: Dict, name: str) -> str:
    for h in payload.get("headers", []) or []:
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value") or ""
    return ""


def internal_date_to_local_date_str(msg: Dict) -> str:
    """
    Gmail returns internalDate in ms since epoch (UTC).
    We'll print date in local time as YYYY-MM-DD.
    """
    try:
        ms = int(msg.get("internalDate", "0"))
        dt_utc = dt.datetime.utcfromtimestamp(ms / 1000.0)
        # For display only: keep as date
        return dt_utc.date().isoformat()
    except Exception:
        return ""


# =========================
# Gmail Auth
# =========================
def authenticate_gmail_api():
    """
    Authenticate and return Gmail API service.
    Uses:
      - secrets/credentials.json (OAuth client)
      - secrets/token.json (created after first login)
    Paths come from .env:
      GMAIL_CREDENTIALS_PATH, GMAIL_TOKEN_PATH
    """
    if not os.path.exists(CREDENTIALS_PATH):
        raise FileNotFoundError(
            f"Δεν βρέθηκε το credentials file: {CREDENTIALS_PATH}\n"
            f"Βεβαιώσου ότι υπάρχει στο secrets/ και ότι το .env δείχνει σωστά."
        )

    creds = None

    # Load existing token if present
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If no valid creds, start OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=8080)

        # Ensure secrets folder exists and save token
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    return service


# =========================
# Main logic
# =========================
def list_messages_with_label(service, label: str, start_date: Optional[str], end_date: Optional[str], limit: int = 25):
    """
    Search emails by label and date range.
    start_date/end_date must be YYYY/MM/DD or None.

    Prints: Date, From, Subject, Snippet
    """
    label = (label or "").strip()
    if not label:
        print("⚠️ Δεν έδωσες label. Σταματάω.")
        return

    # Gmail query
    query_parts = [f'label:"{label}"']
    if start_date:
        query_parts.append(f"after:{start_date}")
    if end_date:
        query_parts.append(f"before:{end_date}")

    query = " ".join(query_parts)
    print(f"\n🔎 Gmail query: {query}\n")

    try:
        results = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        messages = results.get("messages", []) or []

        if not messages:
            print("📭 No messages found.")
            return

        print(f"✅ Found {len(messages)} messages (showing up to {limit}).\n")

        for i, message in enumerate(messages, start=1):
            msg = service.users().messages().get(userId="me", id=message["id"], format="metadata").execute()
            payload = msg.get("payload", {}) or {}

            subject = get_header(payload, "Subject")
            sender = get_header(payload, "From")
            date_str = internal_date_to_local_date_str(msg)

            snippet = (msg.get("snippet") or "").replace("\n", " ").strip()

            print(f"[{i}] {date_str}")
            print(f"From: {sender}")
            print(f"Subject: {subject}")
            print(f"Snippet: {snippet[:200]}")
            print("-" * 60)

    except Exception as error:
        print(f"❌ An error occurred: {error}")


def main():
    # Connect to Gmail API
    service = authenticate_gmail_api()

    # User inputs
    label = input("Label to search (π.χ. InspoNews): ").strip()

    start_in = input("Start date (YYYY/MM/DD) ή Enter για skip: ").strip()
    end_in = input("End date (YYYY/MM/DD) ή Enter για skip: ").strip()

    start_date = parse_date_yyyy_mm_dd(start_in)
    end_date = parse_date_yyyy_mm_dd(end_in)

    if start_in and not start_date:
        print("⚠️ Start date δεν είναι σωστό format. Χρησιμοποίησε YYYY/MM/DD.")
        return
    if end_in and not end_date:
        print("⚠️ End date δεν είναι σωστό format. Χρησιμοποίησε YYYY/MM/DD.")
        return

    list_messages_with_label(service, label, start_date, end_date, limit=25)


if __name__ == "__main__":
    main()
