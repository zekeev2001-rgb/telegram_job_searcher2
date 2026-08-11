import sqlite3
import os
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2

from flask import Flask, request, jsonify, send_from_directory

APP_URL = os.environ.get('APP_URL', 'https://near-gig.onrender.com')

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, price REAL, lat REAL, lng REAL, category TEXT DEFAULT 'Другое', created_at TEXT, expires_at TEXT, likes INTEGER DEFAULT 0)''')
    try: c.execute('ALTER TABLE jobs ADD COLUMN category TEXT DEFAULT "Другое"')
    except: pass
    try: c.execute('ALTER TABLE jobs ADD COLUMN created_at TEXT')
    except: pass
    try: c.execute('ALTER TABLE jobs ADD COLUMN expires_at TEXT')
    except: pass
    try: c.execute('ALTER TABLE jobs ADD COLUMN likes INTEGER DEFAULT 0')
    except: pass
    conn.commit()
    conn.close()

init_db()

def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

@app.route('/manifest.json')
def manifest():
    return send_from_directory('.', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    return '''self.addEventListener('install', function(e) { self.skipWaiting(); });
self.addEventListener('activate', function(e) { clients.claim(); e.waitUntil(caches.keys().then(function(keys) { return Promise.all(keys.map(function(key) { return caches.delete(key); })); })); });
self.addEventListener('fetch', function(e) { e.respondWith(fetch(e.request)); });'''

@app.route('/get_jobs')
def get_jobs():
    category = request.args.get('category')
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    radius = request.args.get('radius', type=float)
    max_price = request.args.get('max_price', type=float)
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    query = 'SELECT id, title, description, price, lat, lng, category, created_at, expires_at, likes FROM jobs WHERE (expires_at IS NULL OR expires_at > ?)'
    params = [datetime.now().isoformat()]
    if category: query += ' AND category = ?'; params.append(category)
    if max_price is not None: query += ' AND price <= ?'; params.append(max_price)
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    jobs = []
    for r in rows:
        job = {'id': r[0], 'title': r[1], 'description': r[2], 'price': r[3], 'lat': r[4], 'lng': r[5], 'category': r[6], 'created_at': r[7], 'expires_at': r[8], 'likes': r[9]}
        if lat is not None and lng is not None and radius is not None:
            dist = haversine(lat, lng, job['lat'], job['lng'])
            if dist <= radius: job['distance'] = round(dist, 2); jobs.append(job)
        else: jobs.append(job)
    return jsonify(jobs)

@app.route('/add_job', methods=['POST'])
def add_job():
    data = request.get_json()
    title, description = data['title'], data.get('description', '')
    price, lat, lng = data['price'], data['lat'], data['lng']
    category = data.get('category', 'Другое')
    days_valid = data.get('days_valid', 30)
    created_at = datetime.now().isoformat()
    expires_at = (datetime.now() + timedelta(days=days_valid)).isoformat()
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('INSERT INTO jobs (title, description, price, lat, lng, category, created_at, expires_at, likes) VALUES (?,?,?,?,?,?,?,?,0)', (title, description, price, lat, lng, category, created_at, expires_at))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'}), 201

@app.route('/like_job', methods=['POST'])
def like_job():
    data = request.get_json()
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('UPDATE jobs SET likes = likes + 1 WHERE id = ?', (data['id'],))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/')
def map_page():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Near Gig</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
        <link rel="manifest" href="/manifest.json?v=4">
        <meta name="theme-color" content="#2196F3">
        <link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/1041/1041916.png">
        <meta name="mobile-web-app-capable" content="yes">
        <style>body,html,#map{height:100%;width:100%;margin:0;padding:0;}.panel{position:absolute;top:10px;left:50px;z-index:1000;background:white;padding:8px;border-radius:5px;box-shadow:0 0 5px rgba(0,0,0,0.3);display:flex;gap:5px;flex-wrap:wrap;}.panel input,.panel select,.panel button{font-size:14px;}.search-container{position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:1000;background:white;border-radius:5px;box-shadow:0 0 5px rgba(0,0,0,0.3);display:flex;overflow:hidden;}.search-container input{border:none;padding:8px;width:200px;font-size:14px;outline:none;}.search-container button{border:none;background:#2196F3;color:white;padding:8px 12px;cursor:pointer;font-size:14px;}.locate-btn{position:absolute;top:10px;left:10px;z-index:1000;background:white;padding:5px 10px;border-radius:5px;box-shadow:0 0 5px rgba(0,0,0,0.3);cursor:pointer;font-size:16px;border:none;}</style>
        <script src="https://api-maps.yandex.ru/2.1/?apikey=27ec90a8-477d-41ac-a054-ba4bdd3bd265&lang=ru_RU" type="text/javascript"></script>
    </head>
    <body>
        <div class="panel">
            <select id="categoryFilter"><option value="">Все категории</option><option>Курьер</option><option>Уборка</option><option>Ремонт</option><option>IT</option><option>Другое</option></select>
            <input type="number" id="maxPrice" placeholder="Макс. цена" style="width:90px;">
            <input type="number" id="radius" placeholder="Радиус, км" style="width:90px;">
            <button id="filterBtn">Искать</button>
        </div>
        <button id="addBtn" style="position:absolute;top:10px;right:10px;z-index:1000;padding:10px;background:green;color:white;border:none;border-radius:5px;">+</button>
        <div class="search-container"><input type="text" id="searchInput" placeholder="Поиск адреса..."><button id="searchBtn">🔍</button></div>
        <div id="map"></div>
        <div id="formContainer" style="display:none;position:absolute;top:50px;right:10px;background:white;padding:15px;border-radius:8px;box-shadow:0 0 10px rgba(0,0,0,0.3);z-index:1000;">
            <input type="text" id="title" placeholder="Название" style="width:100%;margin-bottom:5px;"><br>
            <input type="text" id="description" placeholder="Описание" style="width:100%;margin-bottom:5px;"><br>
            <input type="number" id="price" placeholder="Оплата, руб" style="width:100%;margin-bottom:5px;"><br>
            <select id="category"><option>Курьер</option><option>Уборка</option><option>Ремонт</option><option>IT</option><option>Другое</option></select><br><br>
            <input type="number" id="daysValid" placeholder="Актуально дней" value="30" style="width:100%;"><br><br>
            <button id="saveBtn">Сохранить</button>
            <button id="cancelBtn">Отмена</button>
        </div>
        <button id="manualLocateBtn" class="locate-btn" title="Моё местоположение">📍</button>

        <script>
            if ('serviceWorker' in navigator) {
                navigator.serviceWorker.getRegistrations().then(function(regs) {
                    for(let r of regs) r.unregister();
                });
            }

            var myMap, myPlacemark, selectedCoords = null;
            var YANDEX_GEOCODER_KEY = 'a1072bf1-5f7e-4d8b-b535-a231feb84cf8';

            ymaps.ready(function() {
                myMap = new ymaps.Map('map', {
                    center: [55.7558, 37.6173],
                    zoom: 12,
                    controls: ['zoomControl', 'typeSelector', 'geolocationControl'],
                    storage: false  // 🔥 Отключаем использование localStorage (решает проблему Tracking Prevention)
                });

                loadJobs();

                myMap.events.add('click', function(e) {
                    if (document.getElementById('formContainer').style.display === 'block') {
                        setTempMarker(e.get('coords'));
                    }
                });
            });

            function setTempMarker(coords) {
                if (myPlacemark) myMap.geoObjects.remove(myPlacemark);
                myPlacemark = new ymaps.Placemark(coords, { balloonContent: 'Здесь будет ваша подработка' });
                myMap.geoObjects.add(myPlacemark);
                myPlacemark.balloon.open();
                selectedCoords = coords;
            }

            document.getElementById('addBtn').addEventListener('click', function() {
                document.getElementById('formContainer').style.display = 'block';
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(
                        function(pos) {
                            var coords = [pos.coords.latitude, pos.coords.longitude];
                            setTempMarker(coords);
                            myMap.setCenter(coords, 15);
                        },
                        function() { alert('Не удалось определить местоположение.'); },
                        { enableHighAccuracy: true, timeout: 10000 }
                    );
                }
            });

            document.getElementById('cancelBtn').addEventListener('click', function() {
                document.getElementById('formContainer').style.display = 'none';
                if (myPlacemark) { myMap.geoObjects.remove(myPlacemark); myPlacemark = null; selectedCoords = null; }
            });

            document.getElementById('manualLocateBtn').addEventListener('click', function() {
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(
                        function(pos) { myMap.setCenter([pos.coords.latitude, pos.coords.longitude], 15); },
                        function() { alert('Не удалось определить местоположение.'); }
                    );
                }
            });

            function loadJobs(filters = {}) {
                if (myMap) {
                    myMap.geoObjects.each(function(obj) {
                        if (obj !== myPlacemark) myMap.geoObjects.remove(obj);
                    });
                }
                var params = new URLSearchParams(filters).toString();
                fetch('/get_jobs?' + params).then(r => r.json()).then(jobs => {
                    jobs.forEach(job => {
                        var placemark = new ymaps.Placemark([job.lat, job.lng], {
                            balloonContent: '<b>'+job.title+'</b><br>'+job.description+'<br>Цена: '+job.price+' руб.<br>Категория: '+job.category+'<br>❤️ '+job.likes+' <button onclick="likeJob('+job.id+')">Нравится</button>'
                        });
                        myMap.geoObjects.add(placemark);
                    });
                });
            }

            window.likeJob = function(id) {
                fetch('/like_job', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id}) }).then(() => loadJobs(getCurrentFilters()));
            };

            document.getElementById('filterBtn').onclick = function() {
                var filters = {};
                var cat = document.getElementById('categoryFilter').value;
                var mp = document.getElementById('maxPrice').value;
                var rad = document.getElementById('radius').value;
                if (cat) filters.category = cat;
                if (mp) filters.max_price = mp;
                if (rad) { var c = myMap.getCenter(); filters.lat = c[0]; filters.lng = c[1]; filters.radius = rad; }
                loadJobs(filters);
            };

            function getCurrentFilters() {
                var f = {};
                var cat = document.getElementById('categoryFilter').value;
                var mp = document.getElementById('maxPrice').value;
                var rad = document.getElementById('radius').value;
                if (cat) f.category = cat;
                if (mp) f.max_price = mp;
                if (rad) { var c = myMap.getCenter(); f.lat = c[0]; f.lng = c[1]; f.radius = rad; }
                return f;
            }

            document.getElementById('searchBtn').addEventListener('click', function() {
                var query = document.getElementById('searchInput').value.trim();
                if (!query) return;
                var url = 'https://geocode-maps.yandex.ru/1.x/?format=json&apikey=' + YANDEX_GEOCODER_KEY +
                          '&geocode=' + encodeURIComponent(query) + '&lang=ru_RU&results=1';
                fetch(url).then(r => r.json()).then(data => {
                    var pos = data.response.GeoObjectCollection.featureMember[0].GeoObject.Point.pos.split(' ');
                    var coords = [parseFloat(pos[1]), parseFloat(pos[0])];
                    myMap.setCenter(coords, 15);
                    if (document.getElementById('formContainer').style.display === 'block') setTempMarker(coords);
                });
            });

            document.getElementById('saveBtn').addEventListener('click', function() {
                var title = document.getElementById('title').value;
                var desc = document.getElementById('description').value;
                var price = document.getElementById('price').value;
                var cat = document.getElementById('category').value;
                var days = document.getElementById('daysValid').value;
                if (!title||!price||!selectedCoords) { alert('Заполните все поля и выберите место'); return; }
                fetch('/add_job', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({title,description:desc,price:parseFloat(price),lat:selectedCoords[0],lng:selectedCoords[1],category:cat,days_valid:parseInt(days)})
                }).then(r=>r.json()).then(() => {
                    alert('Объявление добавлено!');
                    document.getElementById('formContainer').style.display = 'none';
                    if (myPlacemark) { myMap.geoObjects.remove(myPlacemark); myPlacemark=null; selectedCoords=null; }
                    loadJobs(getCurrentFilters());
                });
            });
        </script>
    </body>
    </html>
    '''

if __name__ == '__main__':
    app.run(debug=True)
