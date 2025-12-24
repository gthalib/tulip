# Tulip

A WhatsApp bot using Kapso API and Gemini for intent analysis.

## Features

- Intent analysis via Gemini (or OpenRouter fallback)
- Session persistence in SQLite
- Modular design (Base, Meal modules)
- Phone number whitelisting
- Background webhook processing

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Create a `.env` file:

```ini
KAPSO_API_KEY=
PHONE_NUMBER_ID=
AI_PROCESSOR=gemini        # or openrouter
GEMINI_API_KEY=
OPENROUTER_API_KEY=        # if using openrouter
```

## Usage

```bash
python bot.py
```

Set up Kapso webhooks to point to `https://your-domain.com/webhook`.

## Project Structure

- `bot.py` - Main bot logic
- `bot.db` - SQLite database (auto-created)
- `bot.log` - Runtime logs

## Modules

**Base** - General chat, settings (whitelist management)  
**Meal** - Placeholder for meal planning

## Extending

1. Create a class inheriting from `Module`
2. Implement the `handle` method
3. Register in `WhatsAppBot.modules`
4. Update the prompt in `analyze_intent`
