import os
import logging
import json
import sqlite3
import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from google import genai
from openai import AsyncOpenAI
from kapso_whatsapp import WhatsAppClient
from kapso_whatsapp.webhooks import normalize_webhook, verify_signature

load_dotenv()

@dataclass
class Config:
    """Application configuration."""
    KAPSO_API_KEY: str = os.getenv("KAPSO_API_KEY")
    PHONE_NUMBER_ID: str = os.getenv("PHONE_NUMBER_ID")
    VERIFY_TOKEN: str = os.getenv("WEBHOOK_VERIFY_TOKEN", "123")
    APP_SECRET: str = os.getenv("META_APP_SECRET")  # Optional: for signature verification
    PORT: int = int(os.getenv("PORT", 5001))
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    BASE_URL: str = "https://api.kapso.ai/meta/whatsapp"
    AI_PROCESSOR: str = os.getenv("AI_PROCESSOR", "gemini").lower()
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY")
    DATABASE_PATH: str = "bot.db"

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("WhatsAppBot")

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS whitelist (phone_number TEXT PRIMARY KEY)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    processor TEXT,
                    name TEXT,
                    suspended_until TIMESTAMP,
                    error_counter INTEGER DEFAULT 0,
                    last_error TEXT,
                    PRIMARY KEY (processor, name)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    phone_number TEXT PRIMARY KEY,
                    active_module TEXT DEFAULT 'Base',
                    active_submodule TEXT DEFAULT 'Main',
                    history TEXT DEFAULT '[]'
                )
            """)
            conn.commit()

    def get_session(self, phone_number: str) -> 'Session':
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT active_module, active_submodule, history FROM sessions WHERE phone_number = ?", (phone_number,))
            row = cursor.fetchone()
            if row:
                return Session(
                    phone_number=phone_number,
                    active_module=row[0],
                    active_submodule=row[1],
                    history=json.loads(row[2])
                )
            return Session(phone_number=phone_number)

    def save_session(self, session: 'Session'):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO sessions (phone_number, active_module, active_submodule, history) 
                VALUES (?, ?, ?, ?)
                ON CONFLICT(phone_number) DO UPDATE SET
                    active_module = excluded.active_module,
                    active_submodule = excluded.active_submodule,
                    history = excluded.history
            """, (session.phone_number, session.active_module, session.active_submodule, json.dumps(session.history)))
            conn.commit()

    def get_available_models(self, processor: str) -> list[str]:
        now = datetime.now()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT name FROM models 
                WHERE processor = ? 
                AND (suspended_until IS NULL OR suspended_until < ?)
                ORDER BY error_counter ASC
            """, (processor, now))
            return [row[0] for row in cursor.fetchall()]

    def suspend_model(self, processor: str, name: str, error_msg: str):
        suspended_until = datetime.now() + timedelta(hours=24)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO models (processor, name, suspended_until, error_counter, last_error) 
                VALUES (?, ?, ?, 1, ?) 
                ON CONFLICT(processor, name) DO UPDATE SET 
                    suspended_until = excluded.suspended_until,
                    error_counter = error_counter + 1,
                    last_error = excluded.last_error
            """, (processor, name, suspended_until, error_msg))
            conn.commit()

    def add_model(self, processor: str, name: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO models (processor, name) VALUES (?, ?)", (processor, name))
            conn.commit()

    def is_whitelisted(self, phone_number: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM whitelist WHERE phone_number = ?", (phone_number,))
            return cursor.fetchone() is not None

    def get_whitelist(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT phone_number FROM whitelist")
            return [row[0] for row in cursor.fetchall()]

    def add_to_whitelist(self, phone_number: str):
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("INSERT OR IGNORE INTO whitelist (phone_number) VALUES (?)", (phone_number,))
                conn.commit()

    def remove_from_whitelist(self, phone_number: str):
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM whitelist WHERE phone_number = ?", (phone_number,))
                conn.commit()

@dataclass
class Session:
    phone_number: str
    active_module: str = "Base"
    active_submodule: str = "Main"
    history: list = field(default_factory=list)

class SessionManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_session(self, phone_number: str) -> Session:
        return self.db.get_session(phone_number)

    def save_session(self, session: Session):
        # Keep history reasonable size (e.g., last 20 messages)
        if len(session.history) > 20:
            session.history = session.history[-20:]
        logger.debug(f"Saving session for {session.phone_number}. History length: {len(session.history)}")
        self.db.save_session(session)

class Module:
    def __init__(self, bot: 'WhatsAppBot'):
        self.bot = bot

    async def handle(self, session: Session, message: dict, submodule: str, intent: str, ai_reply: str, action: dict = None) -> str:
        raise NotImplementedError

class BaseModule(Module):
    async def handle(self, session: Session, message: dict, submodule: str, intent: str, ai_reply: str, action: dict = None) -> str:
        if submodule == "Settings":
            if action:
                action_type = action.get("type", "").lower()
                value = action.get("value")
                
                logger.debug(f"Settings Action: {action_type} with value: {value}")
                
                if action_type in ["add_whitelist", "create_whitelist"] and value:
                    self.bot.db.add_to_whitelist(value)
                    logger.info(f"Successfully added {value} to whitelist via AI action")
                elif action_type in ["remove_whitelist", "delete_whitelist"] and value:
                    self.bot.db.remove_from_whitelist(value)
                    logger.info(f"Successfully removed {value} from whitelist via AI action")
            
            # For 'Read whitelist', we ensure the current list is shown
            if intent == "Read whitelist" or "read" in intent.lower():
                current_list = self.bot.db.get_whitelist()
                if not current_list:
                    return f"{ai_reply}\n\n*The whitelist is currently empty.*"
                list_str = "\n".join([f"- {n}" for n in current_list])
                return f"{ai_reply}\n\n*Current Whitelist:*\n{list_str}"
        
        return ai_reply

class MealModule(Module):
    async def handle(self, session: Session, message: dict, submodule: str, intent: str, ai_reply: str, action: dict = None) -> str:
        return ai_reply

class WhatsAppBot:
    """Main bot logic for handling WhatsApp events."""
    
    def __init__(self, config: Config):
        self.config = config
        self.ai_processor = config.AI_PROCESSOR
        self.db = DatabaseManager(config.DATABASE_PATH)
        
        # Load models and whitelist from environment
        initial_whitelist = os.getenv("WHITELISTED_NUMBERS", "")
        if initial_whitelist:
            for n in initial_whitelist.split(","):
                if n.strip():
                    self.db.add_to_whitelist(n.strip())

        gemini_model = os.getenv("GEMINI_MODEL")
        if gemini_model:
            self.db.add_model("gemini", gemini_model)
        
        or_models = os.getenv("OPENROUTER_MODELS")
        if or_models:
            for m in or_models.split(","):
                if m.strip():
                    self.db.add_model("openrouter", m.strip())

        self.session_manager = SessionManager(self.db)
        self.modules = {
            "Base": BaseModule(self),
            "Meal": MealModule(self)
        }

    async def analyze_intent(self, text: str, session: Session) -> tuple[str, str, str, str, str, list]:
        if not text:
            return session.active_module, "Main", "Other", "How can I help you today?", "None", []

        history_str = "\n".join([f"{'User' if m['role'] == 'user' else 'Bot'}: {m['content']}" for m in session.history[-5:]])
        prompt = (
            "Analyze the following message for a personal assistant bot.\n"
            "The hierarchy is:\n"
            "- Module: Base\n"
            "  - Submodule: Main | Intents: Greet, Ask, Other\n"
            "  - Submodule: Settings | Intents: Create whitelist, Read whitelist, Delete whitelist\n"
            "- Module: Meal\n"
            "  - Submodule: Main | Intents: Other\n\n"
            f"User is CURRENTLY in: Module={session.active_module}, Submodule={session.active_submodule}\n\n"
            "Instructions:\n"
            "1. Decide the appropriate Module, Submodule, and Intent.\n"
            "2. Generate a friendly, helpful reply.\n"
            "3. If the user refers to values from previous messages (e.g., 'the last two numbers', 'the email I sent'), EXTRACT those values from the 'Conversation History'.\n"
            "4. Action mapping for Settings (REQUIRED if intent involves changing data):\n"
            "   - 'Create whitelist' -> {\"type\": \"add_whitelist\", \"value\": \"phone number\"}\n"
            "   - 'Delete whitelist' -> {\"type\": \"remove_whitelist\", \"value\": \"phone number\"}\n"
            "   - If they want to remove MULTIPLE things, include MULTIPLE action objects in the list.\n\n"
            "Reply with ONLY a JSON object:\n"
            "{\n"
            "  \"module\": \"Base\" or \"Meal\",\n"
            "  \"submodule\": \"Main\" or \"Settings\",\n"
            "  \"intent\": \"specified intent\",\n"
            "  \"reply\": \"Friendly response\",\n"
            "  \"actions\": [{\"type\": \"add_whitelist\", \"value\": \"628...\"}, ...] (List, can be empty)\n"
            "}\n\n"
            "Conversation History:\n"
            f"{history_str}\n\n"
            f"New Message: {text}"
        )

        try:
            clean_text = ""
            available_models = self.db.get_available_models(self.ai_processor)
            
            if not available_models:
                raise Exception(f"No available models for {self.ai_processor} (all might be suspended)")

            for model in available_models:
                try:
                    if self.ai_processor == "openrouter" and self.config.OPENROUTER_API_KEY:
                        async with AsyncOpenAI(
                            api_key=self.config.OPENROUTER_API_KEY,
                            base_url="https://openrouter.ai/api/v1"
                        ) as or_client:
                            logger.debug(f"Attempting OpenRouter with model: {model}")
                            response = await or_client.chat.completions.create(
                                model=model,
                                messages=[
                                    {"role": "system", "content": "You are a helpful personal assistant bot. Reply ONLY with JSON."},
                                    {"role": "user", "content": prompt}
                                ],
                                response_format={"type": "json_object"},
                                timeout=30.0
                            )
                            clean_text = response.choices[0].message.content.strip()
                    elif self.ai_processor == "gemini" and self.config.GEMINI_API_KEY:
                        logger.debug(f"Attempting Gemini with model: {model}")
                        client = genai.Client(api_key=self.config.GEMINI_API_KEY)
                        response = await client.aio.models.generate_content(
                            model=model,
                            contents=prompt
                        )
                        clean_text = response.text.strip().replace("```json", "").replace("```", "").strip()
                    
                    if clean_text:
                        logger.info(f"{self.ai_processor.capitalize()} success with model: {model}")
                        logger.info(f"AI Response Body: {clean_text}")
                        break
                except Exception as model_err:
                    error_str = str(model_err)
                    logger.warning(f"{self.ai_processor.capitalize()} model {model} failed: {error_str}. Suspending for 24h.")
                    self.db.suspend_model(self.ai_processor, model, error_str)
                    continue

            if not clean_text:
                raise Exception(f"All models for {self.ai_processor} failed.")

            data = json.loads(clean_text)
            module = data.get("module", session.active_module)
            submodule = data.get("submodule", "Main")
            intent = data.get("intent", "Other")
            ai_reply = data.get("reply", "I'm here to help!")
            
            actions = data.get("actions", [])
            
            if module not in self.modules:
                module = "Base"
                
            return module, submodule, intent, ai_reply, model, actions

        except Exception as e:
            logger.error(f"{self.ai_processor.capitalize()} analysis failed: {e}")
            return session.active_module, "Main", "Other", "I'm sorry, I'm having trouble processing that right now.", "None", []

    async def handle_message(self, message: dict, phone_number_id: str):
        kapso_ext = message.get("kapso", {})
        direction = kapso_ext.get("direction", "inbound")
        
        if direction == "outbound":
            return

        from_number = message.get("from")
        if not self.db.is_whitelisted(from_number):
            logger.info(f"Ignoring message from {from_number}")
            return

        text_body = message.get("text", {}).get("body", "")
        message_id = message.get("id")
        logger.info(f"Incoming from {from_number}: '{text_body}'")

        if not self.config.KAPSO_API_KEY:
            logger.error("KAPSO_API_KEY not configured")
            return
        try:
            async with WhatsAppClient(
                kapso_api_key=self.config.KAPSO_API_KEY,
                base_url=self.config.BASE_URL
            ) as client:
                if message_id:
                    await client.messages.mark_read(
                        phone_number_id=phone_number_id,
                        message_id=message_id,
                        typing_indicator={"type": "text"}
                    )

                session = self.session_manager.get_session(from_number)
                session.history.append({"role": "user", "content": text_body})
                logger.debug(f"Loaded session for {from_number}. New history length: {len(session.history)}")
                self.session_manager.save_session(session)

                async def typing_refresher():
                    """Keep the typing indicator active by refreshing it every 15 seconds."""
                    while True:
                        await asyncio.sleep(15)
                        try:
                            if message_id:
                                logger.debug(f"Refreshing typing indicator for {from_number}")
                                await client.messages.mark_read(
                                    phone_number_id=phone_number_id,
                                    message_id=message_id,
                                    typing_indicator={"type": "text"}
                                )
                        except Exception as e:
                            logger.debug(f"Failed to refresh typing indicator: {e}")

                typing_task = asyncio.create_task(typing_refresher())

                try:
                    new_module, new_submodule, intent, ai_reply, model_name, actions = await self.analyze_intent(text_body, session)

                    session.active_module = new_module
                    session.active_submodule = new_submodule

                    module_handler = self.modules.get(session.active_module, self.modules["Base"])
                    
                    reply_from_module = ""
                    if not actions:
                        reply_from_module = await module_handler.handle(session, message, new_submodule, intent, ai_reply, None)
                    else:
                        for act in actions:
                            reply_from_module = await module_handler.handle(session, message, new_submodule, intent, ai_reply, act)

                    final_reply = (
                        f"Module: {session.active_module}\n"
                        f"Intent: {intent}\n"
                        f"Model: {model_name}\n\n"
                        f"{reply_from_module}"
                    )
                    
                    session.history.append({"role": "assistant", "content": final_reply})
                    self.session_manager.save_session(session)

                    await client.messages.send_text(
                        phone_number_id=phone_number_id,
                        to=from_number,
                        body=final_reply
                    )
                finally:
                    if not typing_task.done():
                        typing_task.cancel()
        except Exception as e:
            logger.error(f"Failed to process message/reply: {e}")

app = Flask(__name__)
bot_config = Config()
bot = WhatsAppBot(bot_config)

@app.route("/webhook", methods=["GET"])
async def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == bot_config.VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return challenge, 200
    
    logger.warning("Webhook verification failed")
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
async def webhook():
    raw_body = request.get_data()
    payload = request.get_json()

    if bot_config.APP_SECRET:
        signature = request.headers.get("X-Hub-Signature-256")
        if not verify_signature(app_secret=bot_config.APP_SECRET, raw_body=raw_body, signature_header=signature):
            logger.warning("Invalid webhook signature")
            return "Invalid signature", 401

    logger.debug(f"Received raw payload:\n{json.dumps(payload, indent=2)}")

    import threading

    def start_background_task(p):
        async def run_processing(p_inner):
            try:
                result = normalize_webhook(p_inner)
                pn_id = result.phone_number_id or bot_config.PHONE_NUMBER_ID

                if not result.messages and "data" in p_inner and isinstance(p_inner["data"], list):
                    for item in p_inner["data"]:
                        msg = item.get("message")
                        item_pn_id = item.get("phone_number_id")
                        if msg:
                            await bot.handle_message(msg, item_pn_id or pn_id)
                else:
                    for msg in result.messages:
                        await bot.handle_message(msg, pn_id)
            except Exception as e:
                logger.error(f"Background webhook processing error: {e}", exc_info=True)

        asyncio.run(run_processing(p))

    thread = threading.Thread(target=start_background_task, args=(payload,))
    thread.start()

    return jsonify({"status": "accepted"}), 202

if __name__ == "__main__":
    app.run(port=bot_config.PORT, debug=bot_config.DEBUG)
