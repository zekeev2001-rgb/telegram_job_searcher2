import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2

from flask import Flask, request, jsonify, make_response


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

DEFAULT_AVATAR = (
    "https://cdn-icons-png.flaticon.com/512/149/149071.png"
)

DEFAULT_APP_ICON = (
    "https://cdn-icons-png.flaticon.com/512/1041/1041916.png"
)

# На Render persistent disk должен быть подключен,
# если нужно сохранять SQLite после перезапуска.
DB_DIR = os.environ.get(
    "DB_DIR",
    "/opt/render/project/src"
)

os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "app.db")


app = Flask(__name__)
app.secret_key = SECRET_KEY


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            category TEXT DEFAULT 'Другое',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT,
            views INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(job_id, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            job_id INTEGER,
            rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
            comment TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(to_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL,
            UNIQUE(from_user_id, to_user_id, job_id)
        )
    """)

    cursor.execute("""
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

    # Индексы
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_status
        ON jobs(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_user
        ON jobs(user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_category
        ON jobs(category)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_responses_job
        ON responses(job_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_favorites_user
        ON favorites(user_id)
    """)

    # Исправляем старые записи, если avatar_url был пустым.
    cursor.execute("""
        UPDATE users
        SET avatar_url = ?
        WHERE avatar_url IS NULL OR avatar_url = ''
    """, (DEFAULT_AVATAR,))

    conn.commit()
    conn.close()


init_db()


# ============================================================
# HELPERS
# ============================================================

def hash_password(password):
    """
    Оставляем SHA-256 для совместимости с уже созданными
    аккаунтами из предыдущей версии.
    """
    return hashlib.sha256(
        password.encode("utf-8")
    ).hexdigest()


def generate_token():
    return secrets.token_urlsafe(48)


def get_auth_token():
    auth = request.headers.get("Authorization", "")

    if auth.startswith("Bearer "):
        return auth[7:].strip()

    return auth.strip()


def get_user_by_token(token):
    if not token:
        return None

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT users.*
        FROM users
        JOIN sessions
            ON users.id = sessions.user_id
        WHERE sessions.token = ?
          AND datetime(sessions.expires_at) > datetime('now')
    """, (token,))

    user = cursor.fetchone()
    conn.close()

    if user:
        return dict(user)

    return None


def require_auth():
    token = get_auth_token()
    return get_user_by_token(token)


def create_session(user_id):
    token = generate_token()

    expires_at = (
        datetime.now() + timedelta(days=30)
    ).isoformat(timespec="seconds")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
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
    conn.close()

    return token


def user_public(user):
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "phone": user.get("phone", ""),
        "role": user["role"],
        "avatar_url": user["avatar_url"] or DEFAULT_AVATAR,
        "rating": float(user["rating"] or 0),
        "reviews_count": int(user["reviews_count"] or 0),
        "completed_jobs": int(user["completed_jobs"] or 0),
        "created_at": user["created_at"],
        "last_login": user.get("last_login")
    }


def validate_email(email):
    return (
        "@" in email
        and "." in email.split("@")[-1]
        and len(email) <= 255
    )


def haversine(lat1, lng1, lat2, lng2):
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


def valid_coordinates(lat, lng):
    try:
        lat = float(lat)
        lng = float(lng)

        return (
            -90 <= lat <= 90
            and -180 <= lng <= 180
        )
    except (TypeError, ValueError):
        return False


def job_to_dict(row):
    job = dict(row)

    author_id = job.pop("author_id", None)
    author_name = job.pop("author_name", None)
    author_rating = job.pop("author_rating", 0)
    author_avatar = job.pop("author_avatar", None)

    job["author"] = {
        "id": author_id,
        "name": author_name,
        "rating": float(author_rating or 0),
        "avatar": author_avatar or DEFAULT_AVATAR
    }

    return job


def recalculate_rating(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            AVG(rating) AS average_rating,
            COUNT(*) AS review_count
        FROM reviews
        WHERE to_user_id = ?
    """, (user_id,))

    row = cursor.fetchone()

    average = float(row["average_rating"] or 0)
    count = int(row["review_count"] or 0)

    cursor.execute("""
        UPDATE users
        SET rating = ?,
            reviews_count = ?
        WHERE id = ?
    """, (
        round(average, 2),
        count,
        user_id
    ))

    conn.commit()
    conn.close()


# ============================================================
# HEALTH
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "app": "Near Gig",
        "version": "1.1.0"
    })


# ============================================================
# AUTH
# ============================================================

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    email = str(
        data.get("email", "")
    ).strip().lower()

    password = str(
        data.get("password", "")
    )

    name = str(
        data.get("name", "")
    ).strip()

    role = str(
        data.get("role", "executor")
    ).strip().lower()

    if role not in ("executor", "customer"):
        role = "executor"

    if not email or not password or not name:
        return jsonify({
            "error": "Заполните все обязательные поля"
        }), 400

    if len(name) < 2:
        return jsonify({
            "error": "Имя должно содержать минимум 2 символа"
        }), 400

    if len(password) < 6:
        return jsonify({
            "error": "Пароль должен быть минимум 6 символов"
        }), 400

    if not validate_email(email):
        return jsonify({
            "error": "Некорректный email"
        }), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM users WHERE email = ?",
        (email,)
    )

    if cursor.fetchone():
        conn.close()

        return jsonify({
            "error": "Этот email уже зарегистрирован"
        }), 409

    password_hash = hash_password(password)

    cursor.execute("""
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

    user_id = cursor.lastrowid

    conn.commit()

    cursor.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    )

    user = cursor.fetchone()

    conn.close()

    token = create_session(user_id)

    return jsonify({
        "token": token,
        "user": user_public(dict(user))
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
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    )

    user = cursor.fetchone()

    if not user:
        conn.close()

        return jsonify({
            "error": "Неверный email или пароль"
        }), 401

    if user["password_hash"] != hash_password(password):
        conn.close()

        return jsonify({
            "error": "Неверный email или пароль"
        }), 401

    cursor.execute("""
        UPDATE users
        SET last_login = datetime('now')
        WHERE id = ?
    """, (user["id"],))

    conn.commit()

    cursor.execute(
        "SELECT * FROM users WHERE id = ?",
        (user["id"],)
    )

    updated_user = cursor.fetchone()

    conn.close()

    token = create_session(
        updated_user["id"]
    )

    return jsonify({
        "token": token,
        "user": user_public(dict(updated_user))
    })


@app.route("/api/logout", methods=["POST"])
def logout():
    token = get_auth_token()

    if token:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM sessions WHERE token = ?",
            (token,)
        )

        conn.commit()
        conn.close()

    return jsonify({
        "status": "ok"
    })


@app.route("/api/me", methods=["GET"])
def get_me():
    user = require_auth()

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
    min_price = request.args.get("min_price", type=float)
    user_id = request.args.get("user_id", type=int)
    status = request.args.get("status", "active")
    search = request.args.get("search", "").strip()

    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT
            jobs.*,
            users.id AS author_id,
            users.name AS author_name,
            users.rating AS author_rating,
            users.avatar_url AS author_avatar
        FROM jobs
        JOIN users
            ON jobs.user_id = users.id
        WHERE 1 = 1
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

    if min_price is not None:
        query += " AND jobs.price >= ?"
        params.append(min_price)

    if user_id:
        query += " AND jobs.user_id = ?"
        params.append(user_id)

    if search:
        query += """
            AND (
                jobs.title LIKE ?
                OR jobs.description LIKE ?
            )
        """

        search_value = f"%{search}%"

        params.extend([
            search_value,
            search_value
        ])

    query += """
        ORDER BY jobs.created_at DESC
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    conn.close()

    jobs = []

    for row in rows:
        job = job_to_dict(row)

        if (
            lat is not None
            and lng is not None
            and radius is not None
            and job["lat"] is not None
            and job["lng"] is not None
        ):
            distance = haversine(
                lat,
                lng,
                job["lat"],
                job["lng"]
            )

            if distance > radius:
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
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            jobs.*,
            users.id AS author_id,
            users.name AS author_name,
            users.rating AS author_rating,
            users.avatar_url AS author_avatar
        FROM jobs
        JOIN users
            ON jobs.user_id = users.id
        WHERE jobs.id = ?
    """, (job_id,))

    job = cursor.fetchone()

    if not job:
        conn.close()

        return jsonify({
            "error": "Задание не найдено"
        }), 404

    # Увеличиваем просмотры.
    cursor.execute("""
        UPDATE jobs
        SET views = views + 1
        WHERE id = ?
    """, (job_id,))

    cursor.execute("""
        SELECT
            responses.*,
            users.name,
            users.avatar_url,
            users.rating
        FROM responses
        JOIN users
            ON responses.user_id = users.id
        WHERE responses.job_id = ?
        ORDER BY responses.created_at DESC
    """, (job_id,))

    responses = [
        dict(row)
        for row in cursor.fetchall()
    ]

    cursor.execute("""
        SELECT
            reviews.*,
            users.name,
            users.avatar_url
        FROM reviews
        JOIN users
            ON reviews.from_user_id = users.id
        WHERE reviews.job_id = ?
        ORDER BY reviews.created_at DESC
    """, (job_id,))

    reviews = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.commit()
    conn.close()

    result = job_to_dict(job)

    result["responses"] = responses
    result["reviews"] = reviews
    result["views"] = int(result.get("views", 0) or 0) + 1

    return jsonify(result)


@app.route("/api/jobs", methods=["POST"])
def create_job():
    user = require_auth()

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

    category = str(
        data.get("category", "Другое")
    ).strip()

    price = data.get("price")
    lat = data.get("lat")
    lng = data.get("lng")

    if not title:
        return jsonify({
            "error": "Введите название задания"
        }), 400

    if len(title) > 150:
        return jsonify({
            "error": "Название слишком длинное"
        }), 400

    if price is None:
        return jsonify({
            "error": "Укажите цену"
        }), 400

    try:
        price = float(price)
    except (TypeError, ValueError):
        return jsonify({
            "error": "Цена должна быть числом"
        }), 400

    if price <= 0:
        return jsonify({
            "error": "Цена должна быть больше нуля"
        }), 400

    if not valid_coordinates(lat, lng):
        return jsonify({
            "error": "Некорректные координаты"
        }), 400

    lat = float(lat)
    lng = float(lng)

    expires_at = (
        datetime.now() + timedelta(days=30)
    ).isoformat(timespec="seconds")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO jobs (
            user_id,
            title,
            description,
            price,
            lat,
            lng,
            category,
            status,
            expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
    """, (
        user["id"],
        title,
        description,
        price,
        lat,
        lng,
        category or "Другое",
        expires_at
    ))

    job_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "job_id": job_id
    }), 201


@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def delete_job(job_id):
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        return jsonify({
            "error": "Задание не найдено"
        }), 404

    if job["user_id"] != user["id"]:
        conn.close()

        return jsonify({
            "error": "У вас нет прав на удаление этого задания"
        }), 403

    cursor.execute(
        "DELETE FROM jobs WHERE id = ?",
        (job_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok"
    })


@app.route("/api/jobs/<int:job_id>/status", methods=["POST"])
def change_job_status(job_id):
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    data = request.get_json(silent=True) or {}

    new_status = str(
        data.get("status", "")
    ).strip().lower()

    allowed = {
        "active",
        "completed",
        "cancelled"
    }

    if new_status not in allowed:
        return jsonify({
            "error": "Некорректный статус"
        }), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        return jsonify({
            "error": "Задание не найдено"
        }), 404

    if job["user_id"] != user["id"]:
        conn.close()

        return jsonify({
            "error": "Нет прав"
        }), 403

    cursor.execute("""
        UPDATE jobs
        SET status = ?
        WHERE id = ?
    """, (
        new_status,
        job_id
    ))

    if new_status == "completed":
        cursor.execute("""
            UPDATE users
            SET completed_jobs = completed_jobs + 1
            WHERE id = ?
        """, (user["id"],))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "job_status": new_status
    })


# ============================================================
# RESPONSES
# ============================================================

@app.route(
    "/api/jobs/<int:job_id>/respond",
    methods=["POST"]
)
def respond_to_job(job_id):
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    data = request.get_json(silent=True) or {}

    message = str(
        data.get("message", "")
    ).strip()

    if len(message) > 1000:
        return jsonify({
            "error": "Сообщение слишком длинное"
        }), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        return jsonify({
            "error": "Задание не найдено"
        }), 404

    if job["user_id"] == user["id"]:
        conn.close()

        return jsonify({
            "error": "Нельзя откликнуться на собственное задание"
        }), 400

    if job["status"] != "active":
        conn.close()

        return jsonify({
            "error": "Это задание уже не активно"
        }), 400

    cursor.execute("""
        SELECT id
        FROM responses
        WHERE job_id = ?
          AND user_id = ?
    """, (
        job_id,
        user["id"]
    ))

    if cursor.fetchone():
        conn.close()

        return jsonify({
            "error": "Вы уже откликались на это задание"
        }), 409

    cursor.execute("""
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

    response_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "response_id": response_id
    }), 201


@app.route(
    "/api/jobs/<int:job_id>/responses",
    methods=["GET"]
)
def get_job_responses(job_id):
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        return jsonify({
            "error": "Задание не найдено"
        }), 404

    if job["user_id"] != user["id"]:
        conn.close()

        return jsonify({
            "error": "Нет доступа"
        }), 403

    cursor.execute("""
        SELECT
            responses.*,
            users.name,
            users.email,
            users.avatar_url,
            users.rating,
            users.reviews_count
        FROM responses
        JOIN users
            ON responses.user_id = users.id
        WHERE responses.job_id = ?
        ORDER BY responses.created_at DESC
    """, (job_id,))

    responses = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return jsonify(responses)


@app.route(
    "/api/responses/<int:response_id>/status",
    methods=["POST"]
)
def change_response_status(response_id):
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    data = request.get_json(silent=True) or {}

    new_status = str(
        data.get("status", "")
    ).strip().lower()

    allowed = {
        "pending",
        "accepted",
        "rejected",
        "completed"
    }

    if new_status not in allowed:
        return jsonify({
            "error": "Некорректный статус"
        }), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            responses.*,
            jobs.user_id AS owner_id
        FROM responses
        JOIN jobs
            ON responses.job_id = jobs.id
        WHERE responses.id = ?
    """, (response_id,))

    response = cursor.fetchone()

    if not response:
        conn.close()

        return jsonify({
            "error": "Отклик не найден"
        }), 404

    if response["owner_id"] != user["id"]:
        conn.close()

        return jsonify({
            "error": "Нет доступа"
        }), 403

    cursor.execute("""
        UPDATE responses
        SET status = ?
        WHERE id = ?
    """, (
        new_status,
        response_id
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok"
    })


# ============================================================
# FAVORITES
# ============================================================

@app.route("/api/favorites", methods=["GET"])
def get_favorites():
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            jobs.*,
            users.id AS author_id,
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
    """, (user["id"],))

    favorites = [
        job_to_dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return jsonify(favorites)


@app.route(
    "/api/favorites/<int:job_id>",
    methods=["POST"]
)
def toggle_favorite(job_id):
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM jobs WHERE id = ?",
        (job_id,)
    )

    if not cursor.fetchone():
        conn.close()

        return jsonify({
            "error": "Задание не найдено"
        }), 404

    cursor.execute("""
        SELECT id
        FROM favorites
        WHERE user_id = ?
          AND job_id = ?
    """, (
        user["id"],
        job_id
    ))

    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            "DELETE FROM favorites WHERE id = ?",
            (existing["id"],)
        )

        action = "removed"

    else:
        cursor.execute("""
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


@app.route(
    "/api/favorites/<int:job_id>",
    methods=["GET"]
)
def check_favorite(job_id):
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id
        FROM favorites
        WHERE user_id = ?
          AND job_id = ?
    """, (
        user["id"],
        job_id
    ))

    exists = cursor.fetchone() is not None

    conn.close()

    return jsonify({
        "favorite": exists
    })


# ============================================================
# REVIEWS
# ============================================================

@app.route(
    "/api/users/<int:user_id>/reviews",
    methods=["GET"]
)
def get_user_reviews(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            reviews.*,
            users.name,
            users.avatar_url
        FROM reviews
        JOIN users
            ON reviews.from_user_id = users.id
        WHERE reviews.to_user_id = ?
        ORDER BY reviews.created_at DESC
    """, (user_id,))

    reviews = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return jsonify(reviews)


@app.route(
    "/api/users/<int:user_id>/reviews",
    methods=["POST"]
)
def create_review(user_id):
    user = require_auth()

    if not user:
        return jsonify({
            "error": "Не авторизован"
        }), 401

    if user["id"] == user_id:
        return jsonify({
            "error": "Нельзя оставить отзыв самому себе"
        }), 400

    data = request.get_json(silent=True) or {}

    rating = data.get("rating")
    comment = str(
        data.get("comment", "")
    ).strip()

    job_id = data.get("job_id")

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({
            "error": "Оценка должна быть от 1 до 5"
        }), 400

    if rating < 1 or rating > 5:
        return jsonify({
            "error": "Оценка должна быть от 1 до 5"
        }), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM users WHERE id = ?",
        (user_id,)
    )

    if not cursor.fetchone():
        conn.close()

        return jsonify({
            "error": "Пользователь не найден"
        }), 404

    if job_id:
        cursor.execute(
            "SELECT id FROM jobs WHERE id = ?",
            (job_id,)
        )

        if not cursor.fetchone():
            conn.close()

            return jsonify({
                "error": "Задание не найдено"
            }), 404

    try:
        cursor.execute("""
            INSERT INTO reviews (
                from_user_id,
                to_user_id,
                job_id,
                rating,
                comment
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            user["id"],
            user_id,
            job_id,
            rating,
            comment
        ))

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        return jsonify({
            "error": "Вы уже оставляли отзыв"
        }), 409

    conn.close()

    recalculate_rating(user_id)

    return jsonify({
        "status": "ok"
    }), 201


# ============================================================
# PWA
# ============================================================

@app.route("/manifest.json")
def manifest():
    response = jsonify({
        "name": "Near Gig",
        "short_name": "Near Gig",
        "description": "Поиск подработки рядом с вами",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#ffffff",
        "theme_color": "#6366F1",
        "icons": [
            {
                "src": DEFAULT_APP_ICON,
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    })

    response.headers["Cache-Control"] = "no-cache"

    return response


@app.route("/sw.js")
def service_worker():
    js = """
self.addEventListener("install", function(event) {
    self.skipWaiting();
});

self.addEventListener("activate", function(event) {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", function(event) {
    event.respondWith(
        fetch(event.request).catch(function() {
            return new Response(
                "Нет подключения к интернету",
                {
                    status: 503,
                    headers: {
                        "Content-Type": "text/plain; charset=utf-8"
                    }
                }
            );
        })
    );
});
"""

    response = make_response(js)

    response.headers[
        "Content-Type"
    ] = "application/javascript; charset=utf-8"

    return response


# ============================================================
# FRONTEND
# ============================================================

@app.route("/")
def index():
    html = r"""
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

    <title>Near Gig</title>

    <meta
        name="theme-color"
        content="#6366F1"
    >

    <meta
        name="mobile-web-app-capable"
        content="yes"
    >

    <meta
        name="apple-mobile-web-app-capable"
        content="yes"
    >

    <link
        rel="manifest"
        href="/manifest.json"
    >

    <link
        rel="apple-touch-icon"
        href="https://cdn-icons-png.flaticon.com/512/1041/1041916.png"
    >

    <script
        src="https://api-maps.yandex.ru/2.1/?apikey=__YANDEX_KEY__&lang=ru_RU"
    ></script>

    <script src="https://cdn.tailwindcss.com"></script>

    <style>
        * {
            -webkit-tap-highlight-color: transparent;
            box-sizing: border-box;
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
                sans-serif;
        }

        body {
            overscroll-behavior: none;
        }

        #map {
            width: 100%;
            height: 100%;
        }

        .tab-active {
            color: #6366F1 !important;
        }

        .custom-locate-btn {
            position: absolute;
            top: 75px;
            right: 12px;
            z-index: 1000;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,.2);
            border: none;
            width: 44px;
            height: 44px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 20px;
        }

        .modal {
            animation: fadeIn .2s ease;
        }

        @keyframes fadeIn {
            from {
                opacity: 0;
            }

            to {
                opacity: 1;
            }
        }

        .settings-section {
            background: white;
            border-radius: 14px;
            margin-bottom: 16px;
            overflow: hidden;
            border: 1px solid #f0f0f0;
        }

        .settings-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 15px 16px;
            border-bottom: 1px solid #f0f0f0;
        }

        .settings-item:last-child {
            border-bottom: none;
        }

        .settings-label {
            font-size: 16px;
            color: #1a1a1a;
        }

        .settings-sub {
            font-size: 13px;
            color: #8e8e93;
            margin-top: 2px;
        }

        .toggle {
            position: relative;
            width: 51px;
            height: 31px;
            flex-shrink: 0;
        }

        .toggle input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            cursor: pointer;
            inset: 0;
            background: #e9e9ea;
            border-radius: 31px;
            transition: .25s;
        }

        .toggle-slider:before {
            content: "";
            position: absolute;
            width: 27px;
            height: 27px;
            left: 2px;
            bottom: 2px;
            background: white;
            border-radius: 50%;
            transition: .25s;
            box-shadow: 0 2px 4px rgba(0,0,0,.2);
        }

        .toggle input:checked + .toggle-slider {
            background: #34c759;
        }

        .toggle input:checked + .toggle-slider:before {
            transform: translateX(20px);
        }

        .dark {
            background: #111827 !important;
            color: #f9fafb !important;
        }

        .dark .settings-section,
        .dark .bg-white {
            background: #1f2937 !important;
            color: #f9fafb !important;
        }

        .dark .settings-label {
            color: #f9fafb;
        }

        .dark .settings-item {
            border-color: #374151;
        }

        .dark .text-gray-500,
        .dark .text-gray-400 {
            color: #9ca3af !important;
        }

        .dark input,
        .dark textarea,
        .dark select {
            background: #111827;
            color: white;
            border-color: #374151;
        }

        .bottom-nav {
            padding-bottom: env(safe-area-inset-bottom);
        }

        .hidden-screen {
            display: none !important;
        }

        .job-card {
            transition: transform .15s ease;
        }

        .job-card:active {
            transform: scale(.98);
        }

        .toast {
            position: fixed;
            left: 50%;
            bottom: 90px;
            transform: translateX(-50%);
            z-index: 9999;
            background: rgba(20,20,20,.92);
            color: white;
            padding: 12px 18px;
            border-radius: 12px;
            font-size: 14px;
            max-width: calc(100% - 30px);
            text-align: center;
            animation: toastIn .2s ease;
        }

        @keyframes toastIn {
            from {
                opacity: 0;
                transform:
                    translateX(-50%)
                    translateY(10px);
            }

            to {
                opacity: 1;
                transform:
                    translateX(-50%)
                    translateY(0);
            }
        }
    </style>
</head>

<body class="bg-white">

    <!-- HEADER -->

    <header
        id="header"
        class="fixed top-0 left-0 right-0 z-50 bg-white border-b px-4 py-3 flex justify-between items-center"
    >
        <div>
            <h1 class="text-xl font-bold text-gray-900">
                Near Gig
            </h1>

            <p
                id="headerSubtitle"
                class="text-xs text-gray-400"
            >
                Подработка рядом
            </p>
        </div>

        <div class="flex gap-3 items-center">

            <button
                id="loginBtn"
                onclick="openAuth()"
                class="text-sm text-indigo-600 font-medium px-3 py-2 rounded-full border border-indigo-200"
            >
                Войти
            </button>

            <div
                id="userMenu"
                class="hidden relative"
            >
                <button
                    id="profileBtn"
                    class="w-9 h-9 rounded-full bg-gray-200 overflow-hidden"
                >
                    <img
                        id="avatarImg"
                        src="https://cdn-icons-png.flaticon.com/512/149/149071.png"
                        class="w-full h-full object-cover"
                    >
                </button>

                <div
                    id="dropdownMenu"
                    class="hidden absolute right-0 top-11 bg-white shadow-xl rounded-xl py-2 w-52 border z-[9999]"
                >
                    <button
                        onclick="showMyJobs(); closeDropdown();"
                        class="w-full text-left px-4 py-3 text-sm hover:bg-gray-50"
                    >
                        📋 Мои задания
                    </button>

                    <button
                        onclick="showFavorites(); closeDropdown();"
                        class="w-full text-left px-4 py-3 text-sm hover:bg-gray-50"
                    >
                        ❤️ Избранное
                    </button>

                    <button
                        onclick="showProfile(); closeDropdown();"
                        class="w-full text-left px-4 py-3 text-sm hover:bg-gray-50"
                    >
                        👤 Профиль
                    </button>

                    <hr class="my-1">

                    <button
                        onclick="logout(); closeDropdown();"
                        class="w-full text-left px-4 py-3 text-sm text-red-500 hover:bg-gray-50"
                    >
                        Выйти
                    </button>
                </div>
            </div>
        </div>
    </header>


    <!-- MAP -->

    <main
        id="map"
        class="w-full h-full"
    ></main>

    <button
        id="manualLocateBtn"
        class="custom-locate-btn"
        title="Моё местоположение"
    >
        📍
    </button>


    <!-- BOTTOM NAV -->

    <nav
        class="bottom-nav fixed bottom-0 left-0 right-0 z-50 bg-white border-t px-2 pt-2 flex justify-around"
    >

        <button
            onclick="switchTab('map')"
            id="tabMap"
            class="tab-active flex flex-col items-center text-xs pb-2 px-3"
        >
            <span class="text-xl">🗺️</span>
            Карта
        </button>

        <button
            onclick="switchTab('add')"
            id="tabAdd"
            class="flex flex-col items-center text-xs text-gray-500 pb-2 px-3"
        >
            <span class="text-xl">➕</span>
            Создать
        </button>

        <button
            onclick="switchTab('list')"
            id="tabList"
            class="flex flex-col items-center text-xs text-gray-500 pb-2 px-3"
        >
            <span class="text-xl">📋</span>
            Задания
        </button>

        <button
            onclick="switchTab('profile')"
            id="tabProfile"
            class="flex flex-col items-center text-xs text-gray-500 pb-2 px-3"
        >
            <span class="text-xl">👤</span>
            Профиль
        </button>

    </nav>


    <!-- AUTH MODAL -->

    <div
        id="authModal"
        class="hidden fixed inset-0 z-[2000] bg-black/50 flex items-center justify-center p-4 modal"
    >
        <div class="bg-white rounded-2xl p-6 w-full max-w-md">

            <h2
                class="text-xl font-bold mb-4 text-center"
                id="authTitle"
            >
                Вход
            </h2>

            <form
                id="authForm"
                class="space-y-3"
            >

                <input
                    type="email"
                    id="authEmail"
                    placeholder="Email"
                    class="w-full px-4 py-3 border rounded-xl"
                    autocomplete="email"
                    required
                >

                <input
                    type="password"
                    id="authPassword"
                    placeholder="Пароль"
                    class="w-full px-4 py-3 border rounded-xl"
                    autocomplete="current-password"
                    required
                >

                <input
                    type="text"
                    id="authName"
                    placeholder="Ваше имя"
                    class="w-full px-4 py-3 border rounded-xl hidden"
                    autocomplete="name"
                >

                <select
                    id="authRole"
                    class="w-full px-4 py-3 border rounded-xl hidden"
                >
                    <option value="executor">
                        Я ищу подработку
                    </option>

                    <option value="customer">
                        Я ищу исполнителя
                    </option>
                </select>

                <button
                    type="submit"
                    class="w-full bg-indigo-600 text-white py-3 rounded-xl font-medium"
                >
                    Войти
                </button>

            </form>

            <p class="text-center text-sm mt-3">

                <span id="authSwitchText">
                    Нет аккаунта?
                </span>

                <button
                    id="authSwitchBtn"
                    class="text-indigo-600 font-medium"
                >
                    Зарегистрироваться
                </button>

            </p>

            <button
                onclick="closeAuth()"
                class="mt-3 w-full py-2 text-gray-400"
            >
                Отмена
            </button>

        </div>
    </div>


    <!-- CREATE JOB MODAL -->

    <div
        id="jobFormModal"
        class="hidden fixed inset-0 z-[2000] bg-black/50 flex items-center justify-center p-4 modal"
    >
        <div class="bg-white rounded-2xl p-6 w-full max-w-md">

            <h2 class="text-xl font-bold mb-4">
                Новая подработка
            </h2>

            <input
                id="jobTitle"
                placeholder="Название"
                maxlength="150"
                class="w-full px-4 py-3 border rounded-xl mb-2"
            >

            <textarea
                id="jobDesc"
                placeholder="Описание"
                maxlength="2000"
                class="w-full px-4 py-3 border rounded-xl mb-2"
                rows="4"
            ></textarea>

            <input
                id="jobPrice"
                type="number"
                min="1"
                step="0.01"
                placeholder="Цена, ₽"
                class="w-full px-4 py-3 border rounded-xl mb-2"
            >

            <select
                id="jobCategory"
                class="w-full px-4 py-3 border rounded-xl mb-2"
            >
                <option>Курьер</option>
                <option>Уборка</option>
                <option>Ремонт</option>
                <option>Строительство</option>
                <option>IT</option>
                <option>Дизайн</option>
                <option>Помощь по дому</option>
                <option>Авто</option>
                <option>Другое</option>
            </select>

            <div
                class="bg-indigo-50 rounded-xl p-3 mb-3"
            >
                <p
                    id="coordsInfo"
                    class="text-sm text-indigo-700"
                >
                    Нажмите на карте, чтобы выбрать место
                </p>
            </div>

            <button
                onclick="createJob()"
                class="w-full bg-indigo-600 text-white py-3 rounded-xl font-medium mb-2"
            >
                Опубликовать
            </button>

            <button
                onclick="closeJobForm()"
                class="w-full py-2 text-gray-400"
            >
                Отмена
            </button>

        </div>
    </div>


    <!-- LIST MODAL -->

    <div
        id="listModal"
        class="hidden fixed inset-0 z-[1500] bg-white overflow-y-auto"
    >

        <div class="p-4 pb-24">

            <div class="flex justify-between items-center mb-4">

                <div>
                    <h2 class="text-xl font-bold">
                        Все задания
                    </h2>

                    <p class="text-xs text-gray-400">
                        Найдите подработку рядом
                    </p>
                </div>

                <button
                    onclick="closeList()"
                    class="text-gray-500 text-2xl"
                >
                    ×
                </button>

            </div>

            <div class="mb-3">
                <input
                    id="searchJobs"
                    oninput="debouncedLoadJobsList()"
                    placeholder="🔎 Поиск задания..."
                    class="w-full px-4 py-3 border rounded-xl"
                >
            </div>

            <div
                class="flex gap-2 overflow-x-auto pb-3"
                id="categoryFilters"
            >
                <button
                    onclick="setCategory('')"
                    class="category-btn bg-indigo-600 text-white px-3 py-2 rounded-full text-xs whitespace-nowrap"
                    data-category=""
                >
                    Все
                </button>

                <button
                    onclick="setCategory('Курьер')"
                    class="category-btn bg-gray-100 px-3 py-2 rounded-full text-xs whitespace-nowrap"
                    data-category="Курьер"
                >
                    Курьер
                </button>

                <button
                    onclick="setCategory('Уборка')"
                    class="category-btn bg-gray-100 px-3 py-2 rounded-full text-xs whitespace-nowrap"
                    data-category="Уборка"
                >
                    Уборка
                </button>

                <button
                    onclick="setCategory('Ремонт')"
                    class="category-btn bg-gray-100 px-3 py-2 rounded-full text-xs whitespace-nowrap"
                    data-category="Ремонт"
                >
                    Ремонт
                </button>

                <button
                    onclick="setCategory('IT')"
                    class="category-btn bg-gray-100 px-3 py-2 rounded-full text-xs whitespace-nowrap"
                    data-category="IT"
                >
                    IT
                </button>
            </div>

            <div
                id="jobsList"
                class="space-y-3"
            ></div>

        </div>
    </div>


    <!-- PROFILE -->

    <div
        id="profileModal"
        class="hidden fixed inset-0 z-[1600] bg-white overflow-y-auto"
    >

        <div class="p-4 pb-24">

            <div class="flex justify-between items-center mb-4">

                <h2 class="text-xl font-bold">
                    Профиль
                </h2>

                <button
                    onclick="closeProfile()"
                    class="text-gray-500 text-2xl"
                >
                    ×
                </button>

            </div>

            <div id="profileContent"></div>

        </div>
    </div>


    <!-- SETTINGS -->

    <div
        id="settingsModal"
        class="hidden fixed inset-0 z-[1700] bg-white overflow-y-auto"
    >

        <div class="p-4 pb-24">

            <div id="settingsContent"></div>

        </div>
    </div>


    <!-- JOB DETAIL -->

    <div
        id="jobDetailModal"
        class="hidden fixed inset-0 z-[1800] bg-white overflow-y-auto"
    >

        <div class="p-4 pb-24">

            <div class="flex justify-between items-center mb-4">

                <h2
                    class="text-xl font-bold pr-3"
                    id="detailTitle"
                ></h2>

                <button
                    onclick="closeJobDetail()"
                    class="text-gray-500 text-2xl"
                >
                    ×
                </button>

            </div>

            <div id="detailContent"></div>

        </div>
    </div>


    <script>
        // ====================================================
        // GLOBAL STATE
        // ====================================================

        let myMap = null;
        let currentUser = null;
        let authToken = null;

        let selectedCoords = null;
        let tempPlacemark = null;

        let currentCategory = "";
        let searchTimer = null;

        let settings = {
            mapLayer: "hybrid",
            darkMode: false,
            notifications: true
        };


        // ====================================================
        // SETTINGS
        // ====================================================

        function loadSettings() {
            try {
                const saved =
                    localStorage.getItem("neargig_settings");

                if (saved) {
                    settings = {
                        ...settings,
                        ...JSON.parse(saved)
                    };
                }
            } catch (e) {
                console.error(e);
            }

            applyDarkMode();
        }


        function saveSettings() {
            localStorage.setItem(
                "neargig_settings",
                JSON.stringify(settings)
            );
        }


        function applyDarkMode() {
            document.body.classList.toggle(
                "dark",
                !!settings.darkMode
            );
        }


        loadSettings();


        // ====================================================
        // TOAST
        // ====================================================

        function toast(message) {
            const old =
                document.querySelector(".toast");

            if (old) old.remove();

            const el =
                document.createElement("div");

            el.className = "toast";
            el.textContent = message;

            document.body.appendChild(el);

            setTimeout(() => {
                el.remove();
            }, 2500);
        }


        // ====================================================
        // MAP
        // ====================================================

        ymaps.ready(() => {

            const mapType =
                settings.mapLayer === "hybrid"
                    ? "yandex#hybrid"
                    : "yandex#map";

            myMap = new ymaps.Map(
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

            loadJobsOnMap();

            myMap.events.add(
                "click",
                event => {

                    const form =
                        document.getElementById(
                            "jobFormModal"
                        );

                    if (
                        form.classList.contains(
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

        });


        function setTempMarker(coords) {

            if (tempPlacemark) {
                myMap.geoObjects.remove(
                    tempPlacemark
                );
            }

            tempPlacemark =
                new ymaps.Placemark(
                    coords,
                    {
                        balloonContent:
                            "Место нового задания"
                    },
                    {
                        preset:
                            "islands#redIcon"
                    }
                );

            myMap.geoObjects.add(
                tempPlacemark
            );

            selectedCoords = coords;

            document.getElementById(
                "coordsInfo"
            ).textContent =
                "📍 Место выбрано";
        }


        async function loadJobsOnMap(
            filters = {}
        ) {
            if (!myMap) return;

            myMap.geoObjects.each(
                object => {
                    if (
                        object !== tempPlacemark
                    ) {
                        myMap.geoObjects.remove(
                            object
                        );
                    }
                }
            );

            try {

                const params =
                    new URLSearchParams(filters);

                const response =
                    await fetch(
                        "/api/jobs?" +
                        params.toString()
                    );

                const jobs =
                    await response.json();

                if (!Array.isArray(jobs)) {
                    return;
                }

                jobs.forEach(job => {

                    if (
                        job.lat === null ||
                        job.lng === null
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
                                    <div style="min-width:220px">
                                        <b>${escapeHtml(job.title)}</b>
                                        <br>
                                        💰 ${Number(job.price).toLocaleString("ru-RU")} ₽
                                        <br>
                                        👤 ${escapeHtml(job.author.name)}
                                        <br>
                                        ⭐ ${Number(job.author.rating || 0).toFixed(1)}
                                        <br><br>
                                        <button
                                            onclick="showJobDetail(${job.id})"
                                            style="
                                                background:#6366F1;
                                                color:white;
                                                border:0;
                                                padding:8px 12px;
                                                border-radius:8px;
                                                cursor:pointer
                                            "
                                        >
                                            Подробнее
                                        </button>
                                    </div>
                                    `
                            },
                            {
                                preset:
                                    "islands#blueIcon"
                            }
                        );

                    myMap.geoObjects.add(
                        placemark
                    );
                });

            } catch (error) {
                console.error(error);
            }
        }


        // ====================================================
        // NAVIGATION
        // ====================================================

        function switchTab(tab) {

            document
                .querySelectorAll(
                    '[id^="tab"]'
                )
                .forEach(button => {
                    button.classList.remove(
                        "tab-active"
                    );
                    button.classList.add(
                        "text-gray-500"
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
                    "tab-active"
                );
                tabButton.classList.remove(
                    "text-gray-500"
                );
            }

            if (tab === "map") {
                closeAllScreens();
                return;
            }

            if (tab === "add") {

                if (!currentUser) {
                    openAuth();
                    return;
                }

                openJobForm();
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


        function closeAllScreens() {
            [
                "listModal",
                "profileModal",
                "settingsModal",
                "jobDetailModal",
                "jobFormModal"
            ].forEach(id => {
                document
                    .getElementById(id)
                    .classList.add("hidden");
            });
        }


        // ====================================================
        // JOB LIST
        // ====================================================

        function debouncedLoadJobsList() {

            clearTimeout(searchTimer);

            searchTimer = setTimeout(
                loadJobsList,
                300
            );
        }


        function setCategory(category) {

            currentCategory = category;

            document
                .querySelectorAll(".category-btn")
                .forEach(button => {

                    const active =
                        button.dataset.category ===
                        category;

                    button.classList.toggle(
                        "bg-indigo-600",
                        active
                    );

                    button.classList.toggle(
                        "text-white",
                        active
                    );

                    button.classList.toggle(
                        "bg-gray-100",
                        !active
                    );
                });

            loadJobsList();
        }


        async function loadJobsList() {

            const list =
                document.getElementById(
                    "jobsList"
                );

            list.innerHTML = `
                <div class="text-center text-gray-400 py-10">
                    Загрузка...
                </div>
            `;

            const search =
                document.getElementById(
                    "searchJobs"
                )?.value.trim() || "";

            const params =
                new URLSearchParams();

            if (currentCategory) {
                params.set(
                    "category",
                    currentCategory
                );
            }

            if (search) {
                params.set(
                    "search",
                    search
                );
            }

            try {

                const response =
                    await fetch(
                        "/api/jobs?" +
                        params.toString()
                    );

                const jobs =
                    await response.json();

                if (
                    !Array.isArray(jobs)
                ) {
                    list.innerHTML = `
                        <p class="text-red-500">
                            Не удалось загрузить задания
                        </p>
                    `;

                    return;
                }

                if (jobs.length === 0) {
                    list.innerHTML = `
                        <div class="text-center py-12">
                            <div class="text-5xl mb-3">
                                🔎
                            </div>

                            <p class="font-medium">
                                Заданий пока нет
                            </p>

                            <p class="text-sm text-gray-400 mt-1">
                                Попробуйте изменить поиск
                            </p>
                        </div>
                    `;

                } else {

                    list.innerHTML =
                        jobs.map(
                            renderJobCard
                        ).join("");
                }

                document
                    .getElementById(
                        "listModal"
                    )
                    .classList.remove(
                        "hidden"
                    );

            } catch (error) {

                console.error(error);

                list.innerHTML = `
                    <p class="text-red-500">
                        Ошибка загрузки
                    </p>
                `;
            }
        }


        function renderJobCard(job) {

            const distance =
                job.distance !== undefined
                    ? `
                        <span>
                            📍 ${job.distance} км
                        </span>
                    `
                    : "";

            return `
                <div
                    class="job-card bg-white border rounded-2xl p-4 cursor-pointer shadow-sm"
                    onclick="showJobDetail(${job.id})"
                >

                    <div class="flex justify-between gap-3">

                        <h3 class="font-bold text-gray-900">
                            ${escapeHtml(job.title)}
                        </h3>

                        <span class="text-indigo-600 font-bold whitespace-nowrap">
                            ${Number(job.price).toLocaleString("ru-RU")} ₽
                        </span>

                    </div>

                    <p class="text-sm text-gray-500 mt-2 line-clamp-3">
                        ${escapeHtml(job.description || "Без описания")}
                    </p>

                    <div class="flex justify-between gap-2 mt-3 text-xs text-gray-400">

                        <span>
                            ${escapeHtml(job.category)}
                            ·
                            ${escapeHtml(job.author.name)}
                        </span>

                        ${distance}

                    </div>

                </div>
            `;
        }


        // ====================================================
        // JOB DETAIL
        // ====================================================

        async function showJobDetail(jobId) {

            try {

                const response =
                    await fetch(
                        "/api/jobs/" + jobId
                    );

                const job =
                    await response.json();

                if (!response.ok) {
                    toast(
                        job.error ||
                        "Задание не найдено"
                    );

                    return;
                }

                document.getElementById(
                    "detailTitle"
                ).textContent =
                    job.title;

                let actions = "";

                if (
                    currentUser &&
                    currentUser.id !== job.user_id
                ) {

                    actions = `
                        <button
                            onclick="respondToJob(${job.id})"
                            class="w-full bg-green-500 text-white py-3 rounded-xl mb-2 font-medium"
                        >
                            💬 Откликнуться
                        </button>

                        <button
                            id="favoriteBtn"
                            onclick="toggleFav(${job.id})"
                            class="w-full bg-gray-100 py-3 rounded-xl font-medium"
                        >
                            ❤️ В избранное
                        </button>
                    `;

                    checkFavorite(job.id);
                }

                if (
                    currentUser &&
                    currentUser.id === job.user_id
                ) {

                    actions = `
                        <div class="bg-indigo-50 rounded-xl p-3 mb-3 text-sm text-indigo-700">
                            Это ваше задание.
                        </div>

                        <div class="grid grid-cols-2 gap-2">

                            <button
                                onclick="changeJobStatus(${job.id}, 'completed')"
                                class="bg-green-500 text-white py-3 rounded-xl"
                            >
                                Завершить
                            </button>

                            <button
                                onclick="changeJobStatus(${job.id}, 'cancelled')"
                                class="bg-red-100 text-red-600 py-3 rounded-xl"
                            >
                                Отменить
                            </button>

                        </div>
                    `;
                }

                const responses =
                    job.responses || [];

                const reviews =
                    job.reviews || [];

                document.getElementById(
                    "detailContent"
                ).innerHTML = `

                    <div class="mb-4">

                        <div class="text-3xl font-bold text-indigo-600 mb-2">
                            ${Number(job.price).toLocaleString("ru-RU")} ₽
                        </div>

                        <p class="text-gray-600 whitespace-pre-wrap">
                            ${escapeHtml(job.description || "Без описания")}
                        </p>

                    </div>

                    <div class="grid grid-cols-2 gap-2 mb-4">

                        <div class="bg-gray-50 rounded-xl p-3">
                            <div class="text-xs text-gray-400">
                                Категория
                            </div>

                            <div class="font-medium mt-1">
                                ${escapeHtml(job.category)}
                            </div>
                        </div>

                        <div class="bg-gray-50 rounded-xl p-3">
                            <div class="text-xs text-gray-400">
                                Просмотры
                            </div>

                            <div class="font-medium mt-1">
                                👁 ${job.views}
                            </div>
                        </div>

                    </div>

                    <div class="flex items-center gap-3 mb-4 p-3 border rounded-xl">

                        <img
                            src="${escapeAttr(job.author.avatar)}"
                            class="w-12 h-12 rounded-full object-cover"
                        >

                        <div>
                            <div class="font-bold">
                                ${escapeHtml(job.author.name)}
                            </div>

                            <div class="text-sm text-gray-500">
                                ⭐ ${Number(job.author.rating || 0).toFixed(1)}
                                · ${job.author.reviews_count || 0} отзывов
                            </div>
                        </div>

                    </div>

                    ${actions}

                    ${
                        currentUser &&
                        currentUser.id === job.user_id
                            ? `
                                <h3 class="font-bold mt-6 mb-2">
                                    Отклики (${responses.length})
                                </h3>

                                ${
                                    responses.length
                                        ? responses.map(
                                            renderResponse
                                          ).join("")
                                        : `
                                            <p class="text-gray-400 text-sm">
                                                Пока никто не откликнулся.
                                            </p>
                                        `
                                }
                            `
                            : ""
                    }

                    ${
                        reviews.length
                            ? `
                                <h3 class="font-bold mt-6 mb-2">
                                    Отзывы
                                </h3>

                                ${reviews.map(
                                    renderReview
                                ).join("")}
                            `
                            : ""
                    }

                `;

                document
                    .getElementById(
                        "jobDetailModal"
                    )
                    .classList.remove(
                        "hidden"
                    );

            } catch (error) {

                console.error(error);

                toast(
                    "Ошибка загрузки задания"
                );
            }
        }


        function renderResponse(response) {

            return `
                <div class="border rounded-xl p-3 mb-2">

                    <div class="flex items-center gap-2">

                        <img
                            src="${escapeAttr(response.avatar_url || "https://cdn-icons-png.flaticon.com/512/149/149071.png")}"
                            class="w-9 h-9 rounded-full"
                        >

                        <div>
                            <div class="font-medium">
                                ${escapeHtml(response.name)}
                            </div>

                            <div class="text-xs text-gray-400">
                                ⭐ ${Number(response.rating || 0).toFixed(1)}
                            </div>
                        </div>

                    </div>

                    <p class="text-sm text-gray-600 mt-2">
                        ${escapeHtml(response.message || "Без сообщения")}
                    </p>

                    <div class="flex gap-2 mt-3">

                        <button
                            onclick="changeResponseStatus(${response.id}, 'accepted')"
                            class="flex-1 bg-green-100 text-green-700 py-2 rounded-lg text-sm"
                        >
                            Принять
                        </button>

                        <button
                            onclick="changeResponseStatus(${response.id}, 'rejected')"
                            class="flex-1 bg-red-100 text-red-700 py-2 rounded-lg text-sm"
                        >
                            Отклонить
                        </button>

                    </div>

                </div>
            `;
        }


        function renderReview(review) {

            return `
                <div class="border rounded-xl p-3 mb-2">

                    <div class="flex items-center gap-2">

                        <img
                            src="${escapeAttr(review.avatar_url || "https://cdn-icons-png.flaticon.com/512/149/149071.png")}"
                            class="w-8 h-8 rounded-full"
                        >

                        <div class="font-medium">
                            ${escapeHtml(review.name)}
                        </div>

                        <div class="ml-auto">
                            ${"⭐".repeat(Number(review.rating || 0))}
                        </div>

                    </div>

                    ${
                        review.comment
                            ? `
                                <p class="text-sm text-gray-600 mt-2">
                                    ${escapeHtml(review.comment)}
                                </p>
                            `
                            : ""
                    }

                </div>
            `;
        }


        function closeJobDetail() {
            document
                .getElementById(
                    "jobDetailModal"
                )
                .classList.add(
                    "hidden"
                );
        }


        // ====================================================
        // RESPONSES ACTIONS
        // ====================================================

        async function respondToJob(jobId) {

            if (!currentUser) {
                openAuth();
                return;
            }

            const message =
                prompt(
                    "Сообщение для заказчика:"
                );

            if (message === null) {
                return;
            }

            try {

                const response =
                    await fetch(
                        `/api/jobs/${jobId}/respond`,
                        {
                            method: "POST",
                            headers: {
                                "Content-Type":
                                    "application/json",

                                "Authorization":
                                    "Bearer " +
                                    authToken
                            },

                            body: JSON.stringify({
                                message
                            })
                        }
                    );

                const data =
                    await response.json();

                if (!response.ok) {
                    toast(
                        data.error ||
                        "Не удалось отправить отклик"
                    );

                    return;
                }

                toast(
                    "Отклик отправлен!"
                );

                showJobDetail(jobId);

            } catch (error) {

                console.error(error);

                toast(
                    "Ошибка отправки отклика"
                );
            }
        }


        async function changeResponseStatus(
            responseId,
            status
        ) {

            try {

                const response =
                    await fetch(
                        `/api/responses/${responseId}/status`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json",

                                "Authorization":
                                    "Bearer " +
                                    authToken
                            },

                            body: JSON.stringify({
                                status
                            })
                        }
                    );

                const data =
                    await response.json();

                if (!response.ok) {
                    toast(
                        data.error ||
                        "Ошибка"
                    );

                    return;
                }

                toast(
                    status === "accepted"
                        ? "Исполнитель принят"
                        : "Отклик отклонён"
                );

                closeJobDetail();

            } catch (error) {

                console.error(error);

                toast(
                    "Ошибка"
                );
            }
        }


        async function changeJobStatus(
            jobId,
            status
        ) {

            try {

                const response =
                    await fetch(
                        `/api/jobs/${jobId}/status`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json",

                                "Authorization":
                                    "Bearer " +
                                    authToken
                            },

                            body: JSON.stringify({
                                status
                            })
                        }
                    );

                const data =
                    await response.json();

                if (!response.ok) {
                    toast(
                        data.error ||
                        "Ошибка"
                    );

                    return;
                }

                toast(
                    status === "completed"
                        ? "Задание завершено"
                        : "Задание отменено"
                );

                closeJobDetail();
                loadJobsOnMap();

            } catch (error) {

                console.error(error);

                toast(
                    "Ошибка изменения статуса"
                );
            }
        }


        // ====================================================
        // FAVORITES
        // ====================================================

        async function toggleFav(jobId) {

            if (!currentUser) {
                openAuth();
                return;
            }

            try {

                const response =
                    await fetch(
                        `/api/favorites/${jobId}`,
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
                    toast(
                        data.error ||
                        "Ошибка"
                    );

                    return;
                }

                toast(
                    data.action === "added"
                        ? "❤️ Добавлено в избранное"
                        : "Удалено из избранного"
                );

                checkFavorite(jobId);

            } catch (error) {

                console.error(error);
            }
        }


        async function checkFavorite(jobId) {

            if (!currentUser) return;

            try {

                const response =
                    await fetch(
                        `/api/favorites/${jobId}`,
                        {
                            headers: {
                                "Authorization":
                                    "Bearer " +
                                    authToken
                            }
                        }
                    );

                const data =
                    await response.json();

                const button =
                    document.getElementById(
                        "favoriteBtn"
                    );

                if (!button) return;

                if (data.favorite) {
                    button.textContent =
                        "❤️ Убрать из избранного";

                    button.className =
                        "w-full bg-red-50 text-red-600 py-3 rounded-xl font-medium";

                } else {
                    button.textContent =
                        "❤️ В избранное";

                    button.className =
                        "w-full bg-gray-100 py-3 rounded-xl font-medium";
                }

            } catch (error) {
                console.error(error);
            }
        }


        // ====================================================
        // AUTH UI
        // ====================================================

        function openAuth() {

            document
                .getElementById(
                    "authModal"
                )
                .classList.remove(
                    "hidden"
                );

            setAuthMode(true);
        }


        function closeAuth() {

            document
                .getElementById(
                    "authModal"
                )
                .classList.add(
                    "hidden"
                );
        }


        function setAuthMode(login) {

            document.getElementById(
                "authTitle"
            ).textContent =
                login
                    ? "Вход"
                    : "Регистрация";

            document.getElementById(
                "authName"
            ).classList.toggle(
                "hidden",
                login
            );

            document.getElementById(
                "authRole"
            ).classList.toggle(
                "hidden",
                login
            );

            document.getElementById(
                "authSwitchText"
            ).textContent =
                login
                    ? "Нет аккаунта?"
                    : "Есть аккаунт?";

            document.getElementById(
                "authSwitchBtn"
            ).textContent =
                login
                    ? "Зарегистрироваться"
                    : "Войти";

            document.querySelector(
                "#authForm button[type='submit']"
            ).textContent =
                login
                    ? "Войти"
                    : "Зарегистрироваться";

            document.getElementById(
                "authPassword"
            ).autocomplete =
                login
                    ? "current-password"
                    : "new-password";
        }


        document
            .getElementById(
                "authSwitchBtn"
            )
            .addEventListener(
                "click",
                () => {

                    const login =
                        document
                            .getElementById(
                                "authTitle"
                            )
                            .textContent ===
                        "Вход";

                    setAuthMode(!login);
                }
            );


        document
            .getElementById(
                "authForm"
            )
            .addEventListener(
                "submit",
                async event => {

                    event.preventDefault();

                    const login =
                        document
                            .getElementById(
                                "authTitle"
                            )
                            .textContent ===
                        "Вход";

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
                            .value;

                    const body = {
                        email,
                        password
                    };

                    if (!login) {

                        const name =
                            document
                                .getElementById(
                                    "authName"
                                )
                                .value
                                .trim();

                        const role =
                            document
                                .getElementById(
                                    "authRole"
                                )
                                .value;

                        if (!name) {
                            toast(
                                "Введите имя"
                            );

                            return;
                        }

                        body.name = name;
                        body.role = role;
                    }

                    try {

                        const response =
                            await fetch(
                                login
                                    ? "/api/login"
                                    : "/api/register",
                                {
                                    method: "POST",

                                    headers: {
                                        "Content-Type":
                                            "application/json"
                                    },

                                    body:
                                        JSON.stringify(
                                            body
                                        )
                                }
                            );

                        const data =
                            await response.json();

                        if (!response.ok) {
                            toast(
                                data.error ||
                                "Ошибка"
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

                        toast(
                            login
                                ? "С возвращением!"
                                : "Аккаунт создан!"
                        );

                    } catch (error) {

                        console.error(error);

                        toast(
                            "Ошибка соединения"
                        );
                    }
                }
            );


        async function logout() {

            if (authToken) {
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
                } catch (e) {
                    console.error(e);
                }
            }

            currentUser = null;
            authToken = null;

            localStorage.removeItem(
                "token"
            );

            updateUI();

            closeAllScreens();

            toast(
                "Вы вышли из аккаунта"
            );
        }


        function updateUI() {

            document
                .getElementById(
                    "loginBtn"
                )
                .classList.toggle(
                    "hidden",
                    !!currentUser
                );

            document
                .getElementById(
                    "userMenu"
                )
                .classList.toggle(
                    "hidden",
                    !currentUser
                );

            if (currentUser) {

                document.getElementById(
                    "avatarImg"
                ).src =
                    currentUser.avatar_url ||
                    "https://cdn-icons-png.flaticon.com/512/149/149071.png";

                document.getElementById(
                    "headerSubtitle"
                ).textContent =
                    currentUser.name;
            } else {

                document.getElementById(
                    "headerSubtitle"
                ).textContent =
                    "Подработка рядом";
            }
        }


        // ====================================================
        // PROFILE
        // ====================================================

        async function showProfile() {

            if (!currentUser) {
                openAuth();
                return;
            }

            try {

                const [
                    jobsResponse,
                    favoritesResponse,
                    reviewsResponse
                ] = await Promise.all([
                    fetch(
                        `/api/jobs?user_id=${currentUser.id}`
                    ),
                    fetch(
                        "/api/favorites",
                        {
                            headers: {
                                "Authorization":
                                    "Bearer " +
                                    authToken
                            }
                        }
                    ),
                    fetch(
                        `/api/users/${currentUser.id}/reviews`
                    )
                ]);

                const myJobs =
                    await jobsResponse.json();

                const favorites =
                    await favoritesResponse.json();

                const reviews =
                    await reviewsResponse.json();

                document.getElementById(
                    "profileContent"
                ).innerHTML = `

                    <div class="flex items-center gap-4 mb-5">

                        <img
                            src="${escapeAttr(currentUser.avatar_url)}"
                            class="w-20 h-20 rounded-full object-cover"
                        >

                        <div>

                            <h3 class="font-bold text-xl">
                                ${escapeHtml(currentUser.name)}
                            </h3>

                            <p class="text-gray-500 mt-1">
                                ⭐ ${Number(currentUser.rating || 0).toFixed(1)}
                                · ${currentUser.reviews_count || 0} отзывов
                            </p>

                            <p class="text-gray-400 text-sm mt-1">
                                ${escapeHtml(currentUser.email)}
                            </p>

                        </div>

                    </div>

                    <div class="grid grid-cols-3 gap-2 mb-5">

                        <div class="bg-gray-50 rounded-xl p-3 text-center">
                            <div class="font-bold text-lg">
                                ${myJobs.length}
                            </div>

                            <div class="text-xs text-gray-400">
                                Заданий
                            </div>
                        </div>

                        <div class="bg-gray-50 rounded-xl p-3 text-center">
                            <div class="font-bold text-lg">
                                ${favorites.length}
                            </div>

                            <div class="text-xs text-gray-400">
                                Избранное
                            </div>
                        </div>

                        <div class="bg-gray-50 rounded-xl p-3 text-center">
                            <div class="font-bold text-lg">
                                ${currentUser.completed_jobs || 0}
                            </div>

                            <div class="text-xs text-gray-400">
                                Выполнено
                            </div>
                        </div>

                    </div>

                    <button
                        onclick="showSettings()"
                        class="w-full bg-gray-50 text-gray-700 py-3 rounded-xl mb-5"
                    >
                        ⚙️ Настройки
                    </button>

                    <h3 class="font-bold mb-2">
                        Мои задания
                    </h3>

                    ${
                        myJobs.length
                            ? myJobs.map(
                                job => `
                                    <div class="border rounded-xl p-3 mb-2">

                                        <div class="flex justify-between gap-2">

                                            <b>
                                                ${escapeHtml(job.title)}
                                            </b>

                                            <span class="text-indigo-600 font-bold">
                                                ${Number(job.price).toLocaleString("ru-RU")} ₽
                                            </span>

                                        </div>

                                        <div class="text-xs text-gray-400 mt-2">
                                            ${escapeHtml(job.category)}
                                            ·
                                            ${escapeHtml(job.status)}
                                        </div>

                                    </div>
                                `
                            ).join("")
                            : `
                                <p class="text-gray-400 text-sm">
                                    Вы пока не создали заданий.
                                </p>
                            `
                    }

                    <h3 class="font-bold mt-5 mb-2">
                        Избранное
                    </h3>

                    ${
                        favorites.length
                            ? favorites.map(
                                job => `
                                    <div
                                        onclick="showJobDetail(${job.id})"
                                        class="border rounded-xl p-3 mb-2 cursor-pointer"
                                    >
                                        <div class="flex justify-between">
                                            <b>
                                                ${escapeHtml(job.title)}
                                            </b>

                                            <span class="text-indigo-600 font-bold">
                                                ${Number(job.price).toLocaleString("ru-RU")} ₽
                                            </span>
                                        </div>
                                    </div>
                                `
                            ).join("")
                            : `
                                <p class="text-gray-400 text-sm">
                                    Избранных заданий пока нет.
                                </p>
                            `
                    }

                    <h3 class="font-bold mt-5 mb-2">
                        Мои отзывы
                    </h3>

                    ${
                        reviews.length
                            ? reviews.map(
                                renderReview
                            ).join("")
                            : `
                                <p class="text-gray-400 text-sm">
                                    Отзывов пока нет.
                                </p>
                            `
                    }

                `;

                document
                    .getElementById(
                        "profileModal"
                    )
                    .classList.remove(
                        "hidden"
                    );

            } catch (error) {

                console.error(error);

                toast(
                    "Не удалось загрузить профиль"
                );
            }
        }


        function closeProfile() {

            document
                .getElementById(
                    "profileModal"
                )
                .classList.add(
                    "hidden"
                );
        }


        async function showMyJobs() {

            if (!currentUser) {
                openAuth();
                return;
            }

            const jobs =
                await fetch(
                    `/api/jobs?user_id=${currentUser.id}`
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
                    ? jobs.map(
                        job => `
                            <div class="border rounded-xl p-3 mb-2">

                                <div class="flex justify-between">

                                    <b>
                                        ${escapeHtml(job.title)}
                                    </b>

                                    <span class="text-indigo-600 font-bold">
                                        ${Number(job.price).toLocaleString("ru-RU")} ₽
                                    </span>

                                </div>

                                <div class="text-xs text-gray-400 mt-2">
                                    ${escapeHtml(job.status)}
                                </div>

                            </div>
                        `
                    ).join("")
                    : `
                        <p class="text-gray-400">
                            Нет заданий
                        </p>
                    `;

            document
                .getElementById(
                    "jobDetailModal"
                )
                .classList.remove(
                    "hidden"
                );
        }


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
                    ? favorites.map(
                        job => `
                            <div
                                onclick="showJobDetail(${job.id})"
                                class="border rounded-xl p-3 mb-2 cursor-pointer"
                            >

                                <div class="flex justify-between">

                                    <b>
                                        ${escapeHtml(job.title)}
                                    </b>

                                    <span class="text-indigo-600 font-bold">
                                        ${Number(job.price).toLocaleString("ru-RU")} ₽
                                    </span>

                                </div>

                            </div>
                        `
                    ).join("")
                    : `
                        <p class="text-gray-400">
                            Нет избранных заданий
                        </p>
                    `;

            document
                .getElementById(
                    "jobDetailModal"
                )
                .classList.remove(
                    "hidden"
                );
        }


        // ====================================================
        // SETTINGS
        // ====================================================

        function showSettings() {

            document.getElementById(
                "settingsContent"
            ).innerHTML = `

                <button
                    onclick="closeSettings(); showProfile();"
                    class="text-indigo-600 mb-4"
                >
                    ← Профиль
                </button>

                <h2 class="text-2xl font-bold mb-5">
                    Настройки
                </h2>

                <div class="settings-section">

                    <h3 class="text-sm text-gray-500 px-4 pt-3 pb-1 uppercase">
                        Вид
                    </h3>

                    <div class="settings-item">

                        <div>
                            <div class="settings-label">
                                Гибридная карта
                            </div>

                            <div class="settings-sub">
                                Спутник с подписями
                            </div>
                        </div>

                        <label class="toggle">

                            <input
                                type="checkbox"
                                ${
                                    settings.mapLayer ===
                                    "hybrid"
                                        ? "checked"
                                        : ""
                                }
                                onchange="
                                    settings.mapLayer =
                                        this.checked
                                            ? 'hybrid'
                                            : 'map';

                                    saveSettings();

                                    location.reload();
                                "
                            >

                            <span class="toggle-slider"></span>

                        </label>

                    </div>


                    <div class="settings-item">

                        <div>
                            <div class="settings-label">
                                Тёмная тема
                            </div>

                            <div class="settings-sub">
                                Тёмный интерфейс
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
                                    applyDarkMode();
                                "
                            >

                            <span class="toggle-slider"></span>

                        </label>

                    </div>

                </div>


                <div class="settings-section">

                    <h3 class="text-sm text-gray-500 px-4 pt-3 pb-1 uppercase">
                        Уведомления
                    </h3>

                    <div class="settings-item">

                        <div>
                            <div class="settings-label">
                                Уведомления
                            </div>

                            <div class="settings-sub">
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

                    <h3 class="text-sm text-gray-500 px-4 pt-3 pb-1 uppercase">
                        Приложение
                    </h3>

                    <div class="settings-item">

                        <div class="settings-label">
                            Версия
                        </div>

                        <div class="text-gray-500">
                            1.1.0
                        </div>

                    </div>

                    <div class="settings-item">

                        <div class="settings-label">
                            Название
                        </div>

                        <div class="text-gray-500">
                            Near Gig
                        </div>

                    </div>

                </div>

            `;

            document
                .getElementById(
                    "settingsModal"
                )
                .classList.remove(
                    "hidden"
                );

            document
                .getElementById(
                    "profileModal"
                )
                .classList.add(
                    "hidden"
                );
        }


        function closeSettings() {

            document
                .getElementById(
                    "settingsModal"
                )
                .classList.add(
                    "hidden"
                );
        }


        // ====================================================
        // CREATE JOB
        // ====================================================

        function openJobForm() {

            document
                .getElementById(
                    "jobFormModal"
                )
                .classList.remove(
                    "hidden"
                );

            selectedCoords = null;

            document.getElementById(
                "coordsInfo"
            ).textContent =
                "Нажмите на карту, чтобы выбрать место";

            if (navigator.geolocation) {

                navigator.geolocation.getCurrentPosition(
                    position => {

                        const coords = [
                            position.coords.latitude,
                            position.coords.longitude
                        ];

                        if (myMap) {
                            myMap.setCenter(
                                coords,
                                15
                            );
                        }

                        setTempMarker(
                            coords
                        );
                    },
                    () => {},
                    {
                        enableHighAccuracy: true,
                        timeout: 7000
                    }
                );
            }
        }


        function closeJobForm() {

            document
                .getElementById(
                    "jobFormModal"
                )
                .classList.add(
                    "hidden"
                );

            if (
                tempPlacemark &&
                myMap
            ) {
                myMap.geoObjects.remove(
                    tempPlacemark
                );

                tempPlacemark = null;
            }

            selectedCoords = null;
        }


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
                toast(
                    "Введите название"
                );

                return;
            }

            if (!price || Number(price) <= 0) {
                toast(
                    "Введите корректную цену"
                );

                return;
            }

            if (!selectedCoords) {
                toast(
                    "Выберите место на карте"
                );

                return;
            }

            try {

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

                            body: JSON.stringify({
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
                    toast(
                        data.error ||
                        "Ошибка публикации"
                    );

                    return;
                }

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

                toast(
                    "Задание опубликовано!"
                );

            } catch (error) {

                console.error(error);

                toast(
                    "Ошибка соединения"
                );
            }
        }


        // ====================================================
        // GEOLOCATION
        // ====================================================

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
                        toast(
                            "Геолокация недоступна"
                        );

                        return;
                    }

                    navigator.geolocation.getCurrentPosition(
                        position => {

                            const coords = [
                                position.coords.latitude,
                                position.coords.longitude
                            ];

                            if (myMap) {
                                myMap.setCenter(
                                    coords,
                                    15
                                );
                            }
                        },
                        () => {
                            toast(
                                "Не удалось определить местоположение"
                            );
                        },
                        {
                            enableHighAccuracy: true,
                            timeout: 10000
                        }
                    );
                }
            );


        // ====================================================
        // DROPDOWN
        // ====================================================

        document
            .getElementById(
                "profileBtn"
            )
            .addEventListener(
                "click",
                () => {

                    document
                        .getElementById(
                            "dropdownMenu"
                        )
                        .classList.toggle(
                            "hidden"
                        );
                }
            );


        function closeDropdown() {
            document
                .getElementById(
                    "dropdownMenu"
                )
                .classList.add(
                    "hidden"
                );
        }


        document.addEventListener(
            "click",
            event => {

                const menu =
                    document.getElementById(
                        "dropdownMenu"
                    );

                const button =
                    document.getElementById(
                        "profileBtn"
                    );

                if (
                    menu &&
                    button &&
                    !menu.contains(
                        event.target
                    ) &&
                    !button.contains(
                        event.target
                    )
                ) {
                    menu.classList.add(
                        "hidden"
                    );
                }
            }
        );


        // ====================================================
        // SECURITY HELPERS
        // ====================================================

        function escapeHtml(value) {

            const div =
                document.createElement(
                    "div"
                );

            div.textContent =
                value == null
                    ? ""
                    : String(value);

            return div.innerHTML;
        }


        function escapeAttr(value) {
            return escapeHtml(value)
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }


        // ====================================================
        // RESTORE SESSION
        // ====================================================

        async function restoreSession() {

            const savedToken =
                localStorage.getItem(
                    "token"
                );

            if (!savedToken) {
                updateUI();
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
                                    savedToken
                            }
                        }
                    );

                if (!response.ok) {
                    throw new Error(
                        "Session expired"
                    );
                }

                const user =
                    await response.json();

                currentUser =
                    user;

                authToken =
                    savedToken;

                updateUI();

            } catch (error) {

                localStorage.removeItem(
                    "token"
                );

                currentUser = null;
                authToken = null;

                updateUI();
            }
        }


        restoreSession();


        // ====================================================
        // SERVICE WORKER
        // ====================================================

        if (
            "serviceWorker" in navigator
        ) {
            window.addEventListener(
                "load",
                () => {
                    navigator.serviceWorker
                        .register("/sw.js")
                        .catch(
                            error =>
                                console.error(
                                    "SW error:",
                                    error
                                )
                        );
                }
            );
        }

    </script>

</body>
</html>
"""

    html = html.replace(
        "__YANDEX_KEY__",
        YANDEX_MAPS_API_KEY
    )

    return html


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({
            "error": "Маршрут не найден"
        }), 404

    return error


@app.errorhandler(500)
def internal_error(error):
    if request.path.startswith("/api/"):
        return jsonify({
            "error": "Внутренняя ошибка сервера"
        }), 500

    return (
        "Внутренняя ошибка сервера",
        500
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
