import sqlite3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2

from flask import Flask, request, jsonify


# ============================================================
# CONFIG
# ============================================================

APP_URL = os.environ.get(
    "APP_URL",
    "https://near-gig.onrender.com"
)

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    secrets.token_hex(32)
)

YANDEX_MAPS_API_KEY = os.environ.get(
    "YANDEX_MAPS_API_KEY",
    "27ec90a8-477d-41ac-a054-ba4bdd3bd265"
)

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")
)

DEFAULT_AVATAR = (
    "https://cdn-icons-png.flaticon.com/512/149/149071.png"
)

DEFAULT_APP_ICON = (
    "https://cdn-icons-png.flaticon.com/512/1041/1041916.png"
)


app = Flask(__name__)
app.secret_key = SECRET_KEY


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            role TEXT DEFAULT 'executor',
            avatar_url TEXT DEFAULT '',
            rating REAL DEFAULT 0,
            reviews_count INTEGER DEFAULT 0,
            completed_jobs INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            lat REAL,
            lng REAL,
            category TEXT DEFAULT 'Другое',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT,
            views INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            job_id INTEGER,
            rating INTEGER CHECK(rating >= 1 AND rating <= 5),
            comment TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(to_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            UNIQUE(user_id, job_id)
        )
    """)

    # Индексы для более быстрой работы
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_status
        ON jobs(status)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_user
        ON jobs(user_id)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_responses_job
        ON responses(job_id)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_favorites_user
        ON favorites(user_id)
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# HELPERS
# ============================================================

def hash_password(password):
    return hashlib.sha256(
        password.encode("utf-8")
    ).hexdigest()


def generate_token():
    return secrets.token_hex(32)


def get_token():
    return request.headers.get(
        "Authorization",
        ""
    ).replace("Bearer ", "").strip()


def get_user_by_token(token):
    if not token:
        return None

    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT users.*
        FROM users
        JOIN sessions
            ON users.id = sessions.user_id
        WHERE sessions.token = ?
          AND sessions.expires_at > datetime('now')
    """, (token,))

    user = c.fetchone()
    conn.close()

    if user:
        return dict(user)

    return None


def require_user():
    user = get_user_by_token(get_token())
    return user


def haversine(lat1, lng1, lat2, lng2):
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return None

    R = 6371.0

    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlng / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )

    return R * c


def user_public(user):
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "phone": user["phone"],
        "role": user["role"],
        "avatar_url": user["avatar_url"] or DEFAULT_AVATAR,
        "rating": user["rating"],
        "reviews_count": user["reviews_count"],
        "completed_jobs": user["completed_jobs"],
        "created_at": user["created_at"]
    }


# ============================================================
# AUTH
# ============================================================

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    name = str(data.get("name", "")).strip()
    role = str(data.get("role", "executor")).strip()

    if role not in ("executor", "customer"):
        role = "executor"

    if not email or not password or not name:
        return jsonify({
            "error": "Заполните все обязательные поля"
        }), 400

    if len(password) < 6:
        return jsonify({
            "error": "Пароль должен содержать минимум 6 символов"
        }), 400

    if "@" not in email or "." not in email:
        return jsonify({
            "error": "Введите корректный email"
        }), 400

    conn = get_db()
    c = conn.cursor()

    c.execute(
        "SELECT id FROM users WHERE email = ?",
        (email,)
    )

    if c.fetchone():
        conn.close()
        return jsonify({
            "error": "Этот email уже зарегистрирован"
        }), 409

    password_hash = hash_password(password)

    c.execute("""
        INSERT INTO users (
            email,
            password_hash,
            name,
            role,
            avatar_url
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        email,
        password_hash,
        name,
        role,
        DEFAULT_AVATAR
    ))

    user_id = c.lastrowid

    token = generate_token()

    expires_at = (
        datetime.utcnow()
        + timedelta(days=30)
    ).isoformat()

    c.execute("""
        INSERT INTO sessions (
            user_id,
            token,
            expires_at
        )
        VALUES (?, ?, ?)
    """, (
        user_id,
        token,
        expires_at
    ))

    conn.commit()

    c.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    )

    user = c.fetchone()

    conn.close()

    return jsonify({
        "token": token,
        "user": user_public(user)
    }), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    email = str(
        data.get("email", "")
    ).strip().lower()

    password = str(
        data.get("password", "")
    )

    if not email or not password:
        return jsonify({
            "error": "Введите email и пароль"
        }), 400

    conn = get_db()
    c = conn.cursor()

    c.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    )

    user = c.fetchone()

    if (
        not user
        or user["password_hash"] != hash_password(password)
    ):
        conn.close()

        return jsonify({
            "error": "Неверный email или пароль"
        }), 401

    token = generate_token()

    expires_at = (
        datetime.utcnow()
        + timedelta(days=30)
    ).isoformat()

    c.execute("""
        INSERT INTO sessions (
            user_id,
            token,
            expires_at
        )
        VALUES (?, ?, ?)
    """, (
        user["id"],
        token,
        expires_at
    ))

    c.execute("""
        UPDATE users
        SET last_login = datetime('now')
        WHERE id = ?
    """, (user["id"],))

    conn.commit()
    conn.close()

    return jsonify({
        "token": token,
        "user": user_public(user)
    })


@app.route("/api/logout", methods=["POST"])
def logout():
    token = get_token()

    if token:
        conn = get_db()

        conn.execute(
            "DELETE FROM sessions WHERE token = ?",
            (token,)
        )

        conn.commit()
        conn.close()

    return jsonify({
        "status": "ok"
    })


@app.route("/api/me", methods=["GET"])
def me():
    user = require_user()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    return jsonify(
        user_public(user)
    )


# ============================================================
# JOBS
# ============================================================

@app.route("/api/jobs", methods=["GET"])
def get_jobs():
    category = request.args.get("category")
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius = request.args.get("radius", type=float)
    max_price = request.args.get("max_price", type=float)
    user_id = request.args.get("user_id", type=int)

    status = request.args.get(
        "status",
        "active"
    )

    conn = get_db()
    c = conn.cursor()

    query = """
        SELECT
            jobs.*,
            users.name AS author_name,
            users.rating AS author_rating,
            users.avatar_url AS author_avatar,
            users.id AS author_id
        FROM jobs
        JOIN users
            ON jobs.user_id = users.id
        WHERE 1=1
    """

    params = []

    if status:
        query += " AND jobs.status = ?"
        params.append(status)

    if category:
        query += " AND jobs.category = ?"
        params.append(category)

    if max_price is not None:
        query += " AND jobs.price <= ?"
        params.append(max_price)

    if user_id:
        query += " AND jobs.user_id = ?"
        params.append(user_id)

    query += """
        ORDER BY jobs.created_at DESC
    """

    c.execute(query, params)

    rows = c.fetchall()
    conn.close()

    jobs = []

    for row in rows:
        job = dict(row)

        job["author"] = {
            "id": row["author_id"],
            "name": row["author_name"],
            "rating": row["author_rating"],
            "avatar": row["author_avatar"] or DEFAULT_AVATAR
        }

        if (
            lat is not None
            and lng is not None
            and radius is not None
        ):
            distance = haversine(
                lat,
                lng,
                job["lat"],
                job["lng"]
            )

            if distance is None or distance > radius:
                continue

            job["distance"] = round(
                distance,
                2
            )

        jobs.append(job)

    return jsonify(jobs)


@app.route("/api/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT
            jobs.*,
            users.name AS author_name,
            users.rating AS author_rating,
            users.avatar_url AS author_avatar,
            users.id AS author_id
        FROM jobs
        JOIN users
            ON jobs.user_id = users.id
        WHERE jobs.id = ?
    """, (job_id,))

    job = c.fetchone()

    if not job:
        conn.close()

        return jsonify({
            "error": "Задание не найдено"
        }), 404

    c.execute("""
        SELECT
            responses.*,
            users.name,
            users.avatar_url
        FROM responses
        JOIN users
            ON responses.user_id = users.id
        WHERE responses.job_id = ?
        ORDER BY responses.created_at DESC
    """, (job_id,))

    responses = []

    for response in c.fetchall():
        item = dict(response)
        item["avatar_url"] = (
            item["avatar_url"]
            or DEFAULT_AVATAR
        )
        responses.append(item)

    c.execute("""
        UPDATE jobs
        SET views = views + 1
        WHERE id = ?
    """, (job_id,))

    conn.commit()
    conn.close()

    result = dict(job)

    result["author"] = {
        "id": job["author_id"],
        "name": job["author_name"],
        "rating": job["author_rating"],
        "avatar": (
            job["author_avatar"]
            or DEFAULT_AVATAR
        )
    }

    result["responses"] = responses

    return jsonify(result)


@app.route("/api/jobs", methods=["POST"])
def create_job():
    user = require_user()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    data = request.get_json(silent=True) or {}

    title = str(
        data.get("title", "")
    ).strip()

    description = str(
        data.get("description", "")
    ).strip()

    price = data.get("price")
    lat = data.get("lat")
    lng = data.get("lng")

    category = str(
        data.get("category", "Другое")
    ).strip()

    if not title:
        return jsonify({
            "error": "Введите название задания"
        }), 400

    try:
        price = float(price)
    except (TypeError, ValueError):
        return jsonify({
            "error": "Некорректная цена"
        }), 400

    if price <= 0:
        return jsonify({
            "error": "Цена должна быть больше 0"
        }), 400

    if lat is None or lng is None:
        return jsonify({
            "error": "Выберите место на карте"
        }), 400

    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return jsonify({
            "error": "Некорректные координаты"
        }), 400

    expires_at = (
        datetime.utcnow()
        + timedelta(days=30)
    ).isoformat()

    conn = get_db()

    c = conn.cursor()

    c.execute("""
        INSERT INTO jobs (
            user_id,
            title,
            description,
            price,
            lat,
            lng,
            category,
            expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user["id"],
        title,
        description,
        price,
        lat,
        lng,
        category,
        expires_at
    ))

    job_id = c.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "job_id": job_id
    }), 201


# ============================================================
# RESPONSES
# ============================================================

@app.route(
    "/api/jobs/<int:job_id>/respond",
    methods=["POST"]
)
def respond_to_job(job_id):
    user = require_user()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    data = request.get_json(silent=True) or {}

    message = str(
        data.get("message", "")
    ).strip()

    conn = get_db()
    c = conn.cursor()

    c.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,)
    )

    job = c.fetchone()

    if not job:
        conn.close()

        return jsonify({
            "error": "Задание не найдено"
        }), 404

    if job["user_id"] == user["id"]:
        conn.close()

        return jsonify({
            "error": "Нельзя откликнуться на своё задание"
        }), 400

    c.execute("""
        SELECT id
        FROM responses
        WHERE job_id = ?
          AND user_id = ?
    """, (
        job_id,
        user["id"]
    ))

    if c.fetchone():
        conn.close()

        return jsonify({
            "error": "Вы уже откликались на это задание"
        }), 409

    c.execute("""
        INSERT INTO responses (
            job_id,
            user_id,
            message
        )
        VALUES (?, ?, ?)
    """, (
        job_id,
        user["id"],
        message
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok"
    }), 201


# ============================================================
# FAVORITES
# ============================================================

@app.route("/api/favorites", methods=["GET"])
def get_favorites():
    user = require_user()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    conn = get_db()

    rows = conn.execute("""
        SELECT
            jobs.*,
            users.name AS author_name,
            users.rating AS author_rating,
            users.avatar_url AS author_avatar
        FROM favorites
        JOIN jobs
            ON favorites.job_id = jobs.id
        JOIN users
            ON jobs.user_id = users.id
        WHERE favorites.user_id = ?
        ORDER BY favorites.created_at DESC
    """, (user["id"],)).fetchall()

    conn.close()

    result = []

    for row in rows:
        item = dict(row)

        item["author"] = {
            "name": row["author_name"],
            "rating": row["author_rating"],
            "avatar": (
                row["author_avatar"]
                or DEFAULT_AVATAR
            )
        }

        result.append(item)

    return jsonify(result)


@app.route(
    "/api/favorites/<int:job_id>",
    methods=["POST"]
)
def toggle_favorite(job_id):
    user = require_user()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    conn = get_db()

    c = conn.cursor()

    c.execute("""
        SELECT id
        FROM favorites
        WHERE user_id = ?
          AND job_id = ?
    """, (
        user["id"],
        job_id
    ))

    existing = c.fetchone()

    if existing:
        c.execute(
            "DELETE FROM favorites WHERE id = ?",
            (existing["id"],)
        )

        action = "removed"

    else:
        c.execute("""
            INSERT INTO favorites (
                user_id,
                job_id
            )
            VALUES (?, ?)
        """, (
            user["id"],
            job_id
        ))

        action = "added"

    conn.commit()
    conn.close()

    return jsonify({
        "action": action
    })


# ============================================================
# PWA
# ============================================================

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Near Gig",
        "short_name": "Near Gig",
        "description": "Подработка рядом с вами",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0d0f12",
        "theme_color": "#111318",
        "orientation": "portrait",
        "icons": [
            {
                "src": DEFAULT_APP_ICON,
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    })


@app.route("/sw.js")
def service_worker():
    return """
self.addEventListener("install", event => {
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(
        self.clients.claim()
    );
});

self.addEventListener("fetch", event => {
    event.respondWith(
        fetch(event.request).catch(() => {
            return new Response(
                "Оффлайн",
                {
                    status: 503,
                    headers: {
                        "Content-Type": "text/plain"
                    }
                }
            );
        })
    );
});
"""


# ============================================================
# FRONTEND
# ============================================================

@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="ru">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,
             initial-scale=1.0,
             maximum-scale=1.0,
             user-scalable=no,
             viewport-fit=cover"
>

<meta
    name="theme-color"
    content="#111318"
>

<meta
    name="mobile-web-app-capable"
    content="yes"
>

<meta
    name="apple-mobile-web-app-capable"
    content="yes"
>

<meta
    name="apple-mobile-web-app-status-bar-style"
    content="black-translucent"
>

<title>Near Gig</title>

<link
    rel="manifest"
    href="/manifest.json"
>

<link
    rel="apple-touch-icon"
    href="https://cdn-icons-png.flaticon.com/512/1041/1041916.png"
>

<script>
const YANDEX_MAPS_API_KEY = "__YANDEX_MAPS_API_KEY__";
</script>

<script
    src="https://api-maps.yandex.ru/2.1/?apikey=__YANDEX_MAPS_API_KEY__&lang=ru_RU">
</script>

<script
    src="https://cdn.tailwindcss.com">
</script>


<style>

/* ==========================================================
   ROOT
========================================================== */

:root {
    --bg: #f5f6f8;
    --surface: #ffffff;
    --surface-2: #f0f1f4;
    --text: #181a1f;
    --text-secondary: #666b76;
    --text-muted: #969ba6;
    --border: #e5e7eb;
    --accent: #6366f1;
    --accent-soft: #eef0ff;
    --success: #35a46b;
    --danger: #c85b64;
    --shadow: 0 10px 30px rgba(0,0,0,.08);
}

html.dark {
    --bg: #0d0f12;
    --surface: #15181d;
    --surface-2: #1c2026;
    --text: #e4e6ea;
    --text-secondary: #a4a8b1;
    --text-muted: #777c86;
    --border: #282c33;
    --accent: #8588b8;
    --accent-soft: #242632;
    --success: #5caa83;
    --danger: #c67880;
    --shadow: 0 14px 35px rgba(0,0,0,.28);
}


/* ==========================================================
   BASE
========================================================== */

* {
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}

html,
body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        Helvetica,
        Arial,
        sans-serif;
    background: var(--bg);
    color: var(--text);
}

body {
    overscroll-behavior: none;
}

button,
input,
textarea,
select {
    font: inherit;
}

button {
    cursor: pointer;
}

input,
textarea,
select {
    outline: none;
}

::selection {
    background: var(--accent);
    color: white;
}


/* ==========================================================
   APP
========================================================== */

#app {
    width: 100%;
    height: 100%;
    position: relative;
    overflow: hidden;
}

#map {
    position: absolute;
    inset: 0;
}


/* ==========================================================
   HEADER
========================================================== */

.app-header {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;

    z-index: 30;

    padding:
        max(10px, env(safe-area-inset-top))
        14px
        10px
        14px;

    pointer-events: none;
}

.header-inner {
    height: 54px;

    display: flex;
    align-items: center;
    justify-content: space-between;

    padding: 0 5px 0 13px;

    background: rgba(255,255,255,.94);

    border: 1px solid rgba(0,0,0,.05);

    border-radius: 17px;

    box-shadow:
        0 5px 20px rgba(0,0,0,.10);

    backdrop-filter: blur(18px);

    pointer-events: auto;
}

.dark .header-inner {
    background: rgba(21,24,29,.94);
    border-color: rgba(255,255,255,.05);
    box-shadow:
        0 8px 25px rgba(0,0,0,.28);
}

.logo {
    display: flex;
    align-items: center;
    gap: 9px;

    font-size: 18px;
    font-weight: 750;
    letter-spacing: -.4px;
}

.logo-dot {
    width: 29px;
    height: 29px;

    display: flex;
    align-items: center;
    justify-content: center;

    border-radius: 9px;

    background: var(--accent);
    color: white;

    font-size: 14px;
    font-weight: 800;
}

.login-button {
    border: 0;

    background: var(--accent-soft);
    color: var(--accent);

    padding: 9px 15px;

    border-radius: 11px;

    font-size: 14px;
    font-weight: 650;
}

.dark .login-button {
    color: #c1c3d9;
}


/* ==========================================================
   PROFILE
========================================================== */

.profile-button {
    width: 38px;
    height: 38px;

    border: 0;
    padding: 0;

    overflow: hidden;

    border-radius: 50%;

    background: var(--surface-2);
}

.profile-button img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.profile-menu {
    position: absolute;

    right: 5px;
    top: 48px;

    width: 210px;

    background: var(--surface);

    border: 1px solid var(--border);

    border-radius: 16px;

    box-shadow: var(--shadow);

    padding: 7px;

    overflow: hidden;
}

.profile-menu button {
    width: 100%;

    border: 0;
    background: transparent;

    color: var(--text);

    text-align: left;

    padding: 12px;

    border-radius: 10px;

    font-size: 14px;
}

.profile-menu button:active {
    background: var(--surface-2);
}


/* ==========================================================
   MAP BUTTON
========================================================== */

.locate-button {
    position: fixed;

    right: 14px;

    bottom: calc(
        88px + env(safe-area-inset-bottom)
    );

    z-index: 20;

    width: 46px;
    height: 46px;

    border: 1px solid var(--border);

    border-radius: 14px;

    background: var(--surface);

    color: var(--text);

    box-shadow: var(--shadow);

    font-size: 20px;
}


/* ==========================================================
   BOTTOM NAVIGATION
========================================================== */

.bottom-nav {
    position: fixed;

    left: 0;
    right: 0;
    bottom: 0;

    z-index: 40;

    padding:
        7px
        10px
        max(8px, env(safe-area-inset-bottom))
        10px;

    background: rgba(255,255,255,.96);

    border-top: 1px solid var(--border);

    backdrop-filter: blur(18px);
}

.dark .bottom-nav {
    background: rgba(17,19,24,.96);
}

.bottom-nav-inner {
    max-width: 520px;

    margin: auto;

    display: grid;
    grid-template-columns: repeat(4, 1fr);

    gap: 4px;
}

.nav-button {
    min-height: 55px;

    border: 0;
    background: transparent;

    color: var(--text-muted);

    display: flex;
    flex-direction: column;

    align-items: center;
    justify-content: center;

    gap: 3px;

    border-radius: 13px;

    font-size: 11px;
    font-weight: 600;

    transition:
        background .15s ease,
        color .15s ease;
}

.nav-button svg {
    width: 22px;
    height: 22px;
}

.nav-button.active {
    color: var(--accent);
    background: var(--accent-soft);
}

.dark .nav-button.active {
    color: #b9bbd4;
}


/* ==========================================================
   MODALS
========================================================== */

.modal-overlay {
    position: fixed;

    inset: 0;

    z-index: 100;

    display: flex;

    align-items: flex-end;
    justify-content: center;

    background: rgba(0,0,0,.48);

    padding: 0;
}

.modal-overlay.center {
    align-items: center;
    padding: 16px;
}

.modal-sheet {
    width: 100%;
    max-width: 560px;

    max-height: 92vh;

    overflow-y: auto;

    background: var(--surface);

    color: var(--text);

    border-radius:
        24px
        24px
        0
        0;

    box-shadow:
        0 -15px 45px rgba(0,0,0,.20);

    padding:
        18px
        16px
        max(22px, env(safe-area-inset-bottom));

    animation:
        sheetUp .2s ease;
}

.center .modal-sheet {
    border-radius: 22px;

    padding-bottom: 20px;

    animation:
        modalIn .18s ease;
}

@keyframes sheetUp {
    from {
        transform: translateY(20px);
        opacity: 0;
    }

    to {
        transform: translateY(0);
        opacity: 1;
    }
}

@keyframes modalIn {
    from {
        transform: scale(.98);
        opacity: 0;
    }

    to {
        transform: scale(1);
        opacity: 1;
    }
}

.sheet-handle {
    width: 38px;
    height: 4px;

    background: var(--border);

    border-radius: 10px;

    margin: 0 auto 16px;
}


/* ==========================================================
   TYPOGRAPHY
========================================================== */

.modal-title {
    font-size: 21px;
    font-weight: 750;

    letter-spacing: -.4px;

    margin: 0 0 18px;
}

.section-title {
    font-size: 16px;
    font-weight: 700;

    margin: 20px 0 10px;
}


/* ==========================================================
   FORM
========================================================== */

.form-group {
    margin-bottom: 11px;
}

.form-label {
    display: block;

    margin: 0 0 6px 3px;

    font-size: 12px;
    font-weight: 600;

    color: var(--text-secondary);
}

.form-control {
    width: 100%;

    min-height: 48px;

    border:
        1px solid var(--border);

    border-radius: 13px;

    background: var(--surface-2);

    color: var(--text);

    padding: 0 14px;

    font-size: 15px;

    transition:
        border-color .15s,
        box-shadow .15s;
}

textarea.form-control {
    padding-top: 12px;
    padding-bottom: 12px;
    resize: vertical;
    min-height: 92px;
}

.form-control:focus {
    border-color: var(--accent);

    box-shadow:
        0 0 0 3px
        rgba(99,102,241,.10);
}

.dark .form-control:focus {
    box-shadow:
        0 0 0 3px
        rgba(150,150,180,.08);
}


/* ==========================================================
   BUTTONS
========================================================== */

.primary-button,
.secondary-button,
.danger-button {
    width: 100%;

    min-height: 48px;

    border: 0;

    border-radius: 13px;

    font-size: 15px;
    font-weight: 700;

    transition:
        transform .1s,
        opacity .1s;
}

.primary-button {
    background: var(--accent);
    color: white;
}

.dark .primary-button {
    background: #777a9e;
    color: #f4f4f6;
}

.secondary-button {
    background: var(--surface-2);
    color: var(--text);
}

.danger-button {
    background: rgba(200,91,100,.10);
    color: var(--danger);
}

.primary-button:active,
.secondary-button:active,
.danger-button:active {
    transform: scale(.98);
}


/* ==========================================================
   JOB CARDS
========================================================== */

.job-list {
    display: flex;
    flex-direction: column;
    gap: 9px;
}

.job-card {
    padding: 15px;

    border:
        1px solid var(--border);

    background: var(--surface);

    border-radius: 16px;

    box-shadow:
        0 2px 10px rgba(0,0,0,.025);

    transition:
        transform .12s,
        border-color .12s;
}

.job-card:active {
    transform: scale(.99);
}

.job-card-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;

    gap: 12px;
}

.job-title {
    margin: 0;

    font-size: 15px;
    font-weight: 700;

    line-height: 1.3;
}

.job-price {
    white-space: nowrap;

    font-size: 15px;
    font-weight: 750;

    color: var(--accent);
}

.dark .job-price {
    color: #b5b7d1;
}

.job-description {
    color: var(--text-secondary);

    font-size: 13px;

    line-height: 1.45;

    margin-top: 7px;
}

.job-meta {
    display: flex;
    flex-wrap: wrap;

    gap: 6px;

    margin-top: 11px;
}

.meta-chip {
    padding: 5px 8px;

    border-radius: 8px;

    background: var(--surface-2);

    color: var(--text-secondary);

    font-size: 11px;
}


/* ==========================================================
   PROFILE
========================================================== */

.profile-card {
    display: flex;
    align-items: center;

    gap: 13px;

    padding: 15px;

    border-radius: 17px;

    background: var(--surface-2);

    margin-bottom: 12px;
}

.profile-avatar {
    width: 62px;
    height: 62px;

    border-radius: 50%;

    object-fit: cover;
}

.profile-name {
    font-size: 18px;
    font-weight: 750;
}

.profile-email {
    color: var(--text-muted);

    font-size: 12px;

    margin-top: 3px;
}

.stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);

    gap: 7px;

    margin-bottom: 14px;
}

.stat {
    background: var(--surface-2);

    border-radius: 13px;

    padding: 11px 6px;

    text-align: center;
}

.stat-value {
    font-weight: 750;
    font-size: 16px;
}

.stat-label {
    margin-top: 2px;

    color: var(--text-muted);

    font-size: 10px;
}


/* ==========================================================
   SETTINGS
========================================================== */

.settings-section {
    margin-bottom: 14px;

    border:
        1px solid var(--border);

    border-radius: 16px;

    overflow: hidden;

    background: var(--surface);
}

.settings-heading {
    padding: 12px 14px 7px;

    color: var(--text-muted);

    font-size: 11px;
    font-weight: 700;

    text-transform: uppercase;

    letter-spacing: .5px;
}

.settings-item {
    min-height: 58px;

    display: flex;

    align-items: center;
    justify-content: space-between;

    gap: 15px;

    padding: 10px 14px;

    border-top: 1px solid var(--border);
}

.settings-title {
    font-size: 14px;
    font-weight: 600;
}

.settings-subtitle {
    color: var(--text-muted);

    font-size: 11px;

    margin-top: 2px;
}


/* ==========================================================
   TOGGLE
========================================================== */

.toggle {
    position: relative;

    width: 48px;
    height: 29px;

    flex-shrink: 0;
}

.toggle input {
    opacity: 0;
    width: 0;
    height: 0;
}

.toggle-slider {
    position: absolute;

    inset: 0;

    border-radius: 30px;

    background: #d7d9dd;

    transition: .2s;
}

.toggle-slider::before {
    content: "";

    position: absolute;

    width: 25px;
    height: 25px;

    left: 2px;
    top: 2px;

    border-radius: 50%;

    background: white;

    box-shadow:
        0 1px 4px rgba(0,0,0,.20);

    transition: .2s;
}

.toggle input:checked + .toggle-slider {
    background: var(--accent);
}

.toggle input:checked + .toggle-slider::before {
    transform: translateX(19px);
}


/* ==========================================================
   AUTH
========================================================== */

.auth-switch {
    text-align: center;

    color: var(--text-secondary);

    font-size: 13px;

    margin-top: 14px;
}

.auth-switch button {
    border: 0;

    background: transparent;

    color: var(--accent);

    font-weight: 700;
}


/* ==========================================================
   EMPTY
========================================================== */

.empty-state {
    text-align: center;

    padding: 40px 20px;

    color: var(--text-muted);
}

.empty-icon {
    font-size: 35px;

    margin-bottom: 10px;

    opacity: .65;
}


/* ==========================================================
   LOCATION INFO
========================================================== */

.location-info {
    display: flex;
    align-items: center;

    gap: 8px;

    padding: 10px 12px;

    border-radius: 12px;

    background: var(--surface-2);

    color: var(--text-secondary);

    font-size: 12px;

    margin-bottom: 12px;
}


/* ==========================================================
   CLOSE BUTTON
========================================================== */

.close-button {
    width: 36px;
    height: 36px;

    border: 0;

    border-radius: 50%;

    background: var(--surface-2);

    color: var(--text-secondary);

    font-size: 20px;

    display: flex;
    align-items: center;
    justify-content: center;
}


/* ==========================================================
   YANDEX MAP
========================================================== */

.ymaps-2-1-79-controls__control {
    border-radius: 10px !important;
}

.ymaps-2-1-79-gotoymaps {
    display: none !important;
}


/* ==========================================================
   MOBILE
========================================================== */

@media (min-width: 700px) {

    .bottom-nav {
        left: 50%;
        right: auto;
        width: 540px;
        transform: translateX(-50%);
        border: 0;
        background: transparent;
    }

    .bottom-nav-inner {
        padding: 8px;

        background: rgba(255,255,255,.96);

        border:
            1px solid var(--border);

        border-radius: 18px;

        box-shadow: var(--shadow);
    }

    .dark .bottom-nav-inner {
        background: rgba(21,24,29,.96);
    }

    .modal-overlay {
        align-items: center;
        padding: 20px;
    }

    .modal-sheet {
        border-radius: 22px;
        padding: 22px;
    }
}


/* ==========================================================
   SCROLLBAR
========================================================== */

::-webkit-scrollbar {
    width: 4px;
}

::-webkit-scrollbar-track {
    background: transparent;
}

::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 20px;
}


/* ==========================================================
   HIDDEN
========================================================== */

.hidden {
    display: none !important;
}

</style>

</head>


<body>

<div id="app">


<!-- ========================================================
     HEADER
========================================================= -->

<header class="app-header">

    <div class="header-inner">

        <div class="logo">

            <div class="logo-dot">
                NG
            </div>

            <span>Near Gig</span>

        </div>


        <button
            id="loginBtn"
            class="login-button"
            onclick="openAuth()"
        >
            Войти
        </button>


        <div
            id="userMenu"
            class="hidden"
            style="position:relative"
        >

            <button
                id="profileBtn"
                class="profile-button"
            >

                <img
                    id="avatarImg"
                    src="https://cdn-icons-png.flaticon.com/512/149/149071.png"
                    alt=""
                >

            </button>


            <div
                id="dropdownMenu"
                class="profile-menu hidden"
            >

                <button onclick="showProfile()">
                    Профиль
                </button>

                <button onclick="showMyJobs()">
                    Мои задания
                </button>

                <button onclick="showFavorites()">
                    Избранное
                </button>

                <button onclick="showSettings()">
                    Настройки
                </button>

                <button
                    onclick="logout()"
                    style="color:var(--danger)"
                >
                    Выйти
                </button>

            </div>

        </div>

    </div>

</header>


<!-- ========================================================
     MAP
========================================================= -->

<div id="map"></div>


<button
    id="manualLocateBtn"
    class="locate-button"
    title="Моё местоположение"
>
    ⌖
</button>


<!-- ========================================================
     BOTTOM NAV
========================================================= -->

<nav class="bottom-nav">

    <div class="bottom-nav-inner">

        <button
            id="tabMap"
            class="nav-button active"
            onclick="switchTab('map')"
        >

            <svg
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                viewBox="0 0 24 24"
            >
                <path
                    d="M12 21s7-7.1 7-12A7 7 0 1 0 5 9c0 4.9 7 12 7 12Z"
                />
                <circle cx="12" cy="9" r="2.3"/>
            </svg>

            Карта

        </button>


        <button
            id="tabAdd"
            class="nav-button"
            onclick="switchTab('add')"
        >

            <svg
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                viewBox="0 0 24 24"
            >
                <path
                    d="M12 5v14M5 12h14"
                />
            </svg>

            Создать

        </button>


        <button
            id="tabList"
            class="nav-button"
            onclick="switchTab('list')"
        >

            <svg
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                viewBox="0 0 24 24"
            >
                <path d="M8 6h13M8 12h13M8 18h13"/>
                <path d="M3 6h.01M3 12h.01M3 18h.01"/>
            </svg>

            Задания

        </button>


        <button
            id="tabProfile"
            class="nav-button"
            onclick="switchTab('profile')"
        >

            <svg
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                viewBox="0 0 24 24"
            >
                <circle cx="12" cy="8" r="3"/>
                <path
                    d="M5 20c.8-3.3 3.2-5 7-5s6.2 1.7 7 5"
                />
            </svg>

            Профиль

        </button>

    </div>

</nav>


<!-- ========================================================
     AUTH MODAL
========================================================= -->

<div
    id="authModal"
    class="modal-overlay center hidden"
>

    <div class="modal-sheet">

        <div
            class="flex justify-end"
            style="margin-bottom:4px"
        >

            <button
                class="close-button"
                onclick="closeAuth()"
            >
                ×
            </button>

        </div>


        <h2
            id="authTitle"
            class="modal-title"
        >
            Вход
        </h2>


        <form
            id="authForm"
        >

            <div class="form-group">

                <label class="form-label">
                    Email
                </label>

                <input
                    type="email"
                    id="authEmail"
                    class="form-control"
                    placeholder="you@example.com"
                    autocomplete="email"
                    required
                >

            </div>


            <div
                id="authNameGroup"
                class="form-group hidden"
            >

                <label class="form-label">
                    Ваше имя
                </label>

                <input
                    type="text"
                    id="authName"
                    class="form-control"
                    placeholder="Как к вам обращаться?"
                    autocomplete="name"
                >

            </div>


            <div class="form-group">

                <label class="form-label">
                    Пароль
                </label>

                <input
                    type="password"
                    id="authPassword"
                    class="form-control"
                    placeholder="Минимум 6 символов"
                    autocomplete="current-password"
                    required
                >

            </div>


            <button
                type="submit"
                id="authSubmit"
                class="primary-button"
            >
                Войти
            </button>

        </form>


        <div class="auth-switch">

            <span id="authSwitchText">
                Нет аккаунта?
            </span>

            <button
                id="authSwitchBtn"
            >
                Зарегистрироваться
            </button>

        </div>

    </div>

</div>


<!-- ========================================================
     CREATE JOB
========================================================= -->

<div
    id="jobFormModal"
    class="modal-overlay hidden"
>

    <div class="modal-sheet">

        <div class="sheet-handle"></div>

        <div
            style="
                display:flex;
                justify-content:space-between;
                align-items:center;
            "
        >

            <h2 class="modal-title">
                Новая подработка
            </h2>

            <button
                class="close-button"
                onclick="closeJobForm()"
            >
                ×
            </button>

        </div>


        <div class="form-group">

            <label class="form-label">
                Что нужно сделать?
            </label>

            <input
                id="jobTitle"
                class="form-control"
                placeholder="Например: доставить документы"
                maxlength="100"
            >

        </div>


        <div class="form-group">

            <label class="form-label">
                Описание
            </label>

            <textarea
                id="jobDesc"
                class="form-control"
                placeholder="Опишите задачу подробнее"
                maxlength="1000"
            ></textarea>

        </div>


        <div class="form-group">

            <label class="form-label">
                Оплата
            </label>

            <input
                id="jobPrice"
                type="number"
                min="1"
                step="1"
                class="form-control"
                placeholder="Например: 1500"
            >

        </div>


        <div class="form-group">

            <label class="form-label">
                Категория
            </label>

            <select
                id="jobCategory"
                class="form-control"
            >

                <option>Курьер</option>
                <option>Уборка</option>
                <option>Ремонт</option>
                <option>IT</option>
                <option>Помощь</option>
                <option>Другое</option>

            </select>

        </div>


        <div
            id="coordsInfo"
            class="location-info"
        >
            <span>⌖</span>
            <span>
                Нажмите на карте и выберите место
            </span>
        </div>


        <button
            onclick="createJob()"
            class="primary-button"
        >
            Опубликовать
        </button>

    </div>

</div>


<!-- ========================================================
     LIST
========================================================= -->

<div
    id="listModal"
    class="modal-overlay hidden"
>

    <div class="modal-sheet">

        <div class="sheet-handle"></div>

        <div
            style="
                display:flex;
                justify-content:space-between;
                align-items:center;
            "
        >

            <h2 class="modal-title">
                Задания рядом
            </h2>

            <button
                class="close-button"
                onclick="closeList()"
            >
                ×
            </button>

        </div>


        <div
            id="jobsList"
            class="job-list"
        ></div>

    </div>

</div>


<!-- ========================================================
     PROFILE
========================================================= -->

<div
    id="profileModal"
    class="modal-overlay hidden"
>

    <div class="modal-sheet">

        <div class="sheet-handle"></div>

        <div
            style="
                display:flex;
                justify-content:space-between;
                align-items:center;
            "
        >

            <h2 class="modal-title">
                Профиль
            </h2>

            <button
                class="close-button"
                onclick="closeProfile()"
            >
                ×
            </button>

        </div>


        <div id="profileContent"></div>

    </div>

</div>


<!-- ========================================================
     SETTINGS
========================================================= -->

<div
    id="settingsModal"
    class="modal-overlay hidden"
>

    <div class="modal-sheet">

        <div class="sheet-handle"></div>

        <div
            style="
                display:flex;
                justify-content:space-between;
                align-items:center;
            "
        >

            <h2 class="modal-title">
                Настройки
            </h2>

            <button
                class="close-button"
                onclick="closeSettings()"
            >
                ×
            </button>

        </div>


        <div id="settingsContent"></div>

    </div>

</div>


<!-- ========================================================
     JOB DETAIL
========================================================= -->

<div
    id="jobDetailModal"
    class="modal-overlay hidden"
>

    <div class="modal-sheet">

        <div class="sheet-handle"></div>

        <div
            style="
                display:flex;
                justify-content:space-between;
                align-items:flex-start;
                gap:10px;
            "
        >

            <h2
                id="detailTitle"
                class="modal-title"
                style="margin-bottom:10px"
            ></h2>

            <button
                class="close-button"
                onclick="closeJobDetail()"
            >
                ×
            </button>

        </div>


        <div id="detailContent"></div>

    </div>

</div>


<script>

/* ==========================================================
   GLOBAL STATE
========================================================== */

let myMap = null;

let currentUser = null;

let authToken = null;

let selectedCoords = null;

let tempPlacemark = null;

let currentAuthMode = "login";


let settings = {
    darkMode: false,
    mapLayer: "map",
    notifications: true
};


/* ==========================================================
   SETTINGS
========================================================== */

function loadSettings() {

    try {

        const saved =
            localStorage.getItem(
                "neargig_settings"
            );

        if (saved) {

            settings = {
                ...settings,
                ...JSON.parse(saved)
            };

        }

    } catch (error) {

        console.warn(
            "Не удалось загрузить настройки",
            error
        );

    }

    applyTheme();

}


function saveSettings() {

    localStorage.setItem(
        "neargig_settings",
        JSON.stringify(settings)
    );

}


function applyTheme() {

    document.documentElement.classList.toggle(
        "dark",
        settings.darkMode
    );

}


/* ==========================================================
   MODALS
========================================================== */

function openModal(id) {

    const element =
        document.getElementById(id);

    if (element) {
        element.classList.remove("hidden");
    }

}


function closeModal(id) {

    const element =
        document.getElementById(id);

    if (element) {
        element.classList.add("hidden");
    }

}


function closeAuth() {
    closeModal("authModal");
}


function closeList() {
    closeModal("listModal");
}


function closeProfile() {
    closeModal("profileModal");
}


function closeSettings() {
    closeModal("settingsModal");
}


function closeJobDetail() {
    closeModal("jobDetailModal");
}


function closeJobForm() {

    closeModal("jobFormModal");

    selectedCoords = null;

    if (
        tempPlacemark
        && myMap
    ) {

        myMap.geoObjects.remove(
            tempPlacemark
        );

        tempPlacemark = null;

    }

    document.getElementById(
        "coordsInfo"
    ).innerHTML =
        "<span>⌖</span><span>Нажмите на карте и выберите место</span>";

}


/* ==========================================================
   NAVIGATION
========================================================== */

function switchTab(tab) {

    document
        .querySelectorAll(".nav-button")
        .forEach(button => {
            button.classList.remove(
                "active"
            );
        });


    const tabButton =
        document.getElementById(
            "tab" +
            tab.charAt(0).toUpperCase() +
            tab.slice(1)
        );


    if (tabButton) {
        tabButton.classList.add(
            "active"
        );
    }


    if (tab === "map") {

        closeList();
        closeProfile();
        closeSettings();

        if (myMap) {
            myMap.container.fitToViewport();
        }

        return;
    }


    if (tab === "add") {

        if (!currentUser) {
            openAuth();
            return;
        }

        openModal("jobFormModal");
        return;
    }


    if (tab === "list") {

        loadJobsList();
        return;
    }


    if (tab === "profile") {

        if (!currentUser) {
            openAuth();
            return;
        }

        showProfile();
    }

}


/* ==========================================================
   AUTH
========================================================== */

function openAuth(mode = "login") {

    currentAuthMode = mode;

    updateAuthUI();

    openModal("authModal");

}


function updateAuthUI() {

    const isLogin =
        currentAuthMode === "login";


    document.getElementById(
        "authTitle"
    ).textContent =
        isLogin
            ? "С возвращением"
            : "Создать аккаунт";


    document.getElementById(
        "authSubmit"
    ).textContent =
        isLogin
            ? "Войти"
            : "Зарегистрироваться";


    document.getElementById(
        "authNameGroup"
    ).classList.toggle(
        "hidden",
        isLogin
    );


    document.getElementById(
        "authSwitchText"
    ).textContent =
        isLogin
            ? "Нет аккаунта?"
            : "Уже есть аккаунт?";


    document.getElementById(
        "authSwitchBtn"
    ).textContent =
        isLogin
            ? "Зарегистрироваться"
            : "Войти";

}


document
    .getElementById("authSwitchBtn")
    .addEventListener(
        "click",
        () => {

            currentAuthMode =
                currentAuthMode === "login"
                    ? "register"
                    : "login";

            updateAuthUI();

        }
    );


document
    .getElementById("authForm")
    .addEventListener(
        "submit",
        async event => {

            event.preventDefault();


            const email =
                document
                    .getElementById(
                        "authEmail"
                    )
                    .value
                    .trim();


            const password =
                document
                    .getElementById(
                        "authPassword"
                    )
                    .value
                    .trim();


            const name =
                document
                    .getElementById(
                        "authName"
                    )
                    .value
                    .trim();


            if (
                !email
                || !password
            ) {

                alert(
                    "Заполните email и пароль"
                );

                return;

            }


            if (
                currentAuthMode === "register"
                && !name
            ) {

                alert(
                    "Введите ваше имя"
                );

                return;

            }


            const body = {
                email,
                password
            };


            if (
                currentAuthMode === "register"
            ) {

                body.name = name;

            }


            const response =
                await fetch(
                    currentAuthMode === "login"
                        ? "/api/login"
                        : "/api/register",
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json"
                        },
                        body:
                            JSON.stringify(body)
                    }
                );


            const data =
                await response.json();


            if (!response.ok) {

                alert(
                    data.error
                    || "Произошла ошибка"
                );

                return;

            }


            currentUser =
                data.user;

            authToken =
                data.token;


            localStorage.setItem(
                "token",
                authToken
            );


            updateUI();

            closeAuth();

        }
    );


/* ==========================================================
   USER UI
========================================================== */

function updateUI() {

    document
        .getElementById("loginBtn")
        .classList.toggle(
            "hidden",
            !!currentUser
        );


    document
        .getElementById("userMenu")
        .classList.toggle(
            "hidden",
            !currentUser
        );


    if (currentUser) {

        document
            .getElementById(
                "avatarImg"
            )
            .src =
                currentUser.avatar_url
                || "https://cdn-icons-png.flaticon.com/512/149/149071.png";

    }

}


document
    .getElementById("profileBtn")
    .addEventListener(
        "click",
        event => {

            event.stopPropagation();

            document
                .getElementById(
                    "dropdownMenu"
                )
                .classList.toggle(
                    "hidden"
                );

        }
    );


document.addEventListener(
    "click",
    () => {

        document
            .getElementById(
                "dropdownMenu"
            )
            .classList.add(
                "hidden"
            );

    }
);


/* ==========================================================
   MAP
========================================================== */

function initMap() {

    const mapType =
        settings.mapLayer === "hybrid"
            ? "yandex#hybrid"
            : "yandex#map";


    myMap =
        new ymaps.Map(
            "map",
            {
                center: [
                    55.7558,
                    37.6173
                ],

                zoom: 12,

                controls: [
                    "zoomControl",
                    "typeSelector"
                ],

                type: mapType,

                suppressMapOpenBlock: true
            }
        );


    myMap.events.add(
        "click",
        event => {

            const modal =
                document.getElementById(
                    "jobFormModal"
                );


            if (
                modal.classList.contains(
                    "hidden"
                )
            ) {
                return;
            }


            setTempMarker(
                event.get("coords")
            );

        }
    );


    loadJobsOnMap();

}


function setTempMarker(coords) {

    if (
        tempPlacemark
        && myMap
    ) {

        myMap.geoObjects.remove(
            tempPlacemark
        );

    }


    tempPlacemark =
        new ymaps.Placemark(
            coords,
            {
                balloonContent:
                    "Место для задания"
            },
            {
                preset:
                    "islands#redDotIcon"
            }
        );


    myMap.geoObjects.add(
        tempPlacemark
    );


    selectedCoords = coords;


    document.getElementById(
        "coordsInfo"
    ).innerHTML =
        "<span>✓</span><span>Место выбрано</span>";

}


function loadJobsOnMap(filters = {}) {

    if (!myMap) {
        return;
    }


    const objects = [];

    myMap.geoObjects.each(
        object => {

            if (
                object !==
                tempPlacemark
            ) {
                objects.push(
                    object
                );
            }

        }
    );


    objects.forEach(
        object => {
            myMap.geoObjects.remove(
                object
            );
        }
    );


    const params =
        new URLSearchParams(
            filters
        );


    fetch(
        "/api/jobs?" +
        params.toString()
    )
        .then(
            response =>
                response.json()
        )
        .then(
            jobs => {

                jobs.forEach(
                    job => {

                        if (
                            job.lat === null
                            || job.lng === null
                        ) {
                            return;
                        }


                        const placemark =
                            new ymaps.Placemark(
                                [
                                    job.lat,
                                    job.lng
                                ],
                                {
                                    balloonContent:
                                        `
                                        <div style="
                                            min-width:190px;
                                            padding:4px;
                                        ">
                                            <b>
                                                ${escapeHtml(job.title)}
                                            </b>

                                            <div style="
                                                margin-top:5px;
                                            ">
                                                ${escapeHtml(job.description || "")}
                                            </div>

                                            <div style="
                                                margin-top:7px;
                                                font-weight:700;
                                            ">
                                                ${formatPrice(job.price)}
                                            </div>

                                            <button
                                                onclick="showJobDetail(${job.id})"
                                                style="
                                                    margin-top:8px;
                                                    padding:7px 10px;
                                                    border:0;
                                                    border-radius:8px;
                                                    background:#6366f1;
                                                    color:white;
                                                "
                                            >
                                                Подробнее
                                            </button>
                                        </div>
                                        `
                                },
                                {
                                    preset:
                                        "islands#violetDotIcon"
                                }
                            );


                        myMap.geoObjects.add(
                            placemark
                        );

                    }
                );

            }
        )
        .catch(
            error =>
                console.error(
                    error
                )
        );

}


/* ==========================================================
   JOB LIST
========================================================== */

async function loadJobsList() {

    openModal("listModal");


    const container =
        document.getElementById(
            "jobsList"
        );


    container.innerHTML =
        `
        <div class="empty-state">
            <div class="empty-icon">
                …
            </div>
            Загружаем задания
        </div>
        `;


    try {

        const response =
            await fetch(
                "/api/jobs"
            );


        const jobs =
            await response.json();


        if (!jobs.length) {

            container.innerHTML =
                `
                <div class="empty-state">
                    <div class="empty-icon">
                        ⌖
                    </div>

                    Пока нет активных заданий
                </div>
                `;

            return;

        }


        container.innerHTML =
            jobs
                .map(
                    renderJobCard
                )
                .join("");


    } catch (error) {

        container.innerHTML =
            `
            <div class="empty-state">
                Не удалось загрузить задания
            </div>
            `;

    }

}


function renderJobCard(job) {

    return `
        <div
            class="job-card"
            onclick="showJobDetail(${job.id})"
        >

            <div class="job-card-head">

                <h3 class="job-title">
                    ${escapeHtml(job.title)}
                </h3>

                <div class="job-price">
                    ${formatPrice(job.price)}
                </div>

            </div>


            ${
                job.description
                    ? `
                        <div class="job-description">
                            ${escapeHtml(
                                job.description
                            )}
                        </div>
                      `
                    : ""
            }


            <div class="job-meta">

                <span class="meta-chip">
                    ${escapeHtml(
                        job.category
                    )}
                </span>

                <span class="meta-chip">
                    ${escapeHtml(
                        job.author.name
                    )}
                </span>

                ${
                    job.distance !== undefined
                        ? `
                            <span class="meta-chip">
                                ${job.distance} км
                            </span>
                          `
                        : ""
                }

            </div>

        </div>
    `;

}


/* ==========================================================
   JOB DETAIL
========================================================== */

async function showJobDetail(jobId) {

    try {

        const response =
            await fetch(
                "/api/jobs/" +
                jobId
            );


        const job =
            await response.json();


        if (!response.ok) {

            alert(
                job.error
                || "Ошибка"
            );

            return;

        }


        document.getElementById(
            "detailTitle"
        ).textContent =
            job.title;


        const isOwner =
            currentUser
            && currentUser.id === job.user_id;


        let html =
            `
            <div class="job-card" style="margin-bottom:12px">

                <div class="job-price"
                     style="
                        font-size:21px;
                        margin-bottom:8px;
                     "
                >
                    ${formatPrice(job.price)}
                </div>


                ${
                    job.description
                        ? `
                            <div class="job-description"
                                 style="
                                    font-size:14px;
                                 "
                            >
                                ${escapeHtml(
                                    job.description
                                )}
                            </div>
                          `
                        : ""
                }


                <div class="job-meta">

                    <span class="meta-chip">
                        ${escapeHtml(
                            job.category
                        )}
                    </span>

                    <span class="meta-chip">
                        ${escapeHtml(
                            job.author.name
                        )}
                    </span>

                    <span class="meta-chip">
                        ★ ${job.author.rating || "0"}
                    </span>

                    <span class="meta-chip">
                        ${job.views || 0} просмотров
                    </span>

                </div>

            </div>
            `;


        if (
            currentUser
            && !isOwner
        ) {

            html +=
                `
                <button
                    class="primary-button"
                    onclick="respondToJob(${job.id})"
                    style="margin-bottom:8px"
                >
                    Откликнуться
                </button>

                <button
                    class="secondary-button"
                    onclick="toggleFav(${job.id})"
                >
                    ☆ Добавить в избранное
                </button>
                `;

        }


        if (isOwner) {

            html +=
                `
                <div class="section-title">
                    Отклики · ${job.responses.length}
                </div>
                `;


            if (!job.responses.length) {

                html +=
                    `
                    <div class="empty-state">
                        Пока никто не откликнулся
                    </div>
                    `;

            } else {

                html +=
                    job.responses
                        .map(
                            response => `
                            <div
                                class="job-card"
                                style="
                                    display:flex;
                                    gap:10px;
                                    align-items:flex-start;
                                    margin-bottom:8px;
                                "
                            >

                                <img
                                    src="${
                                        response.avatar_url
                                        || "https://cdn-icons-png.flaticon.com/512/149/149071.png"
                                    }"
                                    style="
                                        width:40px;
                                        height:40px;
                                        border-radius:50%;
                                        object-fit:cover;
                                    "
                                >

                                <div>

                                    <div
                                        style="
                                            font-weight:700;
                                            font-size:13px;
                                        "
                                    >
                                        ${escapeHtml(
                                            response.name
                                        )}
                                    </div>

                                    <div
                                        style="
                                            color:var(--text-secondary);
                                            font-size:13px;
                                            margin-top:3px;
                                        "
                                    >
                                        ${
                                            escapeHtml(
                                                response.message
                                                || "Без сообщения"
                                            )
                                        }
                                    </div>

                                </div>

                            </div>
                            `
                        )
                        .join("");

            }

        }


        document.getElementById(
            "detailContent"
        ).innerHTML =
            html;


        openModal(
            "jobDetailModal"
        );


    } catch (error) {

        console.error(
            error
        );

        alert(
            "Не удалось открыть задание"
        );

    }

}


/* ==========================================================
   RESPOND
========================================================== */

async function respondToJob(jobId) {

    if (!currentUser) {

        openAuth();

        return;

    }


    const message =
        prompt(
            "Напишите короткое сообщение заказчику:"
        );


    if (message === null) {
        return;
    }


    const response =
        await fetch(
            "/api/jobs/" +
            jobId +
            "/respond",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",

                    "Authorization":
                        "Bearer " +
                        authToken
                },

                body:
                    JSON.stringify({
                        message:
                            message.trim()
                    })
            }
        );


    const data =
        await response.json();


    if (!response.ok) {

        alert(
            data.error
            || "Не удалось отправить отклик"
        );

        return;

    }


    alert(
        "Отклик отправлен"
    );


    closeJobDetail();

}


/* ==========================================================
   FAVORITES
========================================================== */

async function toggleFav(jobId) {

    if (!currentUser) {

        openAuth();

        return;

    }


    const response =
        await fetch(
            "/api/favorites/" +
            jobId,
            {
                method: "POST",

                headers: {
                    "Authorization":
                        "Bearer " +
                        authToken
                }
            }
        );


    const data =
        await response.json();


    if (!response.ok) {

        alert(
            data.error
            || "Ошибка"
        );

        return;

    }


    alert(
        data.action === "added"
            ? "Добавлено в избранное"
            : "Удалено из избранного"
    );

}


/* ==========================================================
   CREATE JOB
========================================================== */

async function createJob() {

    if (!currentUser) {

        openAuth();

        return;

    }


    const title =
        document.getElementById(
            "jobTitle"
        ).value.trim();


    const description =
        document.getElementById(
            "jobDesc"
        ).value.trim();


    const price =
        document.getElementById(
            "jobPrice"
        ).value;


    const category =
        document.getElementById(
            "jobCategory"
        ).value;


    if (!title) {

        alert(
            "Введите название задания"
        );

        return;

    }


    if (
        !price
        || Number(price) <= 0
    ) {

        alert(
            "Введите корректную оплату"
        );

        return;

    }


    if (!selectedCoords) {

        alert(
            "Выберите место задания на карте"
        );

        return;

    }


    const response =
        await fetch(
            "/api/jobs",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",

                    "Authorization":
                        "Bearer " +
                        authToken
                },

                body:
                    JSON.stringify({
                        title,
                        description,
                        price:
                            Number(price),
                        lat:
                            selectedCoords[0],
                        lng:
                            selectedCoords[1],
                        category
                    })
            }
        );


    const data =
        await response.json();


    if (!response.ok) {

        alert(
            data.error
            || "Не удалось создать задание"
        );

        return;

    }


    alert(
        "Задание опубликовано"
    );


    document.getElementById(
        "jobTitle"
    ).value = "";


    document.getElementById(
        "jobDesc"
    ).value = "";


    document.getElementById(
        "jobPrice"
    ).value = "";


    closeJobForm();

    loadJobsOnMap();

}


/* ==========================================================
   PROFILE
========================================================== */

async function showProfile() {

    if (!currentUser) {

        openAuth();

        return;

    }


    const jobsPromise =
        fetch(
            "/api/jobs?user_id=" +
            currentUser.id
        ).then(
            response =>
                response.json()
        );


    const favoritesPromise =
        fetch(
            "/api/favorites",
            {
                headers: {
                    "Authorization":
                        "Bearer " +
                        authToken
                }
            }
        ).then(
            response =>
                response.json()
        );


    const [
        myJobs,
        favorites
    ] =
        await Promise.all([
            jobsPromise,
            favoritesPromise
        ]);


    document.getElementById(
        "profileContent"
    ).innerHTML =
        `
        <div class="profile-card">

            <img
                class="profile-avatar"
                src="${
                    currentUser.avatar_url
                    || "https://cdn-icons-png.flaticon.com/512/149/149071.png"
                }"
            >

            <div>

                <div class="profile-name">
                    ${escapeHtml(
                        currentUser.name
                    )}
                </div>

                <div class="profile-email">
                    ${escapeHtml(
                        currentUser.email
                    )}
                </div>

            </div>

        </div>


        <div class="stats">

            <div class="stat">

                <div class="stat-value">
                    ★ ${currentUser.rating || "0"}
                </div>

                <div class="stat-label">
                    Рейтинг
                </div>

            </div>


            <div class="stat">

                <div class="stat-value">
                    ${currentUser.reviews_count || 0}
                </div>

                <div class="stat-label">
                    Отзывов
                </div>

            </div>


            <div class="stat">

                <div class="stat-value">
                    ${currentUser.completed_jobs || 0}
                </div>

                <div class="stat-label">
                    Выполнено
                </div>

            </div>

        </div>


        <button
            class="secondary-button"
            onclick="showSettings()"
            style="margin-bottom:10px"
        >
            ⚙ Настройки
        </button>


        <div class="section-title">
            Мои задания · ${myJobs.length}
        </div>


        ${
            myJobs.length
                ? `
                    <div class="job-list">
                        ${myJobs
                            .map(
                                renderJobCard
                            )
                            .join("")}
                    </div>
                  `
                : `
                    <div class="empty-state">
                        Вы ещё ничего не публиковали
                    </div>
                  `
        }


        <div class="section-title">
            Избранное · ${favorites.length}
        </div>


        ${
            favorites.length
                ? `
                    <div class="job-list">
                        ${favorites
                            .map(
                                renderJobCard
                            )
                            .join("")}
                    </div>
                  `
                : `
                    <div class="empty-state">
                        В избранном пока пусто
                    </div>
                  `
        }
        `;


    openModal(
        "profileModal"
    );

}


/* ==========================================================
   MY JOBS
========================================================== */

async function showMyJobs() {

    if (!currentUser) {

        openAuth();

        return;

    }


    const jobs =
        await fetch(
            "/api/jobs?user_id=" +
            currentUser.id
        ).then(
            response =>
                response.json()
        );


    document.getElementById(
        "detailTitle"
    ).textContent =
        "Мои задания";


    document.getElementById(
        "detailContent"
    ).innerHTML =
        jobs.length
            ? `
                <div class="job-list">
                    ${jobs
                        .map(
                            renderJobCard
                        )
                        .join("")}
                </div>
              `
            : `
                <div class="empty-state">
                    <div class="empty-icon">
                        +
                    </div>

                    У вас пока нет заданий
                </div>
              `;


    openModal(
        "jobDetailModal"
    );

}


/* ==========================================================
   FAVORITES LIST
========================================================== */

async function showFavorites() {

    if (!currentUser) {

        openAuth();

        return;

    }


    const favorites =
        await fetch(
            "/api/favorites",
            {
                headers: {
                    "Authorization":
                        "Bearer " +
                        authToken
                }
            }
        ).then(
            response =>
                response.json()
        );


    document.getElementById(
        "detailTitle"
    ).textContent =
        "Избранное";


    document.getElementById(
        "detailContent"
    ).innerHTML =
        favorites.length
            ? `
                <div class="job-list">
                    ${favorites
                        .map(
                            renderJobCard
                        )
                        .join("")}
                </div>
              `
            : `
                <div class="empty-state">
                    <div class="empty-icon">
                        ☆
                    </div>

                    Здесь появятся понравившиеся задания
                </div>
              `;


    openModal(
        "jobDetailModal"
    );

}


/* ==========================================================
   SETTINGS
========================================================== */

function showSettings() {

    document.getElementById(
        "dropdownMenu"
    ).classList.add(
        "hidden"
    );


    document.getElementById(
        "settingsContent"
    ).innerHTML =
        `
        <div class="settings-section">

            <div class="settings-heading">
                Интерфейс
            </div>


            <div class="settings-item">

                <div>

                    <div class="settings-title">
                        Тёмная тема
                    </div>

                    <div class="settings-subtitle">
                        Спокойный тёмный интерфейс
                    </div>

                </div>


                <label class="toggle">

                    <input
                        type="checkbox"
                        ${
                            settings.darkMode
                                ? "checked"
                                : ""
                        }
                        onchange="
                            settings.darkMode =
                                this.checked;

                            saveSettings();
                            applyTheme();
                        "
                    >

                    <span class="toggle-slider"></span>

                </label>

            </div>


            <div class="settings-item">

                <div>

                    <div class="settings-title">
                        Гибридная карта
                    </div>

                    <div class="settings-subtitle">
                        Спутниковый вид с подписями
                    </div>

                </div>


                <label class="toggle">

                    <input
                        type="checkbox"
                        ${
                            settings.mapLayer === "hybrid"
                                ? "checked"
                                : ""
                        }
                        onchange="
                            settings.mapLayer =
                                this.checked
                                    ? 'hybrid'
                                    : 'map';

                            saveSettings();

                            reloadMap();
                        "
                    >

                    <span class="toggle-slider"></span>

                </label>

            </div>

        </div>


        <div class="settings-section">

            <div class="settings-heading">
                Уведомления
            </div>


            <div class="settings-item">

                <div>

                    <div class="settings-title">
                        Уведомления
                    </div>

                    <div class="settings-subtitle">
                        Новые отклики и задания
                    </div>

                </div>


                <label class="toggle">

                    <input
                        type="checkbox"
                        ${
                            settings.notifications
                                ? "checked"
                                : ""
                        }
                        onchange="
                            settings.notifications =
                                this.checked;

                            saveSettings();
                        "
                    >

                    <span class="toggle-slider"></span>

                </label>

            </div>

        </div>


        <div class="settings-section">

            <div class="settings-heading">
                О приложении
            </div>


            <div class="settings-item">

                <div>

                    <div class="settings-title">
                        Near Gig
                    </div>

                    <div class="settings-subtitle">
                        Версия приложения
                    </div>

                </div>

                <div
                    style="
                        color:var(--text-muted);
                        font-size:12px;
                    "
                >
                    1.1.0
                </div>

            </div>

        </div>
        `;


    openModal(
        "settingsModal"
    );

}


function reloadMap() {

    if (!myMap) {
        return;
    }


    const center =
        myMap.getCenter();


    const zoom =
        myMap.getZoom();


    myMap.destroy();


    const mapType =
        settings.mapLayer === "hybrid"
            ? "yandex#hybrid"
            : "yandex#map";


    myMap =
        new ymaps.Map(
            "map",
            {
                center,
                zoom,

                controls: [
                    "zoomControl",
                    "typeSelector"
                ],

                type: mapType
            }
        );


    myMap.events.add(
        "click",
        event => {

            const modal =
                document.getElementById(
                    "jobFormModal"
                );


            if (
                modal.classList.contains(
                    "hidden"
                )
            ) {
                return;
            }


            setTempMarker(
                event.get("coords")
            );

        }
    );


    loadJobsOnMap();

}


/* ==========================================================
   LOCATION
========================================================== */

document
    .getElementById(
        "manualLocateBtn"
    )
    .addEventListener(
        "click",
        () => {

            if (
                !navigator.geolocation
            ) {

                alert(
                    "Геолокация недоступна"
                );

                return;

            }


            navigator.geolocation.getCurrentPosition(

                position => {

                    if (!myMap) {
                        return;
                    }


                    myMap.setCenter(
                        [
                            position.coords.latitude,
                            position.coords.longitude
                        ],
                        15,
                        {
                            duration: 400
                        }
                    );

                },

                () => {

                    alert(
                        "Не удалось определить местоположение. Проверьте разрешение браузера."
                    );

                },

                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 60000
                }

            );

        }
    );


/* ==========================================================
   LOGOUT
========================================================== */

async function logout() {

    try {

        await fetch(
            "/api/logout",
            {
                method: "POST",

                headers: {
                    "Authorization":
                        "Bearer " +
                        authToken
                }
            }
        );

    } catch (error) {

        console.warn(
            error
        );

    }


    currentUser = null;

    authToken = null;


    localStorage.removeItem(
        "token"
    );


    updateUI();

}


/* ==========================================================
   HELPERS
========================================================== */

function formatPrice(price) {

    return (
        Number(price || 0)
            .toLocaleString("ru-RU")
        + " ₽"
    );

}


function escapeHtml(value) {

    return String(
        value ?? ""
    )
        .replace(
            /&/g,
            "&amp;"
        )
        .replace(
            /</g,
            "&lt;"
        )
        .replace(
            />/g,
            "&gt;"
        )
        .replace(
            /"/g,
            "&quot;"
        )
        .replace(
            /'/g,
            "&#039;"
        );

}


/* ==========================================================
   RESTORE SESSION
========================================================== */

async function restoreSession() {

    const token =
        localStorage.getItem(
            "token"
        );


    if (!token) {
        return;
    }


    try {

        const response =
            await fetch(
                "/api/me",
                {
                    headers: {
                        "Authorization":
                            "Bearer " +
                            token
                    }
                }
            );


        if (!response.ok) {
            throw new Error(
                "Session expired"
            );
        }


        currentUser =
            await response.json();


        authToken =
            token;


        updateUI();

    } catch (error) {

        localStorage.removeItem(
            "token"
        );

    }

}


/* ==========================================================
   INIT
========================================================== */

loadSettings();

restoreSession();


if ("serviceWorker" in navigator) {

    window.addEventListener(
        "load",
        () => {

            navigator
                .serviceWorker
                .register("/sw.js")
                .catch(
                    error =>
                        console.warn(
                            "Service worker:",
                            error
                        )
                );

        }
    );

}


ymaps.ready(
    initMap
);

</script>

</div>

</body>

</html>
""".replace(
        "__YANDEX_MAPS_API_KEY__",
        YANDEX_MAPS_API_KEY
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False
    )
