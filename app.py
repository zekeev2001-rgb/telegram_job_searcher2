import sqlite3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from flask import Flask, request, jsonify, send_from_directory

APP_URL = os.environ.get('APP_URL', 'https://near-gig.onrender.com')
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# ==========================================
# БАЗА ДАННЫХ
# ==========================================
def init_db():
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        phone TEXT,
        role TEXT DEFAULT 'executor',
        avatar_url TEXT DEFAULT 'https://cdn-icons-png.flaticon.com/512/149/149071.png',
        rating REAL DEFAULT 0,
        reviews_count INTEGER DEFAULT 0,
        completed_jobs INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        last_login TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        price REAL,
        lat REAL,
        lng REAL,
        category TEXT DEFAULT 'Другое',
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT,
        views INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        message TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(job_id) REFERENCES jobs(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user_id INTEGER NOT NULL,
        to_user_id INTEGER NOT NULL,
        job_id INTEGER,
        rating INTEGER CHECK(rating >= 1 AND rating <= 5),
        comment TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(from_user_id) REFERENCES users(id),
        FOREIGN KEY(to_user_id) REFERENCES users(id),
        FOREIGN KEY(job_id) REFERENCES jobs(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(job_id) REFERENCES jobs(id),
        UNIQUE(user_id, job_id)
    )''')
    
    conn.commit()
    conn.close()

init_db()

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return secrets.token_hex(32)

def get_user_by_token(token):
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('''SELECT users.* FROM users 
                 JOIN sessions ON users.id = sessions.user_id 
                 WHERE sessions.token = ? AND sessions.expires_at > datetime("now")''', (token,))
    user = c.fetchone()
    conn.close()
    if user:
        return {
            'id': user[0], 'email': user[1], 'name': user[3], 'phone': user[4],
            'role': user[5], 'avatar_url': user[6], 'rating': user[7],
            'reviews_count': user[8], 'completed_jobs': user[9]
        }
    return None

def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

# ==========================================
# АУТЕНТИФИКАЦИЯ
# ==========================================
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '').strip()
    role = data.get('role', 'executor')
    
    if not email or not password or not name:
        return jsonify({'error': 'Заполните все поля'}), 400
    
    if len(password) < 6:
        return jsonify({'error': 'Пароль должен быть минимум 6 символов'}), 400
    
    if '@' not in email or '.' not in email:
        return jsonify({'error': 'Некорректный email'}), 400
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    
    c.execute('SELECT id FROM users WHERE email = ?', (email,))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Этот email уже зарегистрирован'}), 409
    
    password_hash = hash_password(password)
    c.execute('INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)',
              (email, password_hash, name, role))
    user_id = c.lastrowid
    
    token = generate_token()
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    c.execute('INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)',
              (user_id, token, expires_at))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'token': token,
        'user': {
            'id': user_id, 'email': email, 'name': name,
            'role': role, 'avatar_url': 'https://cdn-icons-png.flaticon.com/512/149/149071.png',
            'rating': 0, 'reviews_count': 0, 'completed_jobs': 0
        }
    }), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    
    if not email or not password:
        return jsonify({'error': 'Введите email и пароль'}), 400
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE email = ?', (email,))
    user = c.fetchone()
    
    if not user or user[2] != hash_password(password):
        conn.close()
        return jsonify({'error': 'Неверный email или пароль'}), 401
    
    token = generate_token()
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    c.execute('INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)',
              (user[0], token, expires_at))
    
    c.execute('UPDATE users SET last_login = datetime("now") WHERE id = ?', (user[0],))
    conn.commit()
    conn.close()
    
    return jsonify({
        'token': token,
        'user': {
            'id': user[0], 'email': user[1], 'name': user[3], 'phone': user[4],
            'role': user[5], 'avatar_url': user[6], 'rating': user[7],
            'reviews_count': user[8], 'completed_jobs': user[9]
        }
    })

@app.route('/api/logout', methods=['POST'])
def logout():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('DELETE FROM sessions WHERE token = ?', (token,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/me', methods=['GET'])
def get_me():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    return jsonify(user)

# ==========================================
# РАБОТА С ПОДРАБОТКАМИ
# ==========================================
@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    category = request.args.get('category')
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    radius = request.args.get('radius', type=float)
    max_price = request.args.get('max_price', type=float)
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    
    query = '''SELECT jobs.*, users.name, users.rating, users.avatar_url
               FROM jobs JOIN users ON jobs.user_id = users.id
               WHERE jobs.status = 'active' '''
    params = []
    
    if category:
        query += ' AND jobs.category = ?'
        params.append(category)
    if max_price is not None:
        query += ' AND jobs.price <= ?'
        params.append(max_price)
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    jobs = []
    for r in rows:
        job = {
            'id': r[0], 'user_id': r[1], 'title': r[2], 'description': r[3],
            'price': r[4], 'lat': r[5], 'lng': r[6], 'category': r[7],
            'created_at': r[9],
            'author': {'name': r[12], 'rating': r[13], 'avatar': r[14]}
        }
        if lat and lng and radius:
            dist = haversine(lat, lng, job['lat'], job['lng'])
            if dist <= radius:
                job['distance'] = round(dist, 2)
                jobs.append(job)
        else:
            jobs.append(job)
    
    return jsonify(jobs)

@app.route('/api/jobs', methods=['POST'])
def create_job():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    
    data = request.get_json()
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    price = data.get('price')
    lat = data.get('lat')
    lng = data.get('lng')
    category = data.get('category', 'Другое')
    
    if not title or not price or not lat or not lng:
        return jsonify({'error': 'Заполните обязательные поля'}), 400
    
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('''INSERT INTO jobs (user_id, title, description, price, lat, lng, category, expires_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (user['id'], title, description, price, lat, lng, category, expires_at))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'ok'}), 201

# ==========================================
# PWA ФАЙЛЫ
# ==========================================
@app.route('/manifest.json')
def manifest():
    manifest_data = {
        "name": "Near Gig",
        "short_name": "Near Gig",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#6366F1",
        "icons": [
            {"src": "https://cdn-icons-png.flaticon.com/512/1041/1041916.png", "sizes": "192x192", "type": "image/png"},
            {"src": "https://cdn-icons-png.flaticon.com/512/1041/1041916.png", "sizes": "512x512", "type": "image/png"}
        ]
    }
    return jsonify(manifest_data)

@app.route('/sw.js')
def service_worker():
    return '''self.addEventListener('install', function(e) { self.skipWaiting(); });
self.addEventListener('activate', function(e) { clients.claim(); });
self.addEventListener('fetch', function(e) { e.respondWith(fetch(e.request)); });'''

# ==========================================
# ГЛАВНАЯ СТРАНИЦА
# ==========================================
@app.route('/')
def index():
    return '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Near Gig</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#6366F1">
    <link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/1041/1041916.png">
    <meta name="mobile-web-app-capable" content="yes">
    <script src="https://api-maps.yandex.ru/2.1/?apikey=27ec90a8-477d-41ac-a054-ba4bdd3bd265&lang=ru_RU"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        * { -webkit-tap-highlight-color: transparent; }
        body { overscroll-behavior: none; }
        .tab-active { color: #6366F1; border-bottom: 2px solid #6366F1; }
        
        /* Кнопка геолокации */
        .custom-locate-btn {
            position: absolute;
            top: 80px;
            right: 10px;
            z-index: 1000;
            background: white;
            padding: 0;
            border-radius: 8px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            cursor: pointer;
            font-size: 18px;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 40px;
            height: 40px;
        }
        
        /* Кнопки зума — слева вверху */
        .ymaps-2-1-79-zoom {
            top: 80px !important;
            left: 10px !important;
        }
        
        /* Переключатель слоёв — ВНИЗУ СПРАВА */
        .ymaps-2-1-79-type-selector {
            top: auto !important;
            bottom: 80px !important;
            right: 10px !important;
            left: auto !important;
        }
    </style>
</head>
<body class="bg-white overflow-hidden h-screen">
    <div id="header" class="fixed top-0 left-0 right-0 z-50 bg-white border-b px-4 py-3 flex justify-between items-center">
        <h1 class="text-xl font-bold text-gray-900">Near Gig</h1>
        <div class="flex gap-3">
            <button id="loginBtn" onclick="openAuth()" class="text-sm text-indigo-600 font-medium px-3 py-1 rounded-full border border-indigo-200">Войти</button>
            <div id="userMenu" class="hidden relative">
                <button id="profileBtn" class="w-9 h-9 rounded-full bg-gray-200 overflow-hidden">
                    <img id="avatarImg" src="https://cdn-icons-png.flaticon.com/512/149/149071.png" class="w-full h-full object-cover">
                </button>
                <div id="dropdownMenu" class="hidden absolute right-0 top-10 bg-white shadow-lg rounded-lg py-2 w-48 border">
                    <button onclick="showProfile()" class="w-full text-left px-4 py-2 text-sm hover:bg-gray-50">Профиль</button>
                    <button onclick="logout()" class="w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-gray-50">Выйти</button>
                </div>
            </div>
        </div>
    </div>

    <div id="map" class="w-full h-full"></div>

    <!-- Кнопка геолокации -->
    <button id="manualLocateBtn" class="custom-locate-btn" title="Моё местоположение">📍</button>

    <!-- Нижнее меню -->
    <div class="fixed bottom-0 left-0 right-0 z-50 bg-white border-t px-4 py-2 flex justify-around">
        <button onclick="switchTab('map')" id="tabMap" class="tab-active flex flex-col items-center text-xs pb-1">
            <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
            Карта
        </button>
        <button onclick="switchTab('add')" id="tabAdd" class="flex flex-col items-center text-xs text-gray-500 pb-1">
            <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 11h-4v4h-2v-4H7v-2h4V7h2v4h4v2z"/></svg>
            Создать
        </button>
        <button onclick="switchTab('list')" id="tabList" class="flex flex-col items-center text-xs text-gray-500 pb-1">
            <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M4 14h4v-4H4v4zm6 0h4v-4h-4v4zm6 0h4v-4h-4v4zM4 20h4v-4H4v4zm6 0h4v-4h-4v4zm6 0h4v-4h-4v4z"/></svg>
            Задания
        </button>
        <button onclick="switchTab('profile')" id="tabProfile" class="flex flex-col items-center text-xs text-gray-500 pb-1">
            <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
            Профиль
        </button>
    </div>

    <!-- Модальное окно авторизации -->
    <div id="authModal" class="hidden fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
        <div class="bg-white rounded-2xl p-6 w-full max-w-md">
            <h2 class="text-xl font-bold mb-4 text-center" id="authTitle">Вход</h2>
            <form id="authForm" class="space-y-3">
                <input type="email" id="authEmail" placeholder="Email" class="w-full px-4 py-3 border border-gray-200 rounded-xl" required autocomplete="email">
                <input type="password" id="authPassword" placeholder="Пароль" class="w-full px-4 py-3 border border-gray-200 rounded-xl" required>
                <input type="text" id="authName" placeholder="Ваше имя" class="w-full px-4 py-3 border border-gray-200 rounded-xl hidden" autocomplete="name">
                <button type="submit" class="w-full bg-indigo-600 text-white py-3 rounded-xl font-medium">Войти</button>
            </form>
            <p class="text-center text-sm mt-3 text-gray-500">
                <span id="authSwitchText">Нет аккаунта?</span>
                <button id="authSwitchBtn" class="text-indigo-600 font-medium ml-1">Зарегистрироваться</button>
            </p>
            <button onclick="closeAuth()" class="mt-3 w-full py-2 text-gray-400 text-sm">Отмена</button>
        </div>
    </div>

    <!-- Модальное окно создания задания -->
    <div id="jobFormModal" class="hidden fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
        <div class="bg-white rounded-2xl p-6 w-full max-w-md">
            <h2 class="text-xl font-bold mb-4">Новая подработка</h2>
            <input id="jobTitle" placeholder="Название" class="w-full px-4 py-3 border border-gray-200 rounded-xl mb-2">
            <textarea id="jobDesc" placeholder="Описание" class="w-full px-4 py-3 border border-gray-200 rounded-xl mb-2" rows="3"></textarea>
            <input id="jobPrice" type="number" placeholder="Цена, руб" class="w-full px-4 py-3 border border-gray-200 rounded-xl mb-2">
            <select id="jobCategory" class="w-full px-4 py-3 border border-gray-200 rounded-xl mb-2">
                <option>Курьер</option><option>Уборка</option><option>Ремонт</option><option>IT</option><option>Другое</option>
            </select>
            <p id="coordsInfo" class="text-sm text-gray-400 mb-3">Нажмите на карту, чтобы выбрать место</p>
            <button onclick="createJob()" class="w-full bg-indigo-600 text-white py-3 rounded-xl font-medium mb-2">Опубликовать</button>
            <button onclick="closeJobForm()" class="w-full py-2 text-gray-400 text-sm">Отмена</button>
        </div>
    </div>

    <script>
        let myMap, currentUser = null, authToken = null;
        let selectedCoords = null, tempPlacemark = null;

        ymaps.ready(() => {
            myMap = new ymaps.Map('map', {
                center: [55.7558, 37.6173],
                zoom: 12,
                controls: ['zoomControl', 'typeSelector']
            });
            loadJobsOnMap();
            myMap.events.add('click', e => {
                if (document.getElementById('jobFormModal').classList.contains('hidden')) return;
                setTempMarker(e.get('coords'));
            });
        });

        function setTempMarker(coords) {
            if (tempPlacemark) myMap.geoObjects.remove(tempPlacemark);
            tempPlacemark = new ymaps.Placemark(coords, { balloonContent: 'Здесь будет задание' });
            myMap.geoObjects.add(tempPlacemark);
            tempPlacemark.balloon.open();
            selectedCoords = coords;
            document.getElementById('coordsInfo').textContent = 'Место выбрано';
        }

        function loadJobsOnMap(filters = {}) {
            if (!myMap) return;
            myMap.geoObjects.each(obj => { if (obj !== tempPlacemark) myMap.geoObjects.remove(obj); });
            fetch('/api/jobs?' + new URLSearchParams(filters))
                .then(r => r.json())
                .then(jobs => {
                    jobs.forEach(job => {
                        const pm = new ymaps.Placemark([job.lat, job.lng], {
                            balloonContent: '<b>' + job.title + '</b><br>' + job.description + '<br>💰 ' + job.price + ' руб.<br>👤 ' + job.author.name + ' ⭐' + job.author.rating
                        });
                        myMap.geoObjects.add(pm);
                    });
                });
        }

        function switchTab(tab) {
            document.querySelectorAll('[id^="tab"]').forEach(b => {
                b.className = b.className.replace('tab-active', '').replace('text-gray-900', 'text-gray-500');
            });
            const activeTab = document.getElementById('tab' + tab.charAt(0).toUpperCase() + tab.slice(1));
            if (activeTab) activeTab.className += ' tab-active';
            
            if (tab === 'add') {
                if (!currentUser) return openAuth();
                document.getElementById('jobFormModal').classList.remove('hidden');
            }
        }

        function openAuth() { document.getElementById('authModal').classList.remove('hidden'); }
        function closeAuth() { document.getElementById('authModal').classList.add('hidden'); }
        function closeJobForm() {
            document.getElementById('jobFormModal').classList.add('hidden');
            if (tempPlacemark) { myMap.geoObjects.remove(tempPlacemark); tempPlacemark = null; }
        }

        document.getElementById('authSwitchBtn').addEventListener('click', () => {
            const authTitle = document.getElementById('authTitle');
            const authName = document.getElementById('authName');
            const authSwitchText = document.getElementById('authSwitchText');
            const authSwitchBtn = document.getElementById('authSwitchBtn');
            const submitBtn = document.querySelector('#authForm button[type="submit"]');
            
            const isLogin = authTitle.textContent === 'Вход';
            
            if (isLogin) {
                authTitle.textContent = 'Регистрация';
                authName.classList.remove('hidden');
                authSwitchText.textContent = 'Есть аккаунт?';
                authSwitchBtn.textContent = 'Войти';
                submitBtn.textContent = 'Зарегистрироваться';
            } else {
                authTitle.textContent = 'Вход';
                authName.classList.add('hidden');
                authSwitchText.textContent = 'Нет аккаунта?';
                authSwitchBtn.textContent = 'Зарегистрироваться';
                submitBtn.textContent = 'Войти';
            }
        });

        document.getElementById('authForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const isLogin = document.getElementById('authTitle').textContent === 'Вход';
            const email = document.getElementById('authEmail').value.trim();
            const password = document.getElementById('authPassword').value.trim();
            
            if (!email || !password) {
                alert('Заполните email и пароль');
                return;
            }
            
            const url = isLogin ? '/api/login' : '/api/register';
            const body = { email, password };
            
            if (!isLogin) {
                const name = document.getElementById('authName').value.trim();
                if (!name) {
                    alert('Введите ваше имя');
                    return;
                }
                body.name = name;
            }
            
            try {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    currentUser = data.user;
                    authToken = data.token;
                    localStorage.setItem('token', authToken);
                    updateUI();
                    closeAuth();
                    document.getElementById('authEmail').value = '';
                    document.getElementById('authPassword').value = '';
                    document.getElementById('authName').value = '';
                } else {
                    alert(data.error || 'Ошибка');
                }
            } catch (err) {
                alert('Ошибка соединения с сервером');
            }
        });

        async function logout() {
            try {
                await fetch('/api/logout', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + authToken }
                });
            } catch (err) {}
            currentUser = null;
            authToken = null;
            localStorage.removeItem('token');
            updateUI();
        }

        function updateUI() {
            if (currentUser) {
                document.getElementById('loginBtn').classList.add('hidden');
                document.getElementById('userMenu').classList.remove('hidden');
                document.getElementById('avatarImg').src = currentUser.avatar_url || 'https://cdn-icons-png.flaticon.com/512/149/149071.png';
            } else {
                document.getElementById('loginBtn').classList.remove('hidden');
                document.getElementById('userMenu').classList.add('hidden');
            }
        }

        document.getElementById('profileBtn').addEventListener('click', () => {
            document.getElementById('dropdownMenu').classList.toggle('hidden');
        });

        function showProfile() {
            if (!currentUser) return openAuth();
            alert('Профиль\\nИмя: ' + currentUser.name + '\\nEmail: ' + currentUser.email + '\\nРейтинг: ' + currentUser.rating);
        }

        // Кнопка геолокации
        document.getElementById('manualLocateBtn').addEventListener('click', () => {
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(
                    pos => {
                        const coords = [pos.coords.latitude, pos.coords.longitude];
                        myMap.setCenter(coords, 15);
                        if (document.getElementById('jobFormModal').classList.contains('hidden') === false) {
                            setTempMarker(coords);
                        }
                    },
                    () => alert('Не удалось определить местоположение'),
                    { enableHighAccuracy: true, timeout: 10000 }
                );
            } else {
                alert('Геолокация не поддерживается');
            }
        });

        async function createJob() {
            if (!currentUser) return openAuth();
            
            const title = document.getElementById('jobTitle').value.trim();
            const desc = document.getElementById('jobDesc').value.trim();
            const price = document.getElementById('jobPrice').value;
            const cat = document.getElementById('jobCategory').value;
            
            if (!title || !price || !selectedCoords) {
                alert('Заполните все поля и выберите место на карте');
                return;
            }
            
            try {
                const res = await fetch('/api/jobs', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + authToken
                    },
                    body: JSON.stringify({
                        title: title,
                        description: desc,
                        price: parseFloat(price),
                        lat: selectedCoords[0],
                        lng: selectedCoords[1],
                        category: cat
                    })
                });
                
                if (res.ok) {
                    alert('Задание опубликовано!');
                    closeJobForm();
                    loadJobsOnMap();
                }
            } catch (err) {
                alert('Ошибка при создании задания');
            }
        }

        const savedToken = localStorage.getItem('token');
        if (savedToken) {
            fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + savedToken } })
                .then(r => r.ok ? r.json() : Promise.reject())
                .then(user => {
                    currentUser = user;
                    authToken = savedToken;
                    updateUI();
                })
                .catch(() => localStorage.removeItem('token'));
        }
    </script>
</body>
</html>'''

if __name__ == '__main__':
    app.run(debug=True)
