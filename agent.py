"""Morning Briefing Agent — Gmail, Calendar, and Slack daily briefing."""

import json
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from strands import Agent, tool
from strands.models.litellm import LiteLLMModel

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

SYSTEM_PROMPT = """You are a Morning Briefing Agent. Your job is to summarize what the user \
missed overnight and help them start their day.

Before writing the briefing, you MUST call all three tools in this exact order:
1. check_gmail
2. check_calendar
3. check_slack

After gathering data from all three tools, write the final briefing using these exact section \
headings (in this order):

URGENT
UPCOMING EVENTS
SLACK HIGHLIGHTS
OTHER EMAILS
SUGGESTED ACTIONS

Guidelines:
- URGENT: Time-sensitive emails, imminent calendar conflicts, or Slack messages needing action.
- UPCOMING EVENTS: Summarize calendar events from check_calendar.
- SLACK HIGHLIGHTS: Notable recent Slack conversations from check_slack.
- OTHER EMAILS: Remaining unread emails that are not urgent.
- SUGGESTED ACTIONS: Concrete next steps based on everything you found.

Keep the briefing concise and actionable."""


def get_google_credentials() -> Credentials:
    """Load, refresh, or obtain Google OAuth credentials for Gmail and Calendar."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds


@tool
def check_gmail(hours_back: int = 12) -> dict:
    """Fetch unread Gmail messages from the last N hours.

    #Args:
        hours_back: How many hours back to search for unread emails (default: 12).

    #Returns:
        A list of unread emails with sender, subject, date, and a 200-character snippet.
    """
    try:
        creds = get_google_credentials()
        service = build("gmail", "v1", credentials=creds)

        cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp() * 1000
        )

        results = (
            service.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=50)
            .execute()
        )

        emails = []
        for msg_ref in results.get("messages", []):
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )

            if int(msg.get("internalDate", 0)) < cutoff_ms:
                continue

            headers = {
                header["name"]: header["value"]
                for header in msg.get("payload", {}).get("headers", [])
            }
            emails.append(
                {
                    "sender": headers.get("From", "Unknown"),
                    "subject": headers.get("Subject", "(No subject)"),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", "")[:200],
                }
            )

        return {
            "status": "success",
            "content": [{"text": json.dumps(emails, indent=2)}],
        }
    except Exception as exc:
        return {
            "status": "error",
            "content": [{"text": f"Failed to fetch Gmail: {exc}"}],
        }


@tool
def check_calendar(hours_ahead: int = 24) -> dict:
    """Fetch upcoming Google Calendar events for the next N hours.

    #Args:
        hours_ahead: How many hours ahead to look for events (default: 24).

    #Returns:
        A list of events with title, start, end, location, and attendees.
    """
    try:
        creds = get_google_credentials()
        service = build("calendar", "v3", credentials=creds)

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(hours=hours_ahead)).isoformat()

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = []
        for event in events_result.get("items", []):
            start = event.get("start", {})
            end = event.get("end", {})
            attendees = [
                attendee.get("email", attendee.get("displayName", "Unknown"))
                for attendee in event.get("attendees", [])
            ]
            events.append(
                {
                    "title": event.get("summary", "(No title)"),
                    "start": start.get("dateTime", start.get("date", "")),
                    "end": end.get("dateTime", end.get("date", "")),
                    "location": event.get("location", ""),
                    "attendees": attendees,
                }
            )

        return {
            "status": "success",
            "content": [{"text": json.dumps(events, indent=2)}],
        }
    except Exception as exc:
        return {
            "status": "error",
            "content": [{"text": f"Failed to fetch calendar: {exc}"}],
        }


@tool
def check_slack(hours_back: int = 12, max_channels: int = 5) -> dict:
    """Fetch recent Slack messages from the most recently active channels.

    #Args:
        hours_back: How many hours back to fetch messages (default: 12).
        max_channels: Number of most recently active channels to check (default: 5).

    #Returns:
        Channel names and up to 5 recent messages per channel.
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        return {
            "status": "error",
            "content": [{"text": "SLACK_BOT_TOKEN was not found in the .env file."}],
        }

    try:
        client = WebClient(token=token)
        oldest = str(
            (datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp()
        )

        channel_activity = []
        cursor = None
        while True:
            response = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )
            for channel in response.get("channels", []):
                try:
                    history = client.conversations_history(
                        channel=channel["id"],
                        limit=1,
                    )
                    messages = history.get("messages", [])
                    if messages:
                        last_active = float(messages[0]["ts"])
                        channel_activity.append((last_active, channel))
                except SlackApiError:
                    continue

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        channel_activity.sort(key=lambda item: item[0], reverse=True)
        top_channels = channel_activity[:max_channels]

        results = []
        for _, channel in top_channels:
            history = client.conversations_history(
                channel=channel["id"],
                oldest=oldest,
                limit=5,
            )
            messages = []
            for message in history.get("messages", []):
                if message.get("subtype"):
                    continue
                messages.append(
                    {
                        "user": message.get("user", "unknown"),
                        "text": message.get("text", "")[:200],
                        "timestamp": message.get("ts", ""),
                    }
                )

            results.append(
                {
                    "channel": channel.get("name", channel["id"]),
                    "messages": messages[:5],
                }
            )

        return {
            "status": "success",
            "content": [{"text": json.dumps(results, indent=2)}],
        }
    except Exception as exc:
        return {
            "status": "error",
            "content": [{"text": f"Failed to fetch Slack: {exc}"}],
        }


def create_model() -> LiteLLMModel:
    """Build the LiteLLM model backed by OpenRouter."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY was not found in the .env file.")

    return LiteLLMModel(
        model_id="openrouter/openrouter/free",
        client_args={
            "api_key": api_key,
            "api_base": "https://openrouter.ai/api/v1",
        },
        params={
            "max_tokens": 4096,
        },
    )


def create_agent() -> Agent:
    """Create and return a configured Morning Briefing Agent."""
    return Agent(
        model=create_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=[check_gmail, check_calendar, check_slack],
        name="Morning Briefing Agent",
        description="Summarizes Gmail, Calendar, and Slack into a daily briefing.",
    )


def run() -> str:
    """Generate and return the morning briefing."""
    agent = create_agent()
    response = agent("What did I miss? Give me my morning briefing.")
    return str(response)


if __name__ == "__main__":
    print(run())
