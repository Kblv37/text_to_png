import os
import hashlib
import math
from aiogram import Bot, Dispatcher, types
from aiogram.types import InputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from PIL import Image, ImageDraw

TOKEN = '7903858826:AAEt6-dcWHjjZ8OvvZhi8iPYaN5mfTyDeqo'

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# Состояния
class EncodeState(StatesGroup):
    waiting_for_text = State()
    waiting_for_cell_size = State()

class DecodeState(StatesGroup):
    waiting_for_image = State()
    waiting_for_cell_size = State()

### ШИФРОВКА ###
def char_to_color(ch):
    h = hashlib.md5(ch.encode('utf-8')).hexdigest()
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def int_to_rgb(n):
    return ((n >> 16) & 255, (n >> 8) & 255, n & 255)

def text_to_image(text, cell_size, filename_base):
    text = text.replace('\n', '%')
    total_chars = len(text)
    side = math.ceil(math.sqrt(total_chars + 4))
    canvas_size = side * cell_size
    output_file = f"{filename_base}.png"

    img = Image.new('RGB', (canvas_size, canvas_size), color='white')
    draw = ImageDraw.Draw(img)

    text_len = len(text)
    for i in range(4):
        byte_val = (text_len >> (8 * (3 - i))) & 255
        color = int_to_rgb(byte_val)
        x = i % side
        y = i // side
        draw.rectangle([(x * cell_size, y * cell_size), ((x+1) * cell_size, (y+1) * cell_size)], fill=color)

    for i, ch in enumerate(text):
        idx = i + 4
        x = idx % side
        y = idx // side
        color = char_to_color(ch)
        draw.rectangle([(x * cell_size, y * cell_size), ((x+1) * cell_size, (y+1) * cell_size)], fill=color)

    img.save(output_file)
    return output_file

### ДЕШИФРОВКА ###
def build_color_lookup_table():
    charset = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        " .,!?;:-_+=()[]{}<>@#$%^&*/\\|\"'\n\t`~%"
    )
    table = {}
    for ch in charset:
        color = char_to_color(ch)
        table[color] = ch
    return table

def rgb_to_int(rgb):
    r, g, b = rgb
    return (r << 16) + (g << 8) + b

def image_to_text(filename, cell_size):
    img = Image.open(filename)
    pixels = img.load()
    width, height = img.size

    cols = width // cell_size
    length = 0
    for i in range(4):
        x = i % cols
        y = i // cols
        rgb = pixels[x * cell_size + cell_size // 2, y * cell_size + cell_size // 2]
        length = (length << 8) + rgb_to_int(rgb) & 255

    color_table = build_color_lookup_table()
    result = []

    for i in range(length):
        idx = i + 4
        x = idx % cols
        y = idx // cols
        color = pixels[x * cell_size + cell_size // 2, y * cell_size + cell_size // 2]
        char = color_table.get(color, '?')
        result.append(char)

    raw_text = ''.join(result)
    return raw_text.replace('%', '\n')

### БОТ ###
@dp.message_handler(commands=['start'])
async def start(msg: types.Message):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('🔐 Шифровать'), KeyboardButton('🔓 Расшифровать'))
    await msg.answer("Привет! Что вы хотите сделать?", reply_markup=kb)

@dp.message_handler(lambda msg: msg.text == '🔐 Шифровать')
async def encode_start(msg: types.Message):
    await msg.answer("Отправьте текст на латинице.")
    await EncodeState.waiting_for_text.set()

@dp.message_handler(lambda msg: msg.text == '🔓 Расшифровать')
async def decode_start(msg: types.Message):
    await msg.answer("Отправьте PNG-файл в виде документа.", parse_mode='Markdown')
    await DecodeState.waiting_for_image.set()

@dp.message_handler(state=EncodeState.waiting_for_text)
async def encode_get_text(msg: types.Message, state: FSMContext):
    await state.update_data(text=msg.text)
    await msg.answer("Введите размер одного символа в пикселях 1-1000")
    await EncodeState.waiting_for_cell_size.set()

@dp.message_handler(state=EncodeState.waiting_for_cell_size)
async def encode_get_size(msg: types.Message, state: FSMContext):
    try:
        size = int(msg.text.strip())
        if not (1 <= size <= 1000):
            raise ValueError
    except:
        await msg.answer("Ошибка: введите число от 1 до 1000")
        return

    data = await state.get_data()
    filename = f"output_{msg.from_user.id}"
    path = text_to_image(data['text'], size, filename)
    await msg.answer_document(InputFile(path))
    os.remove(path)
    await state.finish()

@dp.message_handler(state=DecodeState.waiting_for_image, content_types=[types.ContentType.DOCUMENT, types.ContentType.PHOTO])
async def decode_get_image(msg: types.Message, state: FSMContext):
    if msg.content_type == types.ContentType.PHOTO:
        await msg.answer("❗ Пожалуйста, отправьте изображение как *документ*, иначе оно может быть сжато.", parse_mode='Markdown')
        return

    if not msg.document.file_name.endswith('.png'):
        await msg.answer("❗ Поддерживаются только файлы PNG.")
        return

    await state.update_data(file_id=msg.document.file_id)
    await msg.answer("Введите размер символа в пикселях 1-1000")
    await DecodeState.waiting_for_cell_size.set()

@dp.message_handler(state=DecodeState.waiting_for_cell_size)
async def decode_get_size(msg: types.Message, state: FSMContext):
    try:
        cell_size = int(msg.text.strip())
        if not (1 <= cell_size <= 1000):
            raise ValueError
    except:
        await msg.answer("Ошибка: введите число от 1 до 1000")
        return

    data = await state.get_data()
    file = await bot.get_file(data['file_id'])
    path = f"temp_{msg.from_user.id}.png"
    await bot.download_file(file.file_path, path)

    result = image_to_text(path, cell_size)
    os.remove(path)
    await msg.answer("🔓 Расшифрованный текст:\n\n" + result)
    await state.finish()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
