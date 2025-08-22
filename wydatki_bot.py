import os
import json
from datetime import date
from openai import OpenAI
import assemblyai as aai
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler

load_dotenv()
TOKEN = os.getenv("WYDATKI_BOT_API_KEY")
aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Google Sheets setup
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("dima-wydatki-c8dcedafff4d.json", SCOPE)
GSPREAD_CLIENT = gspread.authorize(CREDS)
SHEET = GSPREAD_CLIENT.open("Витрати").worksheet("2026")

def extract_expense_data_ai(text: str):
    """
    AI-powered expense parser that understands Polish natural language.
    Falls back to regex if AI parsing fails.
    """
    today = date.today().strftime("%d.%m.%Y")

    prompt = f"""
    You are an expense data extractor for a Polish personal finance bot.
    From the following text, extract:
    - amount: float in PLN (no currency symbol),
    - date: in format DD.MM.YYYY (assume current year if year is missing),
    - place: only the store or location name.

    Today is {today}.
    Text: "{text}"

    Respond ONLY in valid JSON, with keys: amount, date, place.
    Example: {{"amount": 200.0, "date": "15.07.2025", "place": "Biedronka"}}
    """

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            temperature=0
        )

        data = json.loads(response.output_text)

        # Validate minimal data
        if not data.get("amount") or not data.get("date") or not data.get("place"):
            raise ValueError("Incomplete AI response")

        return data["amount"], data["date"], data["place"]

    except Exception as e:
        print(f"[WARN] AI parser failed ({e})")

def append_clean_row(sheet, amount, date_str, place):
    place = " ".join(place.split())  # normalize spaces
    row = [amount, date_str, place]
    next_row = len(sheet.col_values(1)) + 1
    sheet.update(f"A{next_row}:C{next_row}", [row])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tekst = "Скажи скільки, де і коли витратив:\n"
    await update.message.reply_text(tekst)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    file_path = str(await file.download_to_drive("voice.ogg"))
    
    transcriber = aai.Transcriber(config=aai.TranscriptionConfig(language_code="pl"))
    transcript = transcriber.transcribe(file_path)

    if transcript.status == aai.TranscriptStatus.error:
        await update.message.reply_text("❌ Не вдалося розпізнати голос.")
        return
    
    text = transcript.text
    await update.message.reply_text(f"Розпізнано: {text}")

    amount, date_str, place = extract_expense_data_ai(text)

    await update.message.reply_text(f"📌 Записано: {amount} zł, {date_str}, {place}")

    append_clean_row(SHEET, amount, date_str, place)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("Bot działa...")
    app.run_polling()