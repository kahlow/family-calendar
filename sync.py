"""Fetch Google Calendar events and generate a structured JSON briefing."""

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
HISTORY_DIR = Path(os.environ.get("HISTORY_DIR", SCRIPT_DIR / "history"))
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


def analyze_weekends(events):
    """Analyze upcoming weekends and flag light ones for date night/family suggestions."""
    now = datetime.now()
    weekends = []

    # Find all Sat/Sun pairs in the look-ahead window
    for day_offset in range(LOOK_AHEAD_DAYS):
        day = now + timedelta(days=day_offset)
        if day.weekday() == 5:  # Saturday
            saturday = day.date()
            sunday = saturday + timedelta(days=1)

            sat_events = []
            sun_events = []
            for ev in events:
                ev_date = ev["start"][:10]
                is_timed = "T" in ev["start"]
                if ev_date == str(saturday):
                    sat_events.append(ev)
                    if is_timed:
                        sat_events[-1]["_timed"] = True
                elif ev_date == str(sunday):
                    sun_events.append(ev)
                    if is_timed:
                        sun_events[-1]["_timed"] = True

            timed_count = sum(1 for e in sat_events if e.get("_timed")) + sum(
                1 for e in sun_events if e.get("_timed")
            )

            if timed_count == 0:
                status = "free"
            elif timed_count <= 1:
                status = "light"
            else:
                status = "busy"

            weekends.append(
                {
                    "saturday": str(saturday),
                    "sunday": str(sunday),
                    "status": status,
                    "timed_event_count": timed_count,
                    "saturday_events": [
                        {"summary": e["summary"], "calendar": e["calendar"]}
                        for e in sat_events
                    ],
                    "sunday_events": [
                        {"summary": e["summary"], "calendar": e["calendar"]}
                        for e in sun_events
                    ],
                }
            )

    # Clean up temporary _timed keys
    for ev in events:
        ev.pop("_timed", None)

    return weekends


def generate_briefing(events_text, weekend_analysis):
    """Send events to Claude and get back a structured JSON briefing."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    weekend_context = json.dumps(weekend_analysis, indent=2)

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=(
            "You are a briefing assistant for a husband who would otherwise forget "
            "everything on the family calendar. Your tone is warm, funny, and "
            "self-deprecating 'dumb husband' humor -- think dad jokes and gentle "
            "roasting, never mean-spirited. The audience is the husband; the vast "
            "majority of events are his wife's. Your job is to make sure he doesn't "
            "drop the ball.\n\n"
            "You MUST respond with valid JSON only. No markdown, no code fences, "
            "no extra text outside the JSON object."
        ),
        messages=[
            {
                "role": "user",
                "content": f"""Today is {today}.

Here are the upcoming events from our family's Google Calendars:

{events_text}

Here is the weekend analysis data:

{weekend_context}

Analyze these events and return a JSON object with exactly these keys:

{{
  "summary": "A 2-3 sentence 'hey dummy, here's what you need to know' overview of the period. Warm, funny, helpful.",
  "action_items": [
    {{
      "date": "YYYY-MM-DD",
      "time": "HH:MM" or "All day",
      "event": "Event name",
      "calendar": "Calendar name",
      "why": "Brief explanation of why this affects the husband (e.g. 'you're on kid duty', 'don't forget to RSVP')"
    }}
  ],
  "fyi_events": [
    {{
      "date": "YYYY-MM-DD",
      "events": [
        {{
          "time": "HH:MM" or "All day",
          "event": "Event name",
          "calendar": "Calendar name",
          "location": "Location if any"
        }}
      ]
    }}
  ],
  "weekend_outlook": [
    {{
      "dates": "Mar 15-16",
      "status": "free" or "light" or "busy",
      "suggestion": "For free/light weekends: a specific date night idea, family activity, or lazy weekend celebration. For busy weekends: a brief heads-up about what's going on."
    }}
  ],
  "conflicts": [
    {{
      "events": ["Event A", "Event B"],
      "date": "YYYY-MM-DD",
      "description": "Brief description of the conflict"
    }}
  ]
}}

Rules:
- action_items: things the husband must DO, show up for, drive someone to, handle childcare around, buy gifts for, RSVP to. When wife is busy, call out that he's on duty.
- fyi_events: everything else, grouped by date. These are visibility items.
- weekend_outlook: one entry per weekend in the window. Use the weekend analysis data provided.
- conflicts: any overlapping or double-booked events. Empty array if none.
- Return ONLY the JSON object, nothing else.""",
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Strip code fences if the model wraps them despite instructions
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    return json.loads(raw)


def rebuild_index(history_dir):
    """Rebuild index.json from all snapshot files in the history directory."""
    snapshots = []
    for path in sorted(history_dir.glob("*.json"), reverse=True):
        if path.name == "index.json":
            continue
        try:
            data = json.loads(path.read_text())
            snapshots.append(
                {
                    "timestamp": path.stem,
                    "generated_at": data.get("generated_at", ""),
                    "event_count": data.get("event_count", 0),
                }
            )
        except (json.JSONDecodeError, KeyError):
            continue

    index_path = history_dir / "index.json"
    index_path.write_text(json.dumps(snapshots, indent=2))
    print(f"Index updated: {len(snapshots)} snapshots")


def main():
    try:
        print("Loading Google credentials...")
        creds = load_credentials()

        print("Fetching calendar events...")
        events = fetch_events(creds)
        print(f"Found {len(events)} events in the next {LOOK_AHEAD_DAYS} days")

        print("Analyzing weekends...")
        weekend_analysis = analyze_weekends(events)

        events_text = format_events_as_text(events)

        print("Generating briefing with Claude...")
        briefing = generate_briefing(events_text, weekend_analysis)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)

        snapshot = {
            "generated_at": datetime.now().isoformat(),
            "look_ahead_days": LOOK_AHEAD_DAYS,
            "event_count": len(events),
            "events": events,
            "briefing": briefing,
            "weekend_analysis": weekend_analysis,
        }
        snapshot_path = HISTORY_DIR / f"{timestamp}.json"
        snapshot_path.write_text(json.dumps(snapshot, indent=2))
        print(f"Snapshot saved to {snapshot_path}")

        rebuild_index(HISTORY_DIR)

        print("Done!")

    except Exception:
        error = traceback.format_exc()
        print(f"ERROR: {error}")


if __name__ == "__main__":
    main()
