import sqlite3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from flask import Flask, request, jsonify, make_response, send_from_directory

APP_URL = os.environ.get('APP_URL', 'https://near-gig.onrender.com')
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# ==========================================
# БАЗА ДАННЫХ
# ==========================================
def init_db():
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        phone TEXT,
        role TEXT DEFAULT 'executor',  -- executor / customer
        avatar_url TEXT DEFAULT 'https://cdn-icons-png.flaticon.com/512/149/149071.png',
        rating REAL DEFAULT 0,
        reviews_count INTEGER DEFAULT 0,
        completed_jobs INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        last_login TEXT
    )''')
    
    # Таблица сессий
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    # Таблица подработок (обновлённая)
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        price REAL,
        lat REAL,
        lng REAL,
        category TEXT DEFAULT 'Другое',
        status TEXT DEFAULT 'active',  -- active / in_progress / completed / cancelled
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT,
        views INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    # Таблица откликов
    c.execute('''CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        message TEXT,
        status TEXT DEFAULT 'pending',  -- pending / accepted / rejected
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(job_id) REFERENCES jobs(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    
    # Таблица отзывов
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
    
    # Таблица избранного
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
    """Хеширование пароля"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    """Генерация токена сессии"""
    return secrets.token_hex(32)

def get_user_by_token(token):
    """Получение пользователя по токену сессии"""
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
    """Расчёт расстояния между координатами в км"""
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
    """Регистрация нового пользователя"""
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '').strip()
    role = data.get('role', 'executor')
    
    if not email or not password or not name:
        return jsonify({'error': 'Заполните все поля'}), 400
    
    if len(password) < 6:
        return jsonify({'error': 'Пароль должен быть минимум 6 символов'}), 400
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    
    # Проверка на существование email
    c.execute('SELECT id FROM users WHERE email = ?', (email,))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Этот email уже зарегистрирован'}), 409
    
    # Создание пользователя
    password_hash = hash_password(password)
    c.execute('INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)',
              (email, password_hash, name, role))
    user_id = c.lastrowid
    
    # Создание сессии
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
    """Вход пользователя"""
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
    
    # Создание новой сессии
    token = generate_token()
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    c.execute('INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)',
              (user[0], token, expires_at))
    
    # Обновление last_login
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
    """Выход из системы"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('DELETE FROM sessions WHERE token = ?', (token,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/me', methods=['GET'])
def get_me():
    """Получение профиля текущего пользователя"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    return jsonify(user)

@app.route('/api/profile', methods=['PUT'])
def update_profile():
    """Обновление профиля"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    
    data = request.get_json()
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    
    if 'name' in data:
        c.execute('UPDATE users SET name = ? WHERE id = ?', (data['name'], user['id']))
    if 'phone' in data:
        c.execute('UPDATE users SET phone = ? WHERE id = ?', (data['phone'], user['id']))
    if 'avatar_url' in data:
        c.execute('UPDATE users SET avatar_url = ? WHERE id = ?', (data['avatar_url'], user['id']))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

# ==========================================
# РАБОТА С ПОДРАБОТКАМИ
# ==========================================
@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    """Получение списка подработок"""
    category = request.args.get('category')
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    radius = request.args.get('radius', type=float)
    max_price = request.args.get('max_price', type=float)
    status = request.args.get('status', 'active')
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    
    query = '''SELECT jobs.*, users.name as author_name, users.rating as author_rating, users.avatar_url as author_avatar
               FROM jobs JOIN users ON jobs.user_id = users.id
               WHERE jobs.status = ?'''
    params = [status]
    
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
            'status': r[8], 'created_at': r[9], 'expires_at': r[10], 'views': r[11],
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
    """Создание новой подработки"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    
    data = request.get_json()
    title = data.get('title')
    description = data.get('description', '')
    price = data.get('price')
    lat = data.get('lat')
    lng = data.get('lng')
    category = data.get('category', 'Другое')
    days_valid = data.get('days_valid', 30)
    
    if not title or not price or not lat or not lng:
        return jsonify({'error': 'Заполните обязательные поля'}), 400
    
    expires_at = (datetime.now() + timedelta(days=days_valid)).isoformat()
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('''INSERT INTO jobs (user_id, title, description, price, lat, lng, category, expires_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (user['id'], title, description, price, lat, lng, category, expires_at))
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({'id': job_id, 'status': 'ok'}), 201

# ==========================================
# ОТКЛИКИ НА ЗАДАНИЯ
# ==========================================
@app.route('/api/jobs/<int:job_id>/respond', methods=['POST'])
def respond_to_job(job_id):
    """Отклик на подработку"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    
    data = request.get_json()
    message = data.get('message', '')
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('INSERT INTO responses (job_id, user_id, message) VALUES (?, ?, ?)',
              (job_id, user['id'], message))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'ok'}), 201

# ==========================================
# ОТЗЫВЫ И РЕЙТИНГ
# ==========================================
@app.route('/api/reviews', methods=['POST'])
def create_review():
    """Создание отзыва"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    
    data = request.get_json()
    to_user_id = data.get('to_user_id')
    job_id = data.get('job_id')
    rating = data.get('rating')
    comment = data.get('comment', '')
    
    if not to_user_id or not rating or rating < 1 or rating > 5:
        return jsonify({'error': 'Некорректные данные'}), 400
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('INSERT INTO reviews (from_user_id, to_user_id, job_id, rating, comment) VALUES (?, ?, ?, ?, ?)',
              (user['id'], to_user_id, job_id, rating, comment))
    
    # Обновление рейтинга пользователя
    c.execute('SELECT AVG(rating), COUNT(*) FROM reviews WHERE to_user_id = ?', (to_user_id,))
    avg_rating, count = c.fetchone()
    c.execute('UPDATE users SET rating = ?, reviews_count = ? WHERE id = ?',
              (round(avg_rating, 2) if avg_rating else 0, count, to_user_id))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'}), 201

# ==========================================
# ИЗБРАННОЕ
# ==========================================
@app.route('/api/favorites', methods=['GET'])
def get_favorites():
    """Получение избранного"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('''SELECT jobs.* FROM jobs 
                 JOIN favorites ON jobs.id = favorites.job_id 
                 WHERE favorites.user_id = ?''', (user['id'],))
    rows = c.fetchall()
    conn.close()
    
    jobs = [{'id': r[0], 'title': r[2], 'description': r[3], 'price': r[4], 'category': r[7]} for r in rows]
    return jsonify(jobs)

@app.route('/api/favorites/<int:job_id>', methods=['POST'])
def toggle_favorite(job_id):
    """Добавление/удаление из избранного"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_by_token(token)
    if not user:
        return jsonify({'error': 'Не авторизован'}), 401
    
    conn = sqlite3.connect('app.db')
    c = conn.cursor()
    c.execute('SELECT id FROM favorites WHERE user_id = ? AND job_id = ?', (user['id'], job_id))
    existing = c.fetchone()
    
    if existing:
        c.execute('DELETE FROM favorites WHERE id = ?', (existing[0],))
        action = 'removed'
    else:
        c.execute('INSERT INTO favorites (user_id, job_id) VALUES (?, ?)', (user['id'], job_id))
        action = 'added'
    
    conn.commit()
    conn.close()
    return jsonify({'action': action})

# ==========================================
# СТАТИЧЕСКИЕ ФАЙЛЫ PWA
# ==========================================
@app.route('/manifest.json')
def manifest():
    return send_from_directory('.', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('.', 'sw.js')

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
    <title>Near Gig – Подработки рядом</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#6366F1">
    <link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/1041/1041916.png">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <script src="https://api-maps.yandex.ru/2.1/?apikey=27ec90a8-477d-41ac-a054-ba4bdd3bd265&lang=ru_RU"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        * { -webkit-tap-highlight-color: transparent; }
        body { overscroll-behavior: none; }
        .ymaps-2-1-79-ground-pane { filter: grayscale(0); }
        .tab-active { color: #6366F1; border-bottom: 2px solid #6366F1; }
    </style>
</head>
<body class="bg-white overflow-hidden h-screen">
    <!-- ВЕРХНЯЯ ПАНЕЛЬ -->
    <div id="header" class="fixed top-0 left-0 right-0 z-50 bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <h1 class="text-xl font-bold text-gray-900">Near Gig</h1>
        <div class="flex gap-3">
            <button id="loginBtn" class="text-sm text-indigo-600 font-medium px-3 py-1 rounded-full border border-indigo-200">Войти</button>
            <div id="userMenu" class="hidden relative">
                <button id="profileBtn" class="w-9 h-9 rounded-full bg-gray-200 overflow-hidden">
                    <img id="avatarImg" src="https://cdn-icons-png.flaticon.com/512/149/149071.png" class="w-full h-full object-cover">
                </button>
                <div id="dropdownMenu" class="hidden absolute right-0 top-10 bg-white shadow-lg rounded-lg py-2 w-48 border border-gray-100">
                    <button onclick="showProfile()" class="w-full text-left px-4 py-2 text-sm hover:bg-gray-50">Мой профиль</button>
                    <button onclick="showMyJobs()" class="w-full text-left px-4 py-2 text-sm hover:bg-gray-50">Мои заказы</button>
                    <button onclick="showFavorites()" class="w-full text-left px-4 py-2 text-sm hover:bg-gray-50">Избранное</button>
                    <hr class="my-1">
                    <button onclick="logout()" class="w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-gray-50">Выйти</button>
                </div>
            </div>
        </div>
    </div>

    <!-- КАРТА -->
    <div id="map" class="w-full h-full"></div>

    <!-- НИЖНЕЕ МЕНЮ -->
    <div class="fixed bottom-0 left-0 right-0 z-50 bg-white border-t border-gray-200 px-4 py-2 flex justify-around">
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

    <!-- МОДАЛЬНЫЕ ОКНА -->
    <div id="authModal" class="hidden fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
        <div class="bg-white rounded-2xl p-6 w-full max-w-md">
            <h2 class="text-xl font-bold mb-4 text-center" id="authTitle">Вход</h2>
            <form id="authForm" class="space-y-3">
                <input type="email" id="authEmail" placeholder="Email" class="w-full px-4 py-3 border border-gray-200 rounded-xl" required>
                <input type="password" id="authPassword" placeholder="Пароль" class="w-full px-4 py-3 border border-gray-200 rounded-xl" required>
                <input type="text" id="authName" placeholder="Имя (только для регистрации)" class="w-full px-4 py-3 border border-gray-200 rounded-xl hidden">
                <select id="authRole" class="w-full px-4 py-3 border border-gray-200 rounded-xl hidden">
                    <option value="executor">Исполнитель</option>
                    <option value="customer">Заказчик</option>
                </select>
                <button type="submit" class="w-full bg-indigo-600 text-white py-3 rounded-xl font-medium">Войти</button>
            </form>
            <p class="text-center text-sm mt-3 text-gray-500">
                <span id="authSwitchText">Нет аккаунта?</span>
                <button id="authSwitchBtn" class="text-indigo-600 font-medium">Зарегистрироваться</button>
            </p>
            <button onclick="closeAuth()" class="mt-3 w-full py-2 text-gray-400">Отмена</button>
        </div>
    </div>

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
            <button onclick="closeJobForm()" class="w-full py-2 text-gray-400">Отмена</button>
        </div>
    </div>

    <div id="listModal" class="hidden fixed inset-0 z-50 bg-white overflow-y-auto">
        <div class="p-4">
            <div class="flex justify-between items-center mb-4">
                <h2 class="text-xl font-bold">Задания</h2>
                <button onclick="closeList()" class="text-gray-500 text-2xl">&times;</button>
            </div>
            <div id="jobsList" class="space-y-3"></div>
        </div>
    </div>

    <div id="profileModal" class="hidden fixed inset-0 z-50 bg-white overflow-y-auto">
        <div class="p-4">
            <div class="flex justify-between items-center mb-4">
                <h2 class="text-xl font-bold">Профиль</h2>
                <button onclick="closeProfile()" class="text-gray-500 text-2xl">&times;</button>
            </div>
            <div id="profileContent" class="space-y-4">
                <div class="flex items-center gap-4">
                    <img id="profileAvatar" src="https://cdn-icons-png.flaticon.com/512/149/149071.png" class="w-20 h-20 rounded-full">
                    <div>
                        <h3 id="profileName" class="font-bold text-lg"></h3>
                        <p id="profileRole" class="text-gray-500 text-sm"></p>
                        <p class="text-yellow-500">★ <span id="profileRating"></span></p>
                    </div>
                </div>
                <div class="grid grid-cols-3 gap-3 text-center">
                    <div class="bg-gray-50 rounded-xl p-3"><p id="completedJobs" class="text-2xl font-bold">0</p><p class="text-xs text-gray-500">Выполнено</p></div>
                    <div class="bg-gray-50 rounded-xl p-3"><p id="reviewsCount" class="text-2xl font-bold">0</p><p class="text-xs text-gray-500">Отзывов</p></div>
                    <div class="bg-gray-50 rounded-xl p-3"><p id="userRating" class="text-2xl font-bold">0</p><p class="text-xs text-gray-500">Рейтинг</p></div>
                </div>
                <button onclick="showMyJobs()" class="w-full bg-indigo-50 text-indigo-600 py-3 rounded-xl">Мои заказы</button>
                <button onclick="showFavorites()" class="w-full bg-gray-50 text-gray-700 py-3 rounded-xl">Избранное</button>
            </div>
        </div>
    </div>

    <script>
        // Глобальные переменные
        let myMap, currentUser = null, authToken = null;
        let selectedCoords = null, tempPlacemark = null;
        const YANDEX_GEOCODER_KEY = 'a1072bf1-5f7e-4d8b-b535-a231feb84cf8';

        // Инициализация карты
        ymaps.ready(() => {
            myMap = new ymaps.Map('map', {
                center: [55.7558, 37.6173],
                zoom: 12,
                controls: ['zoomControl', 'typeSelector', 'geolocationControl']
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
            document.getElementById('coordsInfo').textContent = `Координаты: ${coords[0].toFixed(4)}, ${coords[1].toFixed(4)}`;
        }

        function loadJobsOnMap(filters = {}) {
            if (!myMap) return;
            myMap.geoObjects.each(obj => { if (obj !== tempPlacemark) myMap.geoObjects.remove(obj); });
            fetch('/api/jobs?' + new URLSearchParams(filters))
                .then(r => r.json())
                .then(jobs => {
                    jobs.forEach(job => {
                        const pm = new ymaps.Placemark([job.lat, job.lng], {
                            balloonContent: `<b>${job.title}</b><br>${job.description}<br>💰 ${job.price} руб.<br>👤 ${job.author.name} ⭐${job.author.rating}`
                        });
                        myMap.geoObjects.add(pm);
                    });
                });
        }

        // Переключение вкладок
        function switchTab(tab) {
            document.querySelectorAll('[id^="tab"]').forEach(b => b.className = b.className.replace('tab-active text-gray-900', 'text-gray-500'));
            document.getElementById('tab' + tab.charAt(0).toUpperCase() + tab.slice(1)).className += ' tab-active text-gray-900';
            
            if (tab === 'add') {
                if (!currentUser) return openAuth();
                document.getElementById('jobFormModal').classList.remove('hidden');
            } else if (tab === 'list') {
                loadJobsList();
                document.getElementById('listModal').classList.remove('hidden');
            } else if (tab === 'profile') {
                if (!currentUser) return openAuth();
                showProfile();
            }
        }

        function loadJobsList() {
            fetch('/api/jobs')
                .then(r => r.json())
                .then(jobs => {
                    document.getElementById('jobsList').innerHTML = jobs.map(job => `
                        <div class="bg-white border border-gray-100 rounded-xl p-4" onclick="focusOnMap(${job.lat},${job.lng})">
                            <div class="flex justify-between">
                                <h3 class="font-bold">${job.title}</h3>
                                <span class="text-indigo-600 font-bold">${job.price} руб</span>
                            </div>
                            <p class="text-sm text-gray-500 mt-1">${job.description}</p>
                            <div class="flex justify-between mt-2 text-xs text-gray-400">
                                <span>${job.category} · ${job.author.name} ⭐${job.author.rating}</span>
                                ${job.distance ? `<span>${job.distance} км</span>` : ''}
                            </div>
                        </div>
                    `).join('');
                });
        }

        function focusOnMap(lat, lng) {
            document.getElementById('listModal').classList.add('hidden');
            myMap.setCenter([lat, lng], 15);
            switchTab('map');
        }

        function closeList() {
            document.getElementById('listModal').classList.add('hidden');
        }

        function closeProfile() {
            document.getElementById('profileModal').classList.add('hidden');
        }

        function closeJobForm() {
            document.getElementById('jobFormModal').classList.add('hidden');
            if (tempPlacemark) { myMap.geoObjects.remove(tempPlacemark); tempPlacemark = null; }
        }

        // Аутентификация
        function openAuth() {
            document.getElementById('authModal').classList.remove('hidden');
        }

        function closeAuth() {
            document.getElementById('authModal').classList.add('hidden');
        }

        document.getElementById('authSwitchBtn').addEventListener('click', () => {
            const isLogin = document.getElementById('authTitle').textContent === 'Вход';
            document.getElementById('authTitle').textContent = isLogin ? 'Регистрация' : 'Вход';
            document.getElementById('authName').classList.toggle('hidden', isLogin);
            document.getElementById('authRole').classList.toggle('hidden', isLogin);
            document.getElementById('authSwitchText').textContent = isLogin ? 'Есть аккаунт?' : 'Нет аккаунта?';
            document.getElementById('authSwitchBtn').textContent = isLogin ? 'Войти' : 'Зарегистрироваться';
        });

        document.getElementById('authForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const isLogin = document.getElementById('authTitle').textContent === 'Вход';
            const email = document.getElementById('authEmail').value;
            const password = document.getElementById('authPassword').value;
            
            const url = isLogin ? '/api/login' : '/api/register';
            const body = { email, password };
            if (!isLogin) {
                body.name = document.getElementById('authName').value;
                body.role = document.getElementById('authRole').value;
            }
            
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
            } else {
                alert(data.error || 'Ошибка');
            }
        });

        async function logout() {
            await fetch('/api/logout', { method: 'POST', headers: { 'Authorization': `Bearer ${authToken}` } });
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
            document.getElementById('profileName').textContent = currentUser.name;
            document.getElementById('profileRole').textContent = currentUser.role === 'executor' ? 'Исполнитель' : 'Заказчик';
            document.getElementById('profileRating').textContent = currentUser.rating;
            document.getElementById('completedJobs').textContent = currentUser.completed_jobs;
            document.getElementById('reviewsCount').textContent = currentUser.reviews_count;
            document.getElementById('userRating').textContent = currentUser.rating;
            document.getElementById('profileAvatar').src = currentUser.avatar_url || 'https://cdn-icons-png.flaticon.com/512/149/149071.png';
            document.getElementById('profileModal').classList.remove('hidden');
        }

        function showMyJobs() {
            // Заглушка
            alert('Мои заказы — в разработке');
        }

        function showFavorites() {
            // Заглушка
            alert('Избранное — в разработке');
        }

        // Создание задания
        async function createJob() {
            if (!currentUser) return openAuth();
            const title = document.getElementById('jobTitle').value;
            const desc = document.getElementById('jobDesc').value;
            const price = document.getElementById('jobPrice').value;
            const cat = document.getElementById('jobCategory').value;
            
            if (!title || !price || !selectedCoords) {
                alert('Заполните все поля и выберите место на карте');
                return;
            }
            
            const res = await fetch('/api/jobs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify({
                    title, description: desc, price: parseFloat(price),
                    lat: selectedCoords[0], lng: selectedCoords[1], category: cat
                })
            });
            
            if (res.ok) {
                alert('Задание опубликовано!');
                closeJobForm();
                loadJobsOnMap();
            }
        }

        // Инициализация
        const savedToken = localStorage.getItem('token');
        if (savedToken) {
            fetch('/api/me', { headers: { 'Authorization': `Bearer ${savedToken}` } })
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
