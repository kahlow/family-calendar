# Family Calendar Briefing

A Docker Compose project that generates a daily AI-powered family calendar briefing. A Python container fetches events from all your Google Calendars, sends them to Claude Haiku for summarization, and writes a styled HTML page served by nginx.

Designed for a TerraMaster NAS but works on any Docker host.

## Prerequisites

- Docker and Docker Compose on your NAS (or any Linux host)
- A Google account with calendars you want to include
- An [Anthropic API key](https://console.anthropic.com/)

## Step 1: Google Cloud Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and create a new project (e.g., "Family Calendar Briefing")
2. Navigate to **APIs & Services > Library**, search for **Google Calendar API**, and enable it
3. Go to **APIs & Services > OAuth consent screen**:
   - Choose **External** user type
   - Fill in the app name and your email
   - Add your email as a **test user**
   - Click through the rest with defaults
4. Go to **APIs & Services > Credentials**:
   - Click **Create Credentials > OAuth client ID**
   - Choose **Desktop app** as the application type
   - Download the JSON file and save it as `credentials.json` in this project directory

> **Important**: By default your app is in "Testing" mode and tokens expire after 7 days. To get long-lived tokens, go back to the **OAuth consent screen** and click **Publish App**. No Google verification is needed for personal use with fewer than 100 users.

## Step 2: Generate token.json

On your local machine (not the NAS), install dependencies and run the token generator:

```bash
pip install google-auth-oauthlib google-api-python-client
python generate_token.py
```

A browser window will open. Sign in with your Google account and allow calendar access.

If you see **"This app isn't verified"**, click **Advanced** then **Go to [app name] (unsafe)**.

Verify that `token.json` was created and contains a `refresh_token` field:
```bash
cat token.json | python -m json.tool | grep refresh_token
```

## Step 3: Deploy to NAS

1. Copy this project to your NAS

2. Create the required directories and place your token:
   ```bash
   mkdir -p /volume1/docker/family-calendar-briefing/html
   cp token.json /volume1/docker/family-calendar-briefing/token.json
   ```

3. Create your `.env` file:
   ```bash
   cp .env.example .env
   # Edit .env with your Anthropic API key and timezone
   ```

4. Start the stack:
   ```bash
   docker compose up -d
   ```

The briefing will generate automatically at 6:00 AM daily (in your configured timezone).

## Step 4: Test

Run a manual sync to verify everything works:

```bash
./run_now.sh
```

Then visit `http://<nas-ip>:8090` in your browser.

Check logs if something went wrong:
```bash
docker compose logs calendar-sync
```

## Troubleshooting

**"token.json not found" or credential errors**
- Make sure `token.json` is at `/volume1/docker/family-calendar-briefing/token.json`
- Re-run `python generate_token.py` if needed

**"Token has been expired or revoked"**
- If your app is still in "Testing" mode, tokens expire after 7 days
- Publish your app (Step 1) and regenerate `token.json` (Step 2)

**"Invalid API key" from Anthropic**
- Check your `.env` file has a valid `ANTHROPIC_API_KEY`

**No events showing up**
- Verify the Google account has calendars with events in the next 14 days
- Check that the Calendar API is enabled in Google Cloud Console

**Briefing not updating daily**
- Check that the container is running: `docker compose ps`
- Verify timezone: `docker compose exec calendar-sync date`
- Check logs: `docker compose logs --tail 50 calendar-sync`
