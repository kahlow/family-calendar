"""
One-time script to generate token.json for Google Calendar API access.

Run this on your local machine (not on the NAS):
    pip install google-auth-oauthlib google-api-python-client
    python generate_token.py

Prerequisites:
    - credentials.json in the same directory (downloaded from Google Cloud Console)
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("token.json", "w") as f:
    f.write(creds.to_json())

print("token.json created successfully.")
print("Copy this file to your NAS at:")
print("  /volume1/docker/family-calendar-briefing/token.json")
