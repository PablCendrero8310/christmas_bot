import logging
import os
import random
from pathlib import Path
from typing import Optional

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
    MessageHandler,
    filters,
)

from controllers import ChristmasDB

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)
DB = ChristmasDB()
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
WAITING_FOR_GIF = 1


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

    # Verificar si ya ha subido un GIF
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

    # Verificar si ya ha subido un GIF (por si acaso)
    if DB.has_user_submitted_gif(telegram_id):
        await update.message.reply_text("❌ Ya has enviado un GIF anteriormente.")
        return ConversationHandler.END

    # Obtener file_id según el tipo de mensaje
    file_id: Optional[str] = None
    if update.message.animation:
        file_id = update.message.animation.file_id
    elif update.message.document and update.message.document.mime_type == "image/gif":
        file_id = update.message.document.file_id

    if not file_id:
        await update.message.reply_text(
            "❌ Por favor envía un GIF válido (como animación o documento GIF)."
        )
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
    user = update.effective_user
    telegram_id = user.id
    username = user.username or ""

    gifs = DB.get_votable_gifs(telegram_id, username)

    if not gifs:
        await update.message.reply_text("❌ No hay memes para votar.")
        return

    # Limpiar datos anteriores
    context.user_data.clear()
    context.user_data["votable_gifs"] = gifs
    context.user_data["current_index"] = 0

    await send_current_gif(update, context)


async def send_current_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        index = context.user_data.get("current_index", 0)
        gifs = context.user_data.get("votable_gifs", [])

        if not gifs or index >= len(gifs) or index < 0:
            # Limpiar datos y enviar mensaje final
            context.user_data.clear()

            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text(
                    "✅ Has votado todos los memes disponibles."
                )
            elif update.message:
                await update.message.reply_text(
                    "✅ Has votado todos los memes disponibles."
                )
            elif update.callback_query:
                await update.callback_query.answer(
                    "✅ Has votado todos los memes disponibles.", show_alert=True
                )
            return

        gif = gifs[index]

        # Crear botones
        buttons = []

        # Botón para votar
        buttons.append(
            [InlineKeyboardButton("⭐ Votar", callback_data=f"vote:{gif.id}")]
        )

        # Botones de navegación
        nav_buttons = []
        if index > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data="prev"))

        # Contador de posición
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

        # Determinar si es un mensaje nuevo o edición
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
                    # Si no hay mensaje, enviar uno nuevo
                    if update.callback_query.from_user:
                        await context.bot.send_animation(
                            chat_id=update.callback_query.from_user.id,
                            animation=gif.file_id,
                            caption="🎄 Vota este meme",
                            reply_markup=markup,
                        )
            except Exception as edit_error:
                print(f"Error al editar mensaje: {str(edit_error)}")
                # Fallback: enviar nuevo mensaje
                if update.callback_query.message:
                    await update.callback_query.message.reply_animation(
                        animation=gif.file_id,
                        caption="🎄 Vota este meme",
                        reply_markup=markup,
                    )
                elif update.callback_query.from_user:
                    await context.bot.send_animation(
                        chat_id=update.callback_query.from_user.id,
                        animation=gif.file_id,
                        caption="🎄 Vota este meme",
                        reply_markup=markup,
                    )

            # Siempre responder al callback_query
            await update.callback_query.answer()

        else:
            # Mensaje nuevo desde comando
            await update.message.reply_animation(
                animation=gif.file_id, caption="🎄 Vota este meme", reply_markup=markup
            )

    except Exception as e:
        print(f"Error en send_current_gif: {str(e)}")

        # Manejo de errores específico
        error_message = "❌ Error al mostrar el GIF"

        if update.callback_query:
            try:
                if update.callback_query.message:
                    await update.callback_query.message.reply_text(error_message)
                else:
                    await update.callback_query.answer(error_message, show_alert=True)
            except:
                pass
        elif update.message:
            await update.message.reply_text(error_message)


async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # Verificar que tenemos query
    if not query:
        return

    await query.answer()
    data = query.data

    if data.startswith("vote:"):
        try:
            gif_id = int(data.split(":")[1])

            # Votar en la base de datos
            vote_result = DB.vote_gif(
                query.from_user.id, query.from_user.username, gif_id
            )

            if not vote_result:
                await query.answer("❌ No puedes votar este GIF", show_alert=True)
                return

            # Obtener datos actuales
            gifs = context.user_data.get("votable_gifs", [])
            current_index = context.user_data.get("current_index", 0)

            # Mover al siguiente
            context.user_data["current_index"] = current_index + 1

            # Actualizar mensaje
            if context.user_data["current_index"] < len(gifs):
                # Mostrar siguiente GIF
                await send_current_gif(update, context)
            else:
                # Mostrar mensaje final
                try:
                    if query.message:
                        await query.message.edit_caption(
                            caption="✅ ¡Gracias por votar todos los memes! ⭐",
                            reply_markup=None,
                        )
                    else:
                        await query.answer(
                            "✅ ¡Gracias por votar todos los memes! ⭐", show_alert=True
                        )
                except Exception as edit_error:
                    # Si no se puede editar, enviar mensaje nuevo
                    if query.message:
                        await query.message.reply_text(
                            "✅ ¡Gracias por votar todos los memes! ⭐"
                        )
                    else:
                        await query.answer(
                            "✅ ¡Gracias por votar todos los memes! ⭐", show_alert=True
                        )

                # Limpiar datos
                context.user_data.pop("votable_gifs", None)
                context.user_data.pop("current_index", None)

        except Exception as e:
            print(f"Error en vote_callback: {str(e)}")
            await query.answer("❌ Error al registrar el voto", show_alert=True)

    elif data in ["next", "prev"]:
        try:
            gifs = context.user_data.get("votable_gifs", [])
            current_index = context.user_data.get("current_index", 0)

            if data == "next":
                new_index = min(current_index + 1, len(gifs) - 1)
            else:  # prev
                new_index = max(current_index - 1, 0)

            context.user_data["current_index"] = new_index
            await send_current_gif(update, context)

        except Exception as e:
            print(f"Error en navegación: {str(e)}")
            await query.answer("❌ Error al navegar", show_alert=True)

    elif data == "counter":
        # Solo responder al callback
        gifs = context.user_data.get("votable_gifs", [])
        current_index = context.user_data.get("current_index", 0)
        await query.answer(f"Posición {current_index + 1}/{len(gifs)}")


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

    # Enviar mensaje inicial del ranking
    header = "*🏆 Ranking de Memes 🏆*\n\n"
    ranking_text = []

    for i, entry in enumerate(leaderboard, start=1):
        username = escape_md2(entry.get("username", "Anónimo"))
        votes = entry.get("votes", 0)
        gif_id = entry.get("gif_id", 0)
        file_id = entry.get("file_id", "")

        # Añadir emojis según la posición
        if i == 1:
            medal = "🥇"
        elif i == 2:
            medal = "🥈"
        elif i == 3:
            medal = "🥉"
        else:
            medal = f"{i}\\."

        line = f"{medal} ⭐ *{votes}* \\- {username}"
        ranking_text.append(line)

        # Enviar el GIF con su información
        caption = f"*Posición {i}*\n{medal} ⭐ *{
            votes} votos*\n👤 *Usuario:* {username}"

        try:
            # Enviar el GIF
            await update.message.reply_animation(
                animation=file_id, caption=caption, parse_mode="MarkdownV2"
            )
        except Exception as gif_error:
            print(f"Error al enviar GIF {gif_id}: {str(gif_error)}")
            # Si falla, enviar solo la información
            await update.message.reply_text(
                f"❌ No se pudo cargar el GIF de la posición {i}\n"
                f"Usuario: {username} - ⭐ {votes} votos"
            )

    # Enviar resumen final
    summary = header + "\n".join(ranking_text)
    await update.message.reply_text(summary, parse_mode="MarkdownV2")


# ------------------ Configuración del bot ------------------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja errores no capturados"""
    logger.error(f"Error no capturado: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Ha ocurrido un error. Por favor, intenta de nuevo más tarde."
        )


def main():
    """Función principal para iniciar el bot"""
    if not TOKEN:
        logger.error("❌ TELEGRAM_TOKEN no está configurado.")
        return

    # Crear la aplicación
    app = ApplicationBuilder().token(TOKEN).build()

    # Añadir manejador de errores
    app.add_error_handler(error_handler)

    # Comandos básicos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("villancico", carol))
    app.add_handler(CommandHandler("ranking", show_leaderboard))
    app.add_handler(CommandHandler("votaciones", show_memes_to_vote))

    # Conversación para enviar memes
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("mandar_meme", send_meme_start)],
        states={
            WAITING_FOR_GIF: [
                MessageHandler(
                    filters.ANIMATION | filters.Document.MimeType("image/gif"),
                    receive_meme,
                ),
                MessageHandler(
                    filters.ALL,
                    lambda u, c: u.message.reply_text("❌ Por favor envía un GIF."),
                ),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    # Manejador de callbacks para votación
    app.add_handler(
        CallbackQueryHandler(vote_callback, pattern=r"^(vote:\d+|next|prev|counter)$")
    )

    logger.info("🤖 Bot iniciado...")

    # Iniciar el bot
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 80)),
        secret_token="AecreTTok1enIHAveChangedByNow",
        webhook_url="https://mi-bot-telegram-2nba.onrender.com",
    )


if __name__ == "__main__":
    main()
