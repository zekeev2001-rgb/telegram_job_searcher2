import sqlite3
import os
from flask import Flask, request, jsonify
import telebot
from telebot import types

# ---------- НАСТРОЙКИ ----------
TOKEN = os.environ.get('TOKEN', 'ТВОЙ_ТОКЕН_СЮДА')  # токен бота (лучше через переменную окружения)
WEBHOOK_PATH = '/webhook'  # путь, по которому Telegram будет слать обновления

# ---------- FLASK ПРИЛОЖЕНИЕ ----------
app = Flask(__name__)

# ---------- БАЗА ДАННЫХ ----------
def init_db():
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            price REAL,
            lat REAL,
            lng REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ---------- TELEGRAM БОТ ----------
bot = telebot.TeleBot(TOKEN)

# Команда /start – отправляет кнопку с Web App
@bot.message_handler(commands=['start'])
def start(message):
    # Здесь нужно указать ПУБЛИЧНЫЙ URL вашего Render-приложения
    # Пока поставим заглушку, заменим после деплоя
    web_app_url = os.environ.get('WEB_APP_URL', 'https://your-app.onrender.com')
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton(
        text='Открыть карту подработок',
        web_app=types.WebAppInfo(url=web_app_url)
    )
    markup.add(btn)
    bot.send_message(message.chat.id, 'Привет! Нажми кнопку, чтобы открыть карту.', reply_markup=markup)

# Маршрут для вебхука Telegram
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Bad request', 403

# ---------- МАРШРУТЫ ДЛЯ КАРТЫ (как и раньше) ----------
@app.route('/get_jobs')
def get_jobs():
    max_price = request.args.get('max_price', type=float)
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    if max_price is not None:
        c.execute('SELECT id, title, description, price, lat, lng FROM jobs WHERE price <= ?', (max_price,))
    else:
        c.execute('SELECT id, title, description, price, lat, lng FROM jobs')
    rows = c.fetchall()
    conn.close()
    jobs = [{'id': r[0], 'title': r[1], 'description': r[2], 'price': r[3], 'lat': r[4], 'lng': r[5]} for r in rows]
    return jsonify(jobs)

@app.route('/add_job', methods=['POST'])
def add_job():
    data = request.get_json()
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('INSERT INTO jobs (title, description, price, lat, lng) VALUES (?,?,?,?,?)',
              (data['title'], data.get('description', ''), data['price'], data['lat'], data['lng']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'}), 201

@app.route('/')
def map_page():
    # (тот же HTML, что и в предыдущей версии, без изменений)
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Карта подработок</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            #map { height: 100vh; width: 100%; }
            .panel {
                position: absolute; top: 10px; left: 50px; z-index: 1000;
                background: white; padding: 8px; border-radius: 5px;
                box-shadow: 0 0 5px rgba(0,0,0,0.3);
                display: flex; gap: 5px;
            }
        </style>
    </head>
    <body>
        <div class="panel">
            <input type="number" id="maxPrice" placeholder="Макс. цена" style="width: 90px;">
            <button id="filterBtn">Показать</button>
        </div>
        <button id="addBtn" style="position:absolute; top:10px; right:10px; z-index:1000; padding:10px; background:green; color:white; border:none; border-radius:5px;">+</button>
        <div id="map"></div>
        <div id="formContainer" style="display:none; position:absolute; top:50px; right:10px; background:white; padding:15px; border-radius:8px; box-shadow:0 0 10px rgba(0,0,0,0.3); z-index:1000;">
            <input type="text" id="title" placeholder="Название" style="width:100%; margin-bottom:5px;"><br>
            <input type="text" id="description" placeholder="Описание" style="width:100%; margin-bottom:5px;"><br>
            <input type="number" id="price" placeholder="Оплата, руб" style="width:100%; margin-bottom:5px;"><br>
            <button id="saveBtn">Сохранить</button>
            <button id="cancelBtn">Отмена</button>
        </div>
        <script>
            var map = L.map('map').setView([55.7558, 37.6173], 12);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
            var selectedLatLng = null, tempMarker = null;
            map.on('click', function(e) {
                if (tempMarker) map.removeLayer(tempMarker);
                tempMarker = L.marker(e.latlng).addTo(map).bindPopup('Выбрано здесь').openPopup();
                selectedLatLng = e.latlng;
            });
            function loadJobs(maxPrice) {
                map.eachLayer(function(layer) {
                    if (layer instanceof L.Marker && layer !== tempMarker) map.removeLayer(layer);
                });
                var url = '/get_jobs';
                if (maxPrice) url += '?max_price=' + maxPrice;
                fetch(url).then(r=>r.json()).then(jobs => {
                    jobs.forEach(job => {
                        L.marker([job.lat, job.lng]).addTo(map)
                            .bindPopup('<b>' + job.title + '</b><br>' + job.description + '<br>Цена: ' + job.price + ' руб.');
                    });
                });
            }
            loadJobs();
            document.getElementById('filterBtn').onclick = function() {
                var mp = document.getElementById('maxPrice').value;
                loadJobs(mp || undefined);
            };
            var addBtn = document.getElementById('addBtn');
            var formContainer = document.getElementById('formContainer');
            var saveBtn = document.getElementById('saveBtn');
            var cancelBtn = document.getElementById('cancelBtn');
            addBtn.onclick = function() { formContainer.style.display = 'block'; };
            cancelBtn.onclick = function() {
                formContainer.style.display = 'none';
                if (tempMarker) { map.removeLayer(tempMarker); tempMarker = null; selectedLatLng = null; }
            };
            saveBtn.onclick = function() {
                var title = document.getElementById('title').value;
                var desc = document.getElementById('description').value;
                var price = document.getElementById('price').value;
                if (!title || !price) { alert('Введи название и оплату'); return; }
                if (!selectedLatLng) { alert('Сначала кликни по карте, чтобы выбрать место!'); return; }
                fetch('/add_job', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({title:title, description:desc, price:parseFloat(price), lat:selectedLatLng.lat, lng:selectedLatLng.lng})
                }).then(r=>r.json()).then(() => {
                    L.marker([selectedLatLng.lat, selectedLatLng.lng]).addTo(map)
                        .bindPopup('<b>' + title + '</b><br>' + desc + '<br>Цена: ' + price + ' руб.');
                    document.getElementById('title').value = '';
                    document.getElementById('description').value = '';
                    document.getElementById('price').value = '';
                    formContainer.style.display = 'none';
                    if (tempMarker) { map.removeLayer(tempMarker); tempMarker = null; selectedLatLng = null; }
                });
            };
        </script>
    </body>
    </html>
    '''
    return html

# ---------- ЗАПУСК ----------
if __name__ == '__main__':
    app.run(debug=True)