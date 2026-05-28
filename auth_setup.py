#!/usr/bin/env python3
"""
Run this script ONCE on your local machine to authorize Google Calendar access.
It will create token.json — then you encode it as base64 and add to GitHub Secrets.

Usage:
  1. pip install google-auth-oauthlib google-api-python-client
  2. Download credentials.json from Google Cloud Console (OAuth 2.0 Desktop App)
  3. python auth_setup.py
  4. Follow the browser prompt
  5. Run: base64 -i token.json | pbcopy   (Mac) or base64 token.json   (Linux)
  6. Add the output as GOOGLE_TOKEN_JSON in GitHub Secrets
"""

import base64
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

def main():
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)

    # Save token
    with open("token.json", "w") as f:
        f.write(creds.to_json())
    print("✅ token.json saved!")

    # Print base64 version for GitHub Secrets
    with open("token.json", "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    print("\n─────────────────────────────────────────")
    print("Copy this value → add as GOOGLE_TOKEN_JSON in GitHub Secrets:")
    print("─────────────────────────────────────────")
    print(b64)
    print("─────────────────────────────────────────")

    # Quick test
    service = build("calendar", "v3", credentials=creds)
    result = service.calendarList().list().execute()
    calendars = result.get("items", [])
    print(f"\n📅 Found {len(calendars)} calendar(s):")
    for cal in calendars:
        print(f"  - {cal['summary']}")

if __name__ == "__main__":
    main()
