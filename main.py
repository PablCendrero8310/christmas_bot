import os
import random
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")


async def carol(update: Update, context: ContextTypes.DEFAULT_TYPE):

    ruta = Path("files/")  # Cambia por tu carpeta
    archivos_ogg = [f for f in ruta.iterdir() if f.is_file()
                    and f.suffix == ".ogg"]
    file = random.choice(archivos_ogg)
    with open(file, "rb") as voice:
        await update.message.reply_voice(voice)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = """
🤖 *Comandos disponibles*:
/start - Inicia el bot
/help - Muestra este mensaje
/villancico - Recibe una nota de voz con un villancico
"""
    # Envía el mensaje en formato Markdown
    await update.message.reply_text(mensaje, parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Hola! Bienvenido al bot 🎄")
    # Ejecutar help automáticamente
    await help_command(update, context)


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("villancico", carol))
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.run_polling()
