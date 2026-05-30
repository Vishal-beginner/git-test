import asyncio
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class TelegramChannel:
    def __init__(self):
        self.token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.app = None
        self.running = False
        self._default_agent_id: Optional[str] = None
        self._message_handler: Optional[Callable] = None

    def set_agent_handler(self, handler: Callable):
        self._message_handler = handler

    def set_default_agent(self, agent_id: str):
        self._default_agent_id = agent_id

    async def start(self):
        if not self.token:
            logger.info("TELEGRAM_BOT_TOKEN not set — Telegram integration disabled")
            return

        try:
            from telegram.ext import (
                Application, CommandHandler, MessageHandler, filters,
            )
            from telegram import Update
            from telegram.ext import ContextTypes

            app = Application.builder().token(self.token).build()

            async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
                await update.message.reply_text(
                    "Hi! I'm an AI agent. Send me a message and I'll respond."
                )

            async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
                await update.message.reply_text(
                    "Send any text and I'll process it through the configured AI agent.\n"
                    "/start — greeting\n/help — this message"
                )

            async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
                if not update.message or not update.message.text:
                    return
                text = update.message.text
                chat_id = str(update.message.chat_id)
                username = (update.message.from_user.username or "user")

                logger.info("Telegram[%s]: %s", username, text[:60])

                from ..core.message_bus import message_bus
                await message_bus.emit("channel_message", {
                    "channel": "telegram",
                    "from": username,
                    "content": text,
                })

                if self._message_handler:
                    try:
                        await update.message.reply_text("⏳ Processing…")
                        reply = await self._message_handler(text, chat_id, "telegram")
                        if reply:
                            await update.message.reply_text(reply)
                            await message_bus.emit("channel_response", {
                                "channel": "telegram",
                                "to": username,
                                "content": reply[:200],
                            })
                    except Exception as exc:
                        logger.error("Telegram handler error: %s", exc)
                        await update.message.reply_text(f"Error: {str(exc)[:100]}")
                else:
                    await update.message.reply_text(
                        "No agent configured. Connect one in the platform UI."
                    )

            app.add_handler(CommandHandler("start", cmd_start))
            app.add_handler(CommandHandler("help", cmd_help))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

            self.app = app
            self.running = True
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot is running")

            # Keep alive until cancelled
            while self.running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Telegram bot error: %s", exc)
        finally:
            await self.stop()

    async def stop(self):
        if self.app and self.running:
            try:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except Exception:
                pass
            self.running = False
            logger.info("Telegram bot stopped")

    async def send_message(self, chat_id: str, text: str):
        if self.app and self.running:
            try:
                await self.app.bot.send_message(chat_id=chat_id, text=text)
            except Exception as exc:
                logger.error("Telegram send error: %s", exc)


telegram_channel = TelegramChannel()
