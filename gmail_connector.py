import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

class GmailConnector:
    def __init__(self, client_secret_file="client_secret.json", token_file="token.json"):
        self.client_secret_file = client_secret_file
        self.token_file = token_file
        self.creds = None

    def authenticate(self):
        if os.path.exists(self.token_file):
            with open(self.token_file, "rb") as token:
                self.creds = pickle.load(token)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secret_file, SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            with open(self.token_file, "wb") as token:
                pickle.dump(self.creds, token)

    def fetch_emails(self, query="subject:(receipt OR invoice OR subscription OR payment) newer_than:365d", max_results=20):
        service = build("gmail", "v1", credentials=self.creds)
        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = results.get("messages", [])
        emails = []
        for msg in messages:
            full_msg = service.users().messages().get(userId="me", id=msg["id"]).execute()
            snippet = full_msg.get("snippet", "")
            emails.append(snippet)
        return emails
