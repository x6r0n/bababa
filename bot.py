import asyncio
import json
import os
import re
import random
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from openai import AsyncOpenAI
from duckduckgo_search import DDGS  

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

user_threads = {}

# --- БІЗНЕС ЛОГІКА (Моки API авіакомпанії) ---

def search_flights(departure_iata: str, arrival_iata: str, date: str) -> str:
    """Генерує реальне посилання на пошук Ryanair на основі IATA кодів"""
    print(f"\n[API] ✈️ Генерація посилання Ryanair: {departure_iata} -> {arrival_iata} на {date}")
    
    # Валідація: міста не можуть збігатися
    if departure_iata.upper() == arrival_iata.upper():
        return json.dumps({
            "status": "error", 
            "message": "Пункт відправлення та прибуття не можуть збігатися. Запитай куди саме клієнт хоче полетіти."
        })

    # Валідація: дата не може бути в минулому
    try:
        flight_date = datetime.strptime(date, "%Y-%m-%d").date()
        today = datetime.now().date()
        if flight_date < today:
            return json.dumps({
                "status": "error", 
                "message": "Неможливо забронювати квиток на дату в минулому. Запропонуй обрати актуальну дату."
            })
    except ValueError:
        pass
    
    # посилання на сторінку вибору квитків Ryanair
    ryanair_link = f"https://www.ryanair.com/ua/uk/trip/flights/select?adults=1&dateOut={date}&originIata={departure_iata}&destinationIata={arrival_iata}&isConnectedFlight=false&isReturn=false"
    
    return json.dumps({
        "status": "success",
        "message": "Рейси знайдено! Перейдіть за посиланням нижче, щоб побачити актуальні ціни та забронювати квиток на офіційному сайті.",
        "flights": [
            {
                "route": f"З {departure_iata} до {arrival_iata}",
                "date": date,
                "booking_link": ryanair_link
            }
        ]
    })

def get_flight_status(flight_number: str, date: str) -> str:
    """Мок: Завжди повертає статус рейсу"""
    print(f"\n[API] ℹ️ Статус рейсу: {flight_number} на {date}")
    
    statuses = ["Вчасно", "Затримується на 30 хв", "Посадка завершується"]
    gates = ["A12", "B4", "C1", "TBD"]
    
    return json.dumps({
        "flight_number": flight_number,
        "date": date,
        "status": random.choice(statuses),
        "terminal": "D",
        "gate": random.choice(gates)
    })

def get_booking_info(pnr_code: str, last_name: str) -> str:
    """Мок: Перевірка броні за PNR-кодом"""
    print(f"\n[API] 🎫 Перевірка броні: {pnr_code} / {last_name}")
    
    if len(pnr_code) != 6:
        return json.dumps({"error": "PNR код має містити 6 символів."})
        
    return json.dumps({
        "status": "Підтверджено",
        "pnr": pnr_code.upper(),
        "passenger": last_name.upper(),
        "baggage_included": "1x 23kg"
    })    
    
def web_search(query: str) -> str:
    """Шукає інформацію в Інтернеті в реальному часі (погода, новини)"""
    print(f"\n[Інтернет] ⏳ Бот намагається загуглити: '{query}'")
    try:
        # Використовуємо with DDGS() як рекомендується в нових версіях бібліотеки
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        
        if not results:
            print("[Інтернет] ❌ Пошуковик не повернув жодного результату.")
            return json.dumps({"error": "В інтернеті нічого не знайдено за цим запитом."})
            
        print(f"[Інтернет] ✅ Успішно знайдено {len(results)} результатів.")
        return json.dumps({"status": "success", "data": results})
    except Exception as e:
        print(f"[Інтернет Помилка] ❌ {str(e)}") 
        # Повертаємо помилку моделі, щоб вона чесно сказала про збій користувачу
        return json.dumps({"error": f"Скажи користувачу, що виникла технічна помилка доступу до Інтернету: {str(e)}"})


# --- ЛОГІКА ВЗАЄМОДІЇ З OPENAI ---

async def handle_tool_calls(run, thread_id: str):
    tool_outputs = []
    
    for tool_call in run.required_action.submit_tool_outputs.tool_calls:
        function_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        
        output = ""
        try:
            if function_name == "search_flights":
                output = search_flights(
                    arguments.get("departure_iata", ""), 
                    arguments.get("arrival_iata", ""), 
                    arguments.get("date", "")
                )
            elif function_name == "get_flight_status":
                output = get_flight_status(
                    arguments.get("flight_number", ""), 
                    arguments.get("date", "")
                )
            elif function_name == "get_booking_info":
                output = get_booking_info(
                    arguments.get("pnr_code", ""), 
                    arguments.get("last_name", "")
                )
            elif function_name == "web_search":
                output = web_search(arguments.get("query", ""))
            else:
                output = json.dumps({"error": f"Функція {function_name} не знайдена"})
        except Exception as e:
            output = json.dumps({"error": f"Помилка виконання: {str(e)}"})

        tool_outputs.append({
            "tool_call_id": tool_call.id,
            "output": output
        })
        
    run = await client.beta.threads.runs.submit_tool_outputs_and_poll(
        thread_id=thread_id,
        run_id=run.id,
        tool_outputs=tool_outputs
    )
    return run

# --- ОБРОБНИКИ TELEGRAM ---

@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    welcome_text = (
        "✈️ <b>Вітаю у SkyFly!</b>\n\n"
        "Я можу допомогти вам з такими питаннями:\n"
        "🔹 Знайти та забронювати квитки\n"
        "🔹 Перевірити статус вашого рейсу (наприклад: <i>статус SF123 на завтра</i>)\n"
        "🔹 Перевірити бронювання (наприклад: <i>моя бронь X8M9Q1, прізвище Шевченко</i>)\n"
        "🔹 Відповісти на питання щодо багажу та правил."
    )
    await message.answer(welcome_text)

@dp.message()
async def process_user_message(message: types.Message) -> None:
    user_id = message.from_user.id
    
    if user_id not in user_threads:
        thread = await client.beta.threads.create()
        user_threads[user_id] = thread.id
    
    thread_id = user_threads[user_id]
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Додаємо поточну дату як системний контекст
    current_date = datetime.now().strftime("%Y-%m-%d")
    enriched_prompt = f"(Системна примітка: сьогоднішня дата {current_date})\nКористувач: {message.text}"
    
    await client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=enriched_prompt
    )
    
    run = await client.beta.threads.runs.create_and_poll(
        thread_id=thread_id,
        assistant_id=ASSISTANT_ID
    )
    
    if run.status == 'requires_action':
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        run = await handle_tool_calls(run, thread_id)
        
    if run.status == 'completed':
        messages = await client.beta.threads.messages.list(thread_id=thread_id)
        bot_reply = messages.data[0].content[0].text.value
        
        # Очищення та форматування тексту
        bot_reply = re.sub(r'【.*?】', '', bot_reply)
        bot_reply = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', bot_reply) 
        bot_reply = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', bot_reply) 
        bot_reply = re.sub(r'### (.*?)\n', r'<b>\1</b>\n', bot_reply)
        
        try:
            await message.answer(bot_reply)
        except Exception:
            await message.answer(bot_reply, parse_mode=None)
    else:
        await message.answer("Вибачте, сталася помилка під час обробки вашого запиту.")

# --- ЗАПУСК БОТА ---

async def main():
    print("Бот підтримки успішно запущений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())