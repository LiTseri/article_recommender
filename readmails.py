import os
import base64
import re
import json
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

# Ανάγνωση των credentials από το credentials.json
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def authenticate_gmail_api():
    """Authenticate and return the Gmail API service."""
    creds = None
    # Το αρχείο token.json αποθηκεύει το access token του χρήστη και την ανανέωση.
    # Αν δεν υπάρχει, θα γίνει η διαδικασία εξουσιοδότησης.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Αν οι credentials είναι άκυρες, κάνουμε επανασύνδεση
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        
        # Αποθηκεύουμε τα credentials για μελλοντική χρήση
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    # Επιστρέφουμε την υπηρεσία Gmail API
    service = build('gmail', 'v1', credentials=creds)
    return service

def list_messages_with_label(service, label, start_date, end_date):
    """Λειτουργία για την αναζήτηση emails με ένα συγκεκριμένο label και ημερομηνία"""
    query = f"label:{label} after:{start_date} before:{end_date}"
    try:
        # Αναζητούμε τα μηνύματα με την query
        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])
        
        if not messages:
            print("No messages found.")
        else:
            print(f"Found {len(messages)} messages.")
            for message in messages:
                msg = service.users().messages().get(userId='me', id=message['id']).execute()
                email_data = msg['payload']['headers']
                for values in email_data:
                    name = values['name']
                    if name == 'From':
                        from_name = values['value']
                        print(f"From: {from_name}")
                        print(f"Subject: {msg['snippet']}")
                        print('-' * 50)

    except Exception as error:
        print(f"An error occurred: {error}")

def main():
    # Σύνδεση με το Gmail API
    service = authenticate_gmail_api()
    
    # Ζητάμε από τον χρήστη το label και τις ημερομηνίες
    label = input("Enter the label you're looking for: ")
    start_date = input("Enter the start date (YYYY/MM/DD): ")
    end_date = input("Enter the end date (YYYY/MM/DD): ")

    # Εκτέλεση της αναζήτησης
    list_messages_with_label(service, label, start_date, end_date)

if __name__ == '__main__':
    main()

