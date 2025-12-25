# Bot Logic Documentation

This document defines all possible **Module**, **Submodule**, **Intent**, and **Action** combinations used by the Tulip WhatsApp bot.

---

## Hierarchy Overview

```
├── Module: Base
│   ├── Submodule: Main
│   │   └── Intents: Greet, Ask, Other
│   └── Submodule: Settings
│       └── Intents: Create whitelist, Read whitelist, Delete whitelist
│
└── Module: Meal
    └── Submodule: Main
        └── Intents: Other
```

---

## Modules

### Base
The default module for general interactions and bot configuration.

| Submodule | Intent | Description |
|-----------|--------|-------------|
| Main | Greet | User is greeting the bot (e.g., "Hi", "Hello", "Good morning") |
| Main | Ask | User is asking a general question |
| Main | Other | Any other general interaction that doesn't fit above intents |
| Settings | Create whitelist | User wants to add a phone number to the whitelist |
| Settings | Read whitelist | User wants to view the current whitelist |
| Settings | Delete whitelist | User wants to remove a phone number from the whitelist |

### Meal
Module for meal planning and food-related features.

| Submodule | Intent | Description |
|-----------|--------|-------------|
| Main | Other | General meal-related interactions |

---

## Actions

Actions are operations that modify data. They are only triggered when the intent requires a state change.

| Action Type | Trigger Intent | Description | Required Value |
|-------------|----------------|-------------|----------------|
| `add_whitelist` | Create whitelist | Adds a phone number to the whitelist | Phone number (string) |
| `remove_whitelist` | Delete whitelist | Removes a phone number from the whitelist | Phone number (string) |

### Action Format

Actions are returned as a list of objects:

```json
{
  "actions": [
    {"type": "add_whitelist", "value": "628123456789"},
    {"type": "remove_whitelist", "value": "628987654321"}
  ]
}
```

- **Multiple actions** can be performed in a single request (e.g., adding multiple numbers)
- **Empty actions** (`[]`) means no data modification is needed
- Action display in bot reply shows "None" when no actions are performed

---

## Reply Format

Every bot reply includes the following metadata header:

```
Module: <module_name>
Submodule: <submodule_name>
Intent: <detected_intent>
Action: <action_type(s) or "None">
Model: <ai_model_used>

<reply_content>
```

### Example Replies

**General Greeting:**
```
Module: Base
Submodule: Main
Intent: Greet
Action: None
Model: gemini-2.0-flash

Hello! How can I help you today?
```

**Adding to Whitelist:**
```
Module: Base
Submodule: Settings
Intent: Create whitelist
Action: add_whitelist
Model: gemini-2.0-flash

Done! I've added 628123456789 to the whitelist.
```

**Multiple Actions:**
```
Module: Base
Submodule: Settings
Intent: Delete whitelist
Action: remove_whitelist, remove_whitelist
Model: gemini-2.0-flash

I've removed both numbers from the whitelist.
```

---

## Session State

The bot maintains session state per user:

- **active_module**: Current module the user is in
- **active_submodule**: Current submodule within the module
- **history**: Conversation history (last 20 messages)

The AI uses this context to determine appropriate routing and maintain conversational continuity.
