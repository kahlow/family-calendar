"""Fetch Google Calendar events and generate an AI-powered family briefing."""

import json
import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_PATH = Path(os.environ.get("TOKEN_PATH", SCRIPT_DIR / "token.json"))
HTML_DIR = Path(os.environ.get("HTML_DIR", SCRIPT_DIR / "html"))
LOOK_AHEAD_DAYS = 14


def load_credentials():
    """Load and refresh Google OAuth credentials from token.json."""
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
        print("Refreshed access token and saved to token.json")

    return creds


def fetch_events(creds):
    """Fetch events from all calendars for the next LOOK_AHEAD_DAYS days."""
    service = build("calendar", "v3", credentials=creds)

    now = datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + timedelta(days=LOOK_AHEAD_DAYS)).isoformat() + "Z"

    calendars = service.calendarList().list().execute().get("items", [])

    all_events = []
    for cal in calendars:
        cal_name = cal.get("summary", "Unknown Calendar")
        cal_id = cal["id"]

        events_result = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        for event in events_result.get("items", []):
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            end = event["end"].get("dateTime", event["end"].get("date", ""))
            all_events.append(
                {
                    "calendar": cal_name,
                    "summary": event.get("summary", "(no title)"),
                    "start": start,
                    "end": end,
                    "location": event.get("location", ""),
                }
            )

    all_events.sort(key=lambda e: e["start"])
    return all_events


def format_events_as_text(events):
    """Group events by date and format as plain text for the LLM prompt."""
    if not events:
        return "No events found in the next 14 days."

    grouped = {}
    for event in events:
        date_str = event["start"][:10]
        grouped.setdefault(date_str, []).append(event)

    lines = []
    for date_str in sorted(grouped):
        lines.append(f"\n## {date_str}")
        for ev in grouped[date_str]:
            time_part = ""
            if "T" in ev["start"]:
                time_part = ev["start"].split("T")[1][:5]
                end_time = ev["end"].split("T")[1][:5] if "T" in ev["end"] else ""
                if end_time:
                    time_part = f"{time_part}-{end_time}"
            else:
                time_part = "All day"

            location = f" @ {ev['location']}" if ev["location"] else ""
            lines.append(f"- [{ev['calendar']}] {time_part}: {ev['summary']}{location}")

    return "\n".join(lines)


def generate_briefing(events_text):
    """Send events to Claude Haiku and get back a styled HTML briefing."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""You are a helpful family calendar assistant. Today is {today}.

Here are the upcoming events from our family's Google Calendars:

{events_text}

Please create a friendly, well-organized family briefing as a complete, self-contained HTML document with inline CSS. Requirements:

- Mobile-friendly responsive design
- Clean, modern styling with good typography
- Color-code events by calendar name (assign each calendar a distinct, pleasant color)
- Group events by date with clear date headers
- Highlight today and tomorrow prominently
- Flag any scheduling conflicts or overlapping events
- Note coordination needs (e.g., multiple family members at different places at the same time)
- Call out prep items (e.g., things to pack, early wake-ups)
- Include a brief friendly summary at the top
- Show when this briefing was generated at the bottom
- Do NOT wrap the output in code fences — output only the raw HTML""",
            }
        ],
    )

    return message.content[0].text


def write_error_page(error_msg):
    """Write an error HTML page so the dashboard shows the problem, not stale content."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Calendar Briefing - Error</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 600px; margin: 40px auto; padding: 0 20px; color: #333; }}
.error {{ background: #fee; border: 1px solid #c00; border-radius: 8px; padding: 20px; margin-top: 20px; }}
</style>
</head>
<body>
<h1>Calendar Briefing Error</h1>
<div class="error">
<p>The briefing could not be generated:</p>
<pre>{error_msg}</pre>
</div>
<p>Generated at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
</body>
</html>"""
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    (HTML_DIR / "index.html").write_text(html)


def main():
    try:
        print("Loading Google credentials...")
        creds = load_credentials()

        print("Fetching calendar events...")
        events = fetch_events(creds)
        print(f"Found {len(events)} events in the next {LOOK_AHEAD_DAYS} days")

        events_text = format_events_as_text(events)

        print("Generating briefing with Claude...")
        html = generate_briefing(events_text)

        HTML_DIR.mkdir(parents=True, exist_ok=True)
        (HTML_DIR / "index.html").write_text(html)
        print("Briefing written to html/index.html")

    except Exception:
        error = traceback.format_exc()
        print(f"ERROR: {error}")
        write_error_page(error)


if __name__ == "__main__":
    main()
