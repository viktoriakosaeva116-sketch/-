import asyncio
import os
import tempfile
import json
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from openai import OpenAI
from file_utils import extract_docx, extract_pdf, extract_txt

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

if not BOT_TOKEN or not OPENROUTER_KEY:
    print("Добавьте токены в .env файл!")
    exit(1)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

openrouter = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

AVAILABLE_MODELS = {
    "devstral": "mistralai/devstral-small-2505:free",
    "mistral": "mistralai/mistral-7b-instruct:free",
    "gemma": "google/gemma-7b-it:free",
    "nous": "nousresearch/nous-hermes-2-mistral:free"
}

MODEL_STATE_FILE = Path("models.json")

def load_selected_model() -> str:
    if MODEL_STATE_FILE.exists():
        try:
            data = json.loads(MODEL_STATE_FILE.read_text(encoding="utf-8"))
            model = data.get("model")
            if model in AVAILABLE_MODELS.values():
                return model
        except Exception:
            pass
    return AVAILABLE_MODELS["devstral"]

def save_selected_model(model: str):
    try:
        MODEL_STATE_FILE.write_text(json.dumps({"model": model}), encoding="utf-8")
    except Exception:
        pass

AI_MODEL = load_selected_model()

SUPPORTED_FORMATS = ['.pdf', '.docx', '.txt']
MAX_FILE_SIZE = 20 * 1024 * 1024

def build_model_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="DevStral", callback_data="set_model_devstral"),
            InlineKeyboardButton(text="Mistral", callback_data="set_model_mistral")
        ],
        [
            InlineKeyboardButton(text="Gemma", callback_data="set_model_gemma"),
            InlineKeyboardButton(text="Nous Hermes", callback_data="set_model_nous")
        ],
        [
            InlineKeyboardButton(text="❓ Помощь", callback_data="help")
        ]
    ])
    return kb

def get_main_keyboard():
    return build_model_keyboard()

@dp.message(CommandStart())
async def start_command(message: Message):
    await message.answer(
        f"🎓 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        "Я проверяю лабораторные работы с помощью ИИ.\n\n"
        f"🤖 <b>Текущая модель:</b>\n<code>{AI_MODEL}</code>\n\n"
        "📄 Отправь файл (PDF, DOCX или TXT) — я дам анализ.",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "help")
async def help_callback(callback):
    await callback.message.answer(
        "📖 Отправь файл: PDF, DOCX или TXT (макс. 20 МБ).\n"
        "Выбери модель кнопками. Выбранная модель сохраняется между перезапусками.\n"
        "Не загружай .env в публичный репозиторий.",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data.startswith("set_model_"))
async def set_model_callback(callback):
    global AI_MODEL
    key = callback.data.replace("set_model_", "")
    mapping = {
        "devstral": AVAILABLE_MODELS["devstral"],
        "mistral": AVAILABLE_MODELS["mistral"],
        "gemma": AVAILABLE_MODELS["gemma"],
        "nous": AVAILABLE_MODELS["nous"]
    }
    sel = mapping.get(key)
    if sel:
        AI_MODEL = sel
        save_selected_model(AI_MODEL)
        await callback.message.answer(f"✅ Модель изменена на:\n<code>{AI_MODEL}</code>", reply_markup=get_main_keyboard())
    else:
        await callback.message.answer("❌ Неизвестная модель", reply_markup=get_main_keyboard())

@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: Message):
    await message.answer(
        "📄 Отправь файл для проверки (PDF/DOCX/TXT).\n\n"
        f"🤖 <b>Текущая модель:</b> <code>{AI_MODEL}</code>",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.document)
async def handle_document(message: Message):
    document = message.document
    file_name = document.file_name
    file_size = document.file_size

    if file_size > MAX_FILE_SIZE:
        await message.answer("❌ Файл слишком большой (макс. 20 МБ).", reply_markup=get_main_keyboard())
        return

    file_ext = Path(file_name).suffix.lower()
    if file_ext not in SUPPORTED_FORMATS:
        await message.answer("❌ Неподдерживаемый формат файла.", reply_markup=get_main_keyboard())
        return

    status_msg = await message.answer(f"⏳ Проверяю работу...\n🤖 Модель: <code>{AI_MODEL}</code>")

    temp_path = None
    try:
        file = await bot.get_file(document.file_id)
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp_file:
            await bot.download_file(file.file_path, tmp_file.name)
            temp_path = tmp_file.name

        if file_ext == '.txt':
            content = await extract_txt(temp_path)
        elif file_ext == '.docx':
            content = await extract_docx(temp_path)
        elif file_ext == '.pdf':
            content = await extract_pdf(temp_path)
        else:
            raise Exception("Неподдерживаемый формат")

        if not content.strip():
            raise Exception("Файл пуст или не содержит читаемого текста")

        await status_msg.edit_text(f"🔄 Извлечено {len(content):,} символов. Отправляю на анализ...\n🤖 Модель: <code>{AI_MODEL}</code>")

        result = await check_with_ai(content)

        if temp_path:
            try:
                os.unlink(temp_path)
            except:
                pass

        await status_msg.edit_text(f"✅ Проверка завершена!\n🤖 Модель: <code>{AI_MODEL}</code>\n📄 Файл: <code>{file_name}</code>\n📝 Символов: {len(content):,}")
        if len(result) > 4000:
            parts = [result[i:i+4000] for i in range(0, len(result), 4000)]
            for i, part in enumerate(parts):
                if i == 0:
                    await message.answer(f"📋 <b>Результат проверки:</b>\n\n{part}")
                else:
                    await message.answer(f"📋 <b>Продолжение ({i+1}):</b>\n\n{part}")
        else:
            await message.answer(f"📋 <b>Результат проверки:</b>\n\n{result}")

    except Exception as e:
        if temp_path:
            try:
                os.unlink(temp_path)
            except:
                pass
        await status_msg.edit_text(f"❌ Ошибка при обработке файла:\n<code>{str(e)}</code>", reply_markup=get_main_keyboard())

async def check_with_ai(content: str) -> str:
    prompt = f"""Ты — преподаватель по информатике. Оцени лабораторную работу студента кратко и по сути.

Дай:
1) Краткое резюме (1-2 предложения).
2) Оценку по четырём критериям (каждый по 10 баллов): корректность, полнота, оформление, документация.
3) 2-3 кратких рекомендации.
4) Итоговая оценка в формате: Итоговая оценка: X/40

Текст работы:
{content}
"""
    try:
        response = openrouter.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1100,
            temperature=0.6,
            top_p=0.9,
            frequency_penalty=0.4,
            presence_penalty=0.3
        )
        body = response.choices[0].message.content
        header = f"🤖 Модель: {AI_MODEL}\n\n"
        return header + body
    except Exception as e:
        return f"❌ Ошибка при обращении к ИИ: {e}"

async def main():
    print("🤖 Запускаю улучшенный бот для проверки лабораторных работ...")
    print(f"🤖 Текущая модель: {AI_MODEL}")
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем.")
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == '__main__':
    asyncio.run(main())
