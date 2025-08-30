import logging
import requests
import os
import asyncio
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.utils.exceptions import NetworkError, TelegramAPIError
import time
from io import BytesIO
import aiohttp
import async_timeout
import json
from PIL import Image
import uuid

# Logging konfiguratsiyasi
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Tokenlar (environment variables dan olish yaxshiroq)
BOT_TOKEN = os.getenv("BOT_TOKEN", "7611353610:AAE63YMwYB0avDT5sv-pBLyhP8Uz7QdPwf0")
HF_TOKEN = os.getenv("HF_TOKEN", "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")

# Bot va dispatcher
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)

# Foydalanuvchilar ma'lumotlari saqlash (real loyiha uchun DB ishlatish kerak)
user_data = {}

# API endpoints
APIS = [
    {
        "name": "HuggingFace SDXL",
        "url": "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
        "headers": {"Authorization": f"Bearer {HF_TOKEN}"},
        "get_image": lambda response: response.content
    },
    {
        "name": "HuggingFace SD v2.1", 
        "url": "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1",
        "headers": {"Authorization": f"Bearer {HF_TOKEN}"},
        "get_image": lambda response: response.content
    },
    {
        "name": "HuggingFace SD v1.5",
        "url": "https://api-inference.huggingface.co/models/runwayml/stable-diffusion-v1-5",
        "headers": {"Authorization": f"Bearer {HF_TOKEN}"},
        "get_image": lambda response: response.content
    }
]

# Inline keyboard
def get_keyboard(has_generated=False):
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    buttons = [
        InlineKeyboardButton("🔄 Qayta urinish", callback_data="retry"),
        InlineKeyboardButton("📝 Namunalar", callback_data="examples"),
        InlineKeyboardButton("👨‍💻 Yordam", callback_data="help"),
        InlineKeyboardButton("⭐ Baholash", callback_data="rate"),
    ]
    
    if has_generated:
        buttons.append(InlineKeyboardButton("📥 Rasmni yuklab olish", callback_data="download"))
    
    keyboard.add(*buttons)
    return keyboard

# Rasmni qayta ishlash funksiyasi
async def process_image(image_data, user_id):
    """Rasmni qayta ishlash va formatini o'zgartirish"""
    try:
        # Rasmni ochib, formatini o'zgartiramiz
        image = Image.open(BytesIO(image_data))
        
        # Rasm hajmini optimallashtirish
        if image.size[0] > 1024 or image.size[1] > 1024:
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        
        # PNG formatiga o'tkazamiz
        output = BytesIO()
        image.save(output, format='PNG', optimize=True)
        output.seek(0)
        
        return output.getvalue()
    except Exception as e:
        logger.error(f"Rasmni qayta ishlashda xatolik: {e}")
        return image_data  # Original rasmni qaytarish

# Rasm yaratish funksiyasi (asynchronous versiyasi)
async def generate_image(prompt: str):
    async with aiohttp.ClientSession() as session:
        for api in APIS:
            try:
                logger.info(f"Trying API: {api['name']}")
                
                async with async_timeout.timeout(90):
                    async with session.post(
                        api["url"], 
                        headers=api["headers"], 
                        json={"inputs": prompt}
                    ) as response:
                        
                        if response.status == 200:
                            logger.info(f"Success with API: {api['name']}")
                            image_data = await response.read()
                            return image_data
                        elif response.status == 503:
                            # Model yuklanmoqda, kutish vaqti
                            data = await response.json()
                            estimated_time = data.get('estimated_time', 30)
                            logger.info(f"Model loading, estimated time: {estimated_time}")
                            # Keyingi API ni sinab ko'rish
                            continue
                        else:
                            logger.warning(f"API {api['name']} failed with status: {response.status}")
                            continue
                            
            except asyncio.TimeoutError:
                logger.error(f"API {api['name']} timeout")
                continue
            except Exception as e:
                logger.error(f"Error with API {api['name']}: {str(e)}")
                continue
    
    return None

# Foydalanuvchi statistikasi
def update_user_stats(user_id, action):
    if user_id not in user_data:
        user_data[user_id] = {
            'generation_count': 0,
            'last_activity': time.time(),
            'first_seen': time.time()
        }
    
    if action == 'generate':
        user_data[user_id]['generation_count'] += 1
    user_data[user_id]['last_activity'] = time.time()

# Start komandasi
@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message):
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    
    update_user_stats(user_id, 'start')
    
    welcome_text = (
        f"👋 Salom, {user_name}!\n\n"
        f"🤖 Men AI yordamida matnga asoslangan rasmlar yaratuvchi botman.\n\n"
        f"🖍️ Rasm yaratish uchun menga istalgan matnli tasvirni yuboring.\n\n"
        f"📖 Misol: <code>sunset over mountains, digital art, 4k quality</code>\n\n"
        f"✨ <b>Yangi imkoniyatlar:</b>\n"
        f"• 📊 Shaxsiy statistikangizni ko'rish (/stats)\n"
        f"• 🌆 Rasm uslubini tanlash (/styles)\n"
        f"• 📥 Yarangan rasmlarni yuklab olish\n\n"
        f"⚠️ Iltimos, so'rovlarni <b>ingliz tilida</b> yuboring."
    )
    
    await message.answer(welcome_text, reply_markup=get_keyboard())

# Statistikalar komandasi
@dp.message_handler(commands=['stats'])
async def stats_handler(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in user_data:
        stats = user_data[user_id]
        stats_text = (
            f"📊 <b>Sizning statistikangiz:</b>\n\n"
            f"🖼️ Yaratalgan rasmlar: <b>{stats['generation_count']}</b>\n"
            f"📅 Birinchi marta: <b>{time.strftime('%Y-%m-%d', time.localtime(stats['first_seen']))}</b>\n"
            f"⏰ So'nggi faollik: <b>{time.strftime('%Y-%m-%d %H:%M', time.localtime(stats['last_activity']))}</b>\n\n"
            f"✨ Davom eting va ko'proq ajoyib rasmlar yarating!"
        )
    else:
        stats_text = "📊 Siz hali hech qanday rasm yaratmagansiz. Bironta so'rov yuboring!"
    
    await message.answer(stats_text, reply_markup=get_keyboard())

# Uslublar ro'yxati
@dp.message_handler(commands=['styles'])
async def styles_handler(message: types.Message):
    styles_text = (
        "🎨 <b>Rasm uslublari va ularga misollar:</b>\n\n"
        "• <b>Realistik</b> - <code>photorealistic, highly detailed, 8k</code>\n"
        "• <b>Raqamli san'at</b> - <code>digital art, concept art</code>\n"
        "• <b>Portret</b> - <code>portrait, professional photography</code>\n"
        "• <b>Anime</b> - <code>anime style, manga art</code>\n"
        "• <b>3D Render</b> - <code>3D render, CGI, octane render</code>\n"
        "• <b>Rasim</b> - <code>oil painting, watercolor, sketch</code>\n"
        "• <b>Futuristik</b> - <code>cyberpunk, futuristic, neon</code>\n"
        "• <b>Fantastika</b> - <code>fantasy art, magical, mystical</code>\n\n"
        "💡 Uslubni so'rovga qo'shing: <code>landscape, digital art, 4k</code>"
    )
    
    await message.answer(styles_text, reply_markup=get_keyboard())

# Yordam komandasi
@dp.message_handler(commands=['help'])
async def help_handler(message: types.Message):
    help_text = (
        "❓ <b>Botdan foydalanish bo'yicha ko'rsatma:</b>\n\n"
        "1. Rasm yaratish uchun menga istalgan matn yuboring\n"
        "2. So'rovlarni <b>ingliz tilida</b> yuboring\n"
        "3. Rasm yaratish 1-2 daqiqa vaqt olishi mumkin\n\n"
        "✨ <b>Yangi funksiyalar:</b>\n"
        "• /stats - Shaxsiy statistikangizni ko'rish\n"
        "• /styles - Rasm uslublari va misollar\n"
        "• 📥 Yarangan rasmlarni yuklab olish\n\n"
        "📝 <b>Yaxshi natija beradigan so'rovlar:</b>\n"
        "• <code>sunset over mountains, digital art, 4k</code>\n"
        "• <code>a beautiful garden with flowers, photorealistic</code>\n"
        "• <code>futuristic cityscape at night, neon lights</code>\n\n"
        "🔄 Agar xato bo'lsa, yangi so'rov yuboring yoki /examples ni bosing"
    )
    
    await message.answer(help_text, reply_markup=get_keyboard())

# Namunalar komandasi
@dp.message_handler(commands=['examples'])
async def examples_handler(message: types.Message):
    examples_text = (
        "🎨 <b>Ishlaydigan so'rov namunalari:</b>\n\n"
        "1. <code>sunset over mountains, dramatic lighting, photorealistic, 8k</code>\n"
        "2. <code>a beautiful garden with colorful flowers, sunny day, oil painting</code>\n"
        "3. <code>futuristic city at night, neon lights, cyberpunk style, digital art</code>\n"
        "4. <code>portrait of a cat, detailed fur, professional photography</code>\n"
        "5. <code>ancient castle in the forest, fantasy art, digital painting</code>\n"
        "6. <code>astronaut riding a horse on mars, surrealism, 4k</code>\n"
        "7. <code>underwater paradise, coral reef, tropical fish, clear water</code>\n\n"
        "💡 <b>Maslahat:</b> So'rovga sifat va uslubni ko'rsating (4k, HD, photorealistic, digital art)"
    )
    
    await message.answer(examples_text, reply_markup=get_keyboard())

# Admin statistikasi
@dp.message_handler(commands=['adminstats'], user_id=[123456789])  # Admin ID sini qo'ying
async def admin_stats_handler(message: types.Message):
    total_users = len(user_data)
    total_generations = sum([user_data[uid]['generation_count'] for uid in user_data])
    
    stats_text = (
        f"👑 <b>Admin statistikasi:</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users}</b>\n"
        f"🖼️ Jami rasmlar: <b>{total_generations}</b>\n"
        f"📊 O'rtacha rasm/foydalanuvchi: <b>{total_generations/total_users if total_users > 0 else 0:.2f}</b>\n"
    )
    
    await message.answer(stats_text)

# Asosiy xabarlarni qayta ishlash
@dp.message_handler()
async def handle_message(message: types.Message):
    # Komandalarni boshqa xabarlardan ajratish
    if message.text.startswith('/'):
        return
    
    user_id = message.from_user.id
    prompt = message.text.strip()
    
    # So'rovni tekshirish
    if len(prompt) < 3:
        await message.answer("❌ Iltimos, kamida 3 ta belgidan iborat tasvirni kiriting.")
        return
    
    if len(prompt) > 1000:
        await message.answer("❌ Tasvir juda uzun. Iltimos, 1000 ta belgidan oshmasligiga e'tibor bering.")
        return
    
    # Foydalanuvchi statistikasini yangilash
    update_user_stats(user_id, 'generate')
    
    # Kutish xabarini yuborish
    wait_msg = await message.answer(
        f"⏳ <b>Rasm yaratilmoqda...</b>\n\n"
        f"📝 So'rovingiz: <i>{prompt[:100]}{'...' if len(prompt) > 100 else ''}</i>\n\n"
        f"⏰ Bu jarayon 1-2 daqiqa vaqt olishi mumkin. Iltimos, kuting..."
    )
    
    # Rasm yaratish
    image_data = await generate_image(prompt)
    
    # Rasmni tekshirish va yuborish
    if image_data:
        try:
            # Rasmni qayta ishlash
            processed_image = await process_image(image_data, user_id)
            
            # Rasmni yuborish
            await bot.send_chat_action(message.chat.id, "upload_photo")
            
            # Fayl nomini yaratish
            filename = f"ai_image_{user_id}_{int(time.time())}.png"
            
            # Rasmni yuborish
            sent_message = await message.answer_photo(
                types.InputFile(BytesIO(processed_image), filename=filename),
                caption=f"🖼 <b>Sizning tasviringiz asosida yaratilgan rasm</b>\n\n"
                       f"📝 So'rov: <i>{prompt}</i>\n"
                       f"👤 Foydalanuvchi: {message.from_user.first_name}\n\n"
                       f"✨ Yangi rasm yaratish uchun yangi tasvir yuboring",
                reply_markup=get_keyboard(has_generated=True)
            )
            
            # Rasm ma'lumotlarini saqlash (yuklab olish uchun)
            if user_id not in user_data:
                user_data[user_id] = {}
            
            user_data[user_id]['last_image'] = {
                'data': processed_image,
                'prompt': prompt,
                'timestamp': time.time()
            }
            
            # Kutish xabarini o'chirish
            await wait_msg.delete()
            
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            await wait_msg.edit_text(
                "❌ Rasmni yuborishda xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring."
            )
    else:
        error_text = (
            "❌ <b>Rasm yaratishda xatolik yuz berdi</b>\n\n"
            "🔧 <b>Quyidagi choralarni ko'ring:</b>\n"
            "1. So'rovingizni <b>ingliz tilida</b> yozing\n"
            "2. So'rovni soddalashtiring\n"
            "3. Sifatni ko'rsating (masalan: HD, 4k, photorealistic)\n"
            "4. Bir necha daqiqa kutib qayta urinib ko'ring\n\n"
            "📝 <b>Yaxshi so'rov namunalari uchun</b> /examples buyrug'ini bosing\n\n"
            "🔄 Yangi so'rov yuboring yoki /help buyrug'i orqali yordam oling"
        )
        
        await wait_msg.edit_text(error_text, reply_markup=get_keyboard())

# Inline tugmalar uchun handler
@dp.callback_query_handler()
async def callback_handler(callback_query: types.CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "help":
        await help_handler(callback_query.message)
    elif data == "examples":
        await examples_handler(callback_query.message)
    elif data == "retry":
        await callback_query.message.answer("🔄 Yangi so'rov yuboring:")
    elif data == "rate":
        await callback_query.message.answer(
            "⭐ Iltimos, botimizni baholang:\n\n"
            "Agar sizga botimiz yoqgan bo'lsa, baho qoldiring yoki takliflaringizni yozib qoldiring.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⭐ Baho berish", url="https://t.me/mortistubea")
            )
        )
    elif data == "download" and user_id in user_data and 'last_image' in user_data[user_id]:
        # Rasmni yuklab olish
        image_data = user_data[user_id]['last_image']['data']
        prompt = user_data[user_id]['last_image']['prompt']
        
        filename = f"ai_image_{prompt[:20].replace(' ', '_')}.png"
        
        await callback_query.message.answer_document(
            types.InputFile(BytesIO(image_data), filename=filename),
            caption=f"📥 <b>Rasm yuklab olindi</b>\n\n"
                   f"📝 So'rov: <i>{prompt}</i>\n"
                   f"💾 Fayl nomi: {filename}"
        )
    
    await callback_query.answer()

# Xatolikni qayta ishlash
@dp.errors_handler()
async def errors_handler(update, exception):
    logger.error(f"Update {update} caused error {exception}")
    return True

# Botni ishga tushirish
if __name__ == '__main__':
    logger.info("Bot starting...")
    executor.start_polling(dp, skip_updates=True)