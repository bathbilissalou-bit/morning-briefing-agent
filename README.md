# Morning Briefing Agent

A Python AI agent that uses Strands, LiteLLM, and OpenRouter to create a prioritized morning briefing from Gmail, Google Calendar, and Slack.

## Features

- Checks unread Gmail messages
- Retrieves upcoming Google Calendar events
- Reads recent Slack messages
- Uses an AI model to organize the results into:
  - URGENT
  - UPCOMING EVENTS
  - SLACK HIGHLIGHTS
  - OTHER EMAILS
  - SUGGESTED ACTIONS

## Technology

- Python
- Strands Agents
- LiteLLM
- OpenRouter
- Gmail API
- Google Calendar API
- Slack SDK

## Security

Private credentials are excluded from GitHub through `.gitignore`, including:

- `.env`
- `credentials.json`
- `token.json`
- `.venv/`

## Run the model test

```bash
python test_model.py
