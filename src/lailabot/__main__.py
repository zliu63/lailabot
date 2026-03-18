import asyncio
import os
import sys

from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from lailabot.approval_server import ApprovalServer
from lailabot.telegram_bot import LailaBot
from lailabot.logger import setup_logger


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    user_id = os.environ.get("TELEGRAM_USER_ID")

    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is required")
        sys.exit(1)
    if not user_id:
        print("Error: TELEGRAM_USER_ID environment variable is required")
        sys.exit(1)

    socket_path = os.environ.get("LAILABOT_SOCKET", "/tmp/lailabot-approval.sock")

    logger = setup_logger()
    logger.info("Starting LailaBot...")

    bot = LailaBot(
        bot_token=bot_token,
        authorized_user_id=int(user_id),
    )

    approval_server = ApprovalServer(socket_path=socket_path)
    approval_server.on_request = bot.handle_approval_request
    bot.approval_server = approval_server

    app = ApplicationBuilder().token(bot_token).build()

    bot._telegram_bot = app.bot

    app.add_handler(CommandHandler("start", bot.handle_start))
    app.add_handler(CommandHandler("new", bot.handle_new))
    app.add_handler(CommandHandler("ls", bot.handle_ls))
    app.add_handler(CommandHandler("list", bot.handle_list))
    app.add_handler(CommandHandler("kill", bot.handle_kill))
    app.add_handler(CommandHandler("set_default", bot.handle_set_default))
    app.add_handler(CommandHandler("send", bot.handle_send))
    app.add_handler(CallbackQueryHandler(bot.handle_approval_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    async def post_init(application):
        await approval_server.start()
        logger.info(f"Approval server listening on {socket_path}")

    async def post_shutdown(application):
        await approval_server.stop()

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    logger.info("LailaBot started. Polling for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
