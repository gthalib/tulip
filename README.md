# Tulip

A WhatsApp bot built with FastAPI, Kapso API, and AI-powered intent analysis (Gemini or OpenRouter).

## Features

- **AI Intent Analysis** - Uses Gemini or OpenRouter for conversational understanding
- **Model Failover** - Automatic model suspension (24h) on failure with fallback
- **Session Persistence** - Conversation history stored in SQLite (survives restarts)
- **Modular Architecture** - Extensible module system (Base, Meal)
- **Phone Whitelist** - Built-in access control via whitelist management
- **Background Processing** - Non-blocking webhook handling via FastAPI BackgroundTasks
- **Typing Indicator** - Auto-refreshing typing indicator during AI processing
- **Signature Verification** - Optional Meta webhook signature validation

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Create a `.env` file (see `.env.example`):

```ini
# Required
KAPSO_API_KEY=your_kapso_api_key
PHONE_NUMBER_ID=your_phone_number_id

# AI Processor (choose one)
AI_PROCESSOR=gemini              # or 'openrouter'
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.0-flash    # model to use

# OpenRouter (alternative)
OPENROUTER_API_KEY=your_key
OPENROUTER_MODELS=model1,model2  # comma-separated, tries in order

# Optional
WEBHOOK_VERIFY_TOKEN=123         # for Meta webhook verification
META_APP_SECRET=                 # optional signature verification
WHITELISTED_NUMBERS=628...,62... # initial whitelist (comma-separated)
PORT=5001
DEBUG=true                       # enables hot reload
```

## Usage

```bash
python bot.py
```

The server starts on `http://0.0.0.0:5001` by default.

Configure your Kapso webhooks to point to `https://your-domain.com/webhook`.

## Project Structure

```
tulip/
├── bot.py          # Main application (FastAPI routes, bot logic, modules)
├── bot.db          # SQLite database (sessions, whitelist, models)
├── bot.log         # Runtime logs
├── requirements.txt
└── .env
```

## Architecture

### Database Tables

| Table | Purpose |
|-------|---------|
| `sessions` | User sessions with module state and conversation history |
| `whitelist` | Authorized phone numbers |
| `models` | AI model registry with suspension tracking |

### Modules

| Module | Submodules | Description |
|--------|------------|-------------|
| **Base** | Main, Settings | General chat and whitelist management |
| **Meal** | Main | Meal planning (placeholder) |

### Intents

**Base/Main**: `Greet`, `Ask`, `Other`  
**Base/Settings**: `Create whitelist`, `Read whitelist`, `Delete whitelist`

## Extending

1. Create a class inheriting from `Module`
2. Implement the `async handle()` method
3. Register in `WhatsAppBot.modules`
4. Update the prompt in `analyze_intent()`

Example:
```python
class FinanceModule(Module):
    async def handle(self, session, message, submodule, intent, ai_reply, action=None):
        # Your logic here
        return ai_reply
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/webhook` | Meta webhook verification |
| `POST` | `/webhook` | Incoming message handler |

## License

See [LICENSE](LICENSE) for details.
