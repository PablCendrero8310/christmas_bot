import logging
import os
import random
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, request
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    Dispatcher,
    MessageHandler,
    filters,
)

from controllers import ChristmasDB

# ------------------ Configuración ------------------
flask_app = Flask(__name__)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DB = ChristmasDB()
TOKEN = os.getenv("TELEGRAM_TOKEN")
WAITING_FOR_GIF = 1

if not TOKEN:
    logger.error("❌ TELEGRAM_TOKEN no está configurado.")
    exit(1)

# ------------------ Utilidades ------------------


def escape_md2(text: str) -> str:
    """Escapar caracteres especiales de MarkdownV2"""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text


# ------------------ Comandos ------------------


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = escape_md2(
        """
🤖 *Comandos disponibles*:

/start - Inicia el bot
/help - Muestra este mensaje
/villancico - Recibe un villancico
/mandar_meme - Mandar meme al ranking
/votaciones - Da tu voto por el mejor meme
/ranking - Ver el ranking de los mejores memes
"""
    )
    await update.message.reply_text(mensaje, parse_mode="MarkdownV2")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Hola! Bienvenido al bot 🎄")
    await help_command(update, context)


async def carol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ruta = Path("files/")
    try:
        archivos_ogg = [f for f in ruta.iterdir() if f.is_file() and f.suffix == ".ogg"]
        if not archivos_ogg:
            await update.message.reply_text("❌ No hay villancicos disponibles.")
            return
        file = random.choice(archivos_ogg)
        with open(file, "rb") as voice:
            await update.message.reply_voice(voice)
    except Exception as e:
        await update.message.reply_text(f"❌ Error al cargar villancicos: {str(e)}")


# ------------------ Envío de memes ------------------


async def send_meme_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    if DB.has_user_submitted_gif(telegram_id):
        await update.message.reply_text(
            "❌ Ya has enviado un GIF. Solo se permite un GIF por persona."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "🎄 Envía tu GIF de Navidad. Solo se permite un GIF por persona.\n"
        "Usa /cancel para cancelar el envío."
    )
    return WAITING_FOR_GIF


async def receive_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    username = user.username
    message_id = update.message.message_id

    if DB.has_user_submitted_gif(telegram_id):
        await update.message.reply_text("❌ Ya has enviado un GIF anteriormente.")
        return ConversationHandler.END

    file_id: Optional[str] = None
    if update.message.animation:
        file_id = update.message.animation.file_id
    elif update.message.document and update.message.document.mime_type == "image/gif":
        file_id = update.message.document.file_id

    if not file_id:
        await update.message.reply_text("❌ Por favor envía un GIF válido.")
        return WAITING_FOR_GIF

    try:
        DB.add_gif(
            telegram_id=telegram_id,
            username=username or "",
            message_id=message_id,
            file_id=file_id,
        )
        await update.message.reply_text("✅ GIF recibido. ¡Suerte en las votaciones!")
    except ValueError as e:
        await update.message.reply_text(f"❌ {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al guardar el GIF: {str(e)}")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Envío cancelado.")
    return ConversationHandler.END


# ------------------ Carrusel de votación ------------------


async def show_memes_to_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gifs = DB.get_votable_gifs(
        update.effective_user.id, update.effective_user.username or ""
    )
    if not gifs:
        await update.message.reply_text("❌ No hay memes para votar.")
        return
    context.user_data.clear()
    context.user_data["votable_gifs"] = gifs
    context.user_data["current_index"] = 0
    await send_current_gif(update, context)


async def send_current_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        index = context.user_data.get("current_index", 0)
        gifs = context.user_data.get("votable_gifs", [])
        if not gifs or index >= len(gifs):
            context.user_data.clear()
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text(
                    "✅ Has votado todos los memes disponibles."
                )
            elif update.message:
                await update.message.reply_text(
                    "✅ Has votado todos los memes disponibles."
                )
            return

        gif = gifs[index]
        buttons = [[InlineKeyboardButton("⭐ Votar", callback_data=f"vote:{gif.id}")]]
        nav_buttons = []
        if index > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data="prev"))
        nav_buttons.append(
            InlineKeyboardButton(f"{index + 1}/{len(gifs)}", callback_data="counter")
        )
        if index < len(gifs) - 1:
            nav_buttons.append(
                InlineKeyboardButton("➡️ Siguiente", callback_data="next")
            )
        if nav_buttons:
            buttons.append(nav_buttons)
        markup = InlineKeyboardMarkup(buttons)

        if update.callback_query:
            try:
                if update.callback_query.message:
                    await update.callback_query.message.edit_media(
                        media=InputMediaAnimation(
                            media=gif.file_id, caption="🎄 Vota este meme"
                        ),
                        reply_markup=markup,
                    )
                else:
                    await context.bot.send_animation(
                        chat_id=update.callback_query.from_user.id,
                        animation=gif.file_id,
                        caption="🎄 Vota este meme",
                        reply_markup=markup,
                    )
            except Exception as edit_error:
                print(f"Error al editar mensaje: {edit_error}")
        else:
            await update.message.reply_animation(
                animation=gif.file_id, caption="🎄 Vota este meme", reply_markup=markup
            )
    except Exception as e:
        print(f"Error en send_current_gif: {e}")


async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data

    if data.startswith("vote:"):
        try:
            gif_id = int(data.split(":")[1])
            vote_result = DB.vote_gif(
                query.from_user.id, query.from_user.username, gif_id
            )
            if not vote_result:
                await query.answer("❌ No puedes votar este GIF", show_alert=True)
                return
            gifs = context.user_data.get("votable_gifs", [])
            current_index = context.user_data.get("current_index", 0)
            context.user_data["current_index"] = current_index + 1
            if context.user_data["current_index"] < len(gifs):
                await send_current_gif(update, context)
            else:
                if query.message:
                    await query.message.edit_caption(
                        caption="✅ ¡Gracias por votar todos los memes! ⭐",
                        reply_markup=None,
                    )
        except Exception as e:
            print(f"Error vote_callback: {e}")
            await query.answer("❌ Error al registrar el voto", show_alert=True)
    elif data in ["next", "prev"]:
        gifs = context.user_data.get("votable_gifs", [])
        current_index = context.user_data.get("current_index", 0)
        if data == "next":
            new_index = min(current_index + 1, len(gifs) - 1)
        else:
            new_index = max(current_index - 1, 0)
        context.user_data["current_index"] = new_index
        await send_current_gif(update, context)


# ------------------ Ranking ------------------


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        leaderboard = DB.get_leaderboard(top=10)
    except Exception as e:
        await update.message.reply_text(f"❌ Error al cargar el ranking: {str(e)}")
        return
    if not leaderboard:
        await update.message.reply_text("❌ No hay GIFs votados todavía.")
        return
    summary = "*🏆 Ranking de Memes 🏆*\n\n"
    for i, entry in enumerate(leaderboard, start=1):
        username = escape_md2(entry.get("username", "Anónimo"))
        votes = entry.get("votes", 0)
        summary += f"{i}. {username} - ⭐ {votes}\n"
    await update.message.reply_text(summary, parse_mode="MarkdownV2")


# ------------------ Error handler ------------------


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error no capturado: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Ha ocurrido un error. Intenta de nuevo más tarde."
        )


# ------------------ Telegram Application ------------------
app_telegram = ApplicationBuilder().token(TOKEN).build()
dispatcher: Dispatcher = app_telegram.dispatcher

# Handlers
dispatcher.add_error_handler(error_handler)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("villancico", carol))
dispatcher.add_handler(CommandHandler("ranking", show_leaderboard))
dispatcher.add_handler(CommandHandler("votaciones", show_memes_to_vote))

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("mandar_meme", send_meme_start)],
    states={
        WAITING_FOR_GIF: [
            MessageHandler(
                filters.ANIMATION | filters.Document.MimeType("image/gif"), receive_meme
            ),
            MessageHandler(
                filters.ALL,
                lambda u, c: u.message.reply_text("❌ Por favor envía un GIF."),
            ),
        ]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
dispatcher.add_handler(conv_handler)
dispatcher.add_handler(
    CallbackQueryHandler(vote_callback, pattern=r"^(vote:\d+|next|prev|counter)$")
)

logger.info("🤖 Bot listo para Webhook...")

# ------------------ Webhook route ------------------


@flask_app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), app_telegram.bot)
    dispatcher.process_update(update)
    return "OK"


# ------------------ Configurar webhook automáticamente ------------------


def set_webhook():
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not host:
        logger.warning(
            "⚠️ No se encontró RENDER_EXTERNAL_HOSTNAME. Configura webhook manualmente."
        )
        return
    webhook_url = f"https://{host}/{TOKEN}"
    r = requests.get(
        f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}"
    )
    if r.status_code == 200 and r.json().get("ok"):
        logger.info(f"✅ Webhook configurado en {webhook_url}")
    else:
        logger.error(f"❌ Error configurando webhook: {r.text}")


# ------------------ Ejecutar Flask ------------------
if __name__ == "__main__":
    set_webhook()
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
