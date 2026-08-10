import telebot
from telebot import types

TOKEN = '8747901117:AAF1kBYuI41P9VOIJOoZvX6kCGhKok-VvgA'

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup()
    web_app_btn = types.InlineKeyboardButton(
        text='🗺 Открыть карту подработок',
        web_app=types.WebAppInfo(url='https://strongman-palpable-untapped.ngrok-free.dev') 
    )
    markup.add(web_app_btn)
    bot.send_message(message.chat.id, 'Привет! Нажми кнопку, чтобы открыть карту.', reply_markup=markup)

bot.polling(none_stop=True)