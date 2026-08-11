import os
import sqlite3
import hashlib
import secrets
import math
import html
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, Response

# ============================================================
# Near Gig — single-file Flask application
# Backend + responsive mobile-first frontend + PWA
# ============================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

APP_URL = os.environ.get("APP_URL", "https://near-gig.onrender.com")
DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.environ.get("RENDER_DISK_MOUNT_PATH", "/opt/render/project/src"), "app.db")
)

DEFAULT_AVATAR = "https://cdn-icons-png.flaticon.com/512/149/149071.png"
APP_ICON = "https://cdn-icons-png.flaticon.com/512/1041/1041916.png"


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            address TEXT DEFAULT '',
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
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(job_id, user_id)
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

    c.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT DEFAULT 'info',
            title TEXT NOT NULL,
            message TEXT DEFAULT '',
            read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Safe migration for older database versions.
    for statement in [
        "ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'executor'",
        "ALTER TABLE users ADD COLUMN avatar_url TEXT DEFAULT ''",
        "ALTER TABLE jobs ADD COLUMN address TEXT DEFAULT ''",
    ]:
        try:
            c.execute(statement)
        except sqlite3.OperationalError:
            pass

    c.execute(
        "UPDATE users SET avatar_url = ? WHERE avatar_url IS NULL OR avatar_url = ''",
        (DEFAULT_AVATAR,)
    )

    conn.commit()
    conn.close()


init_db()


# ============================================================
# HELPERS
# ============================================================

def now_plus(days=30):
    return (datetime.utcnow() + timedelta(days=days)).isoformat()


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 120_000
    )
    return "pbkdf2$120000$" + salt.hex() + "$" + digest.hex()


def verify_password(password, stored):
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations)
        )
        return secrets.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def make_token():
    return secrets.token_urlsafe(48)


def auth_user():
    token = request.headers.get("Authorization", "")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return None

    conn = get_db()
    row = conn.execute("""
        SELECT u.*
        FROM users u
        JOIN sessions s ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > ?
    """, (token, datetime.utcnow().isoformat())).fetchone()
    conn.close()
    return dict(row) if row else None


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = auth_user()
        if not user:
            return jsonify({"error": "Необходима авторизация"}), 401
        return fn(user, *args, **kwargs)
    return wrapper


def public_user(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "phone": row["phone"] or "",
        "role": row["role"] or "executor",
        "avatar_url": row["avatar_url"] or DEFAULT_AVATAR,
        "rating": round(float(row["rating"] or 0), 1),
        "reviews_count": row["reviews_count"] or 0,
        "completed_jobs": row["completed_jobs"] or 0,
        "created_at": row["created_at"],
    }


def haversine(lat1, lng1, lat2, lng2):
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def validate_coords(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError
        return lat, lng
    except Exception:
        return None, None


def job_dict(row, current_user_id=None):
    d = dict(row)
    d["price"] = float(d["price"])
    d["lat"] = float(d["lat"])
    d["lng"] = float(d["lng"])
    d["author"] = {
        "id": d.pop("author_id"),
        "name": d.pop("author_name"),
        "rating": round(float(d.pop("author_rating") or 0), 1),
        "avatar": d.pop("author_avatar") or DEFAULT_AVATAR,
    }
    if current_user_id:
        d["is_favorite"] = bool(d.pop("favorite_id", None))
    else:
        d.pop("favorite_id", None)
    return d


# ============================================================
# AUTH API
# ============================================================

@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    name = str(data.get("name", "")).strip()
    role = data.get("role", "executor")

    if not email or not password or not name:
        return jsonify({"error": "Заполните имя, email и пароль"}), 400
    if len(password) < 6:
        return jsonify({"error": "Пароль должен содержать минимум 6 символов"}), 400
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "Некорректный email"}), 400
    if role not in ("executor", "customer"):
        role = "executor"

    conn = get_db()
    try:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            return jsonify({"error": "Этот email уже зарегистрирован"}), 409

        cur = conn.execute("""
            INSERT INTO users (email, password_hash, name, role, avatar_url)
            VALUES (?, ?, ?, ?, ?)
        """, (email, hash_password(password), name, role, DEFAULT_AVATAR))
        user_id = cur.lastrowid
        token = make_token()
        conn.execute("""
            INSERT INTO sessions (user_id, token, expires_at)
            VALUES (?, ?, ?)
        """, (user_id, token, now_plus(30)))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return jsonify({"token": token, "user": public_user(user)}), 201
    finally:
        conn.close()


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or not password:
        return jsonify({"error": "Введите email и пароль"}), 400

    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            return jsonify({"error": "Неверный email или пароль"}), 401

        token = make_token()
        conn.execute("""
            INSERT INTO sessions (user_id, token, expires_at)
            VALUES (?, ?, ?)
        """, (user["id"], token, now_plus(30)))
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), user["id"])
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        return jsonify({"token": token, "user": public_user(user)})
    finally:
        conn.close()


@app.post("/api/logout")
def logout():
    token = request.headers.get("Authorization", "")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.get("/api/me")
def me():
    user = auth_user()
    if not user:
        return jsonify({"error": "Не авторизован"}), 401
    return jsonify(public_user(user))


@app.patch("/api/me")
@require_auth
def update_me(user):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", user["name"])).strip()
    phone = str(data.get("phone", user["phone"] or "")).strip()
    avatar = str(data.get("avatar_url", user["avatar_url"] or DEFAULT_AVATAR)).strip()

    if not name:
        return jsonify({"error": "Имя не может быть пустым"}), 400
    if len(name) > 80 or len(phone) > 40:
        return jsonify({"error": "Слишком длинные данные"}), 400

    conn = get_db()
    conn.execute("""
        UPDATE users SET name = ?, phone = ?, avatar_url = ?
        WHERE id = ?
    """, (name, phone, avatar or DEFAULT_AVATAR, user["id"]))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    conn.close()
    return jsonify(public_user(row))


# ============================================================
# JOBS API
# ============================================================

@app.get("/api/jobs")
def get_jobs():
    category = request.args.get("category")
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "active")
    user_id = request.args.get("user_id", type=int)
    max_price = request.args.get("max_price", type=float)
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius = request.args.get("radius", type=float)
    limit = min(max(request.args.get("limit", 100, type=int), 1), 200)

    current = auth_user()
    current_id = current["id"] if current else None

    sql = """
        SELECT j.*,
               u.id AS author_id, u.name AS author_name,
               u.rating AS author_rating, u.avatar_url AS author_avatar,
               f.id AS favorite_id
        FROM jobs j
        JOIN users u ON u.id = j.user_id
        LEFT JOIN favorites f
          ON f.job_id = j.id AND f.user_id = ?
        WHERE 1=1
    """
    params = [current_id]

    if status and status != "all":
        sql += " AND j.status = ?"
        params.append(status)
    if category and category != "Все":
        sql += " AND j.category = ?"
        params.append(category)
    if user_id:
        sql += " AND j.user_id = ?"
        params.append(user_id)
    if max_price is not None:
        sql += " AND j.price <= ?"
        params.append(max_price)
    if search:
        sql += " AND (j.title LIKE ? OR j.description LIKE ? OR j.address LIKE ?)"
        q = "%" + search + "%"
        params += [q, q, q]

    sql += " ORDER BY j.created_at DESC LIMIT ?"
    params.append(limit)

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    result = []
    for row in rows:
        job = job_dict(row, current_id)
        if lat is not None and lng is not None and radius is not None:
            if job["lat"] is None or job["lng"] is None:
                continue
            distance = haversine(lat, lng, job["lat"], job["lng"])
            if distance > radius:
                continue
            job["distance"] = round(distance, 2)
        result.append(job)

    return jsonify(result)


@app.get("/api/jobs/<int:job_id>")
def get_job(job_id):
    current = auth_user()
    current_id = current["id"] if current else None

    conn = get_db()
    row = conn.execute("""
        SELECT j.*,
               u.id AS author_id, u.name AS author_name,
               u.rating AS author_rating, u.avatar_url AS author_avatar,
               f.id AS favorite_id
        FROM jobs j
        JOIN users u ON u.id = j.user_id
        LEFT JOIN favorites f
          ON f.job_id = j.id AND f.user_id = ?
        WHERE j.id = ?
    """, (current_id, job_id)).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Задание не найдено"}), 404

    conn.execute("UPDATE jobs SET views = views + 1 WHERE id = ?", (job_id,))

    responses = conn.execute("""
        SELECT r.id, r.message, r.status, r.created_at,
               u.id AS user_id, u.name, u.avatar_url, u.rating
        FROM responses r
        JOIN users u ON u.id = r.user_id
        WHERE r.job_id = ?
        ORDER BY r.created_at DESC
    """, (job_id,)).fetchall()

    conn.commit()
    conn.close()

    result = job_dict(row, current_id)
    result["responses"] = [
        {
            "id": r["id"],
            "message": r["message"],
            "status": r["status"],
            "created_at": r["created_at"],
            "user_id": r["user_id"],
            "name": r["name"],
            "avatar_url": r["avatar_url"] or DEFAULT_AVATAR,
            "rating": round(float(r["rating"] or 0), 1),
        }
        for r in responses
    ]
    return jsonify(result)


@app.post("/api/jobs")
@require_auth
def create_job(user):
    data = request.get_json(silent=True) or {}

    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()
    category = str(data.get("category", "Другое")).strip() or "Другое"
    address = str(data.get("address", "")).strip()

    try:
        price = float(data.get("price"))
    except Exception:
        price = 0

    lat, lng = validate_coords(data.get("lat"), data.get("lng"))

    if not title:
        return jsonify({"error": "Введите название задания"}), 400
    if len(title) > 120:
        return jsonify({"error": "Название слишком длинное"}), 400
    if price <= 0:
        return jsonify({"error": "Цена должна быть больше 0"}), 400
    if lat is None:
        return jsonify({"error": "Выберите корректное место на карте"}), 400

    conn = get_db()
    cur = conn.execute("""
        INSERT INTO jobs
        (user_id, title, description, price, lat, lng, address, category, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user["id"], title, description, price, lat, lng,
        address, category, now_plus(30)
    ))
    job_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "job_id": job_id}), 201


@app.patch("/api/jobs/<int:job_id>")
@require_auth
def update_job(user, job_id):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    if not job:
        conn.close()
        return jsonify({"error": "Задание не найдено"}), 404
    if job["user_id"] != user["id"]:
        conn.close()
        return jsonify({"error": "Нет доступа"}), 403

    title = str(data.get("title", job["title"])).strip()
    description = str(data.get("description", job["description"] or "")).strip()
    category = str(data.get("category", job["category"])).strip()
    address = str(data.get("address", job["address"] or "")).strip()
    status = str(data.get("status", job["status"])).strip()

    try:
        price = float(data.get("price", job["price"]))
    except Exception:
        price = 0

    if status not in ("active", "closed", "completed", "cancelled"):
        status = job["status"]
    if not title or price <= 0:
        conn.close()
        return jsonify({"error": "Проверьте название и цену"}), 400

    conn.execute("""
        UPDATE jobs
        SET title=?, description=?, price=?, address=?, category=?, status=?
        WHERE id=?
    """, (title, description, price, address, category, status, job_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.delete("/api/jobs/<int:job_id>")
@require_auth
def delete_job(user, job_id):
    conn = get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        conn.close()
        return jsonify({"error": "Задание не найдено"}), 404
    if job["user_id"] != user["id"]:
        conn.close()
        return jsonify({"error": "Нет доступа"}), 403

    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ============================================================
# RESPONSES
# ============================================================

@app.post("/api/jobs/<int:job_id>/respond")
@require_auth
def respond(user, job_id):
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    conn = get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    if not job:
        conn.close()
        return jsonify({"error": "Задание не найдено"}), 404
    if job["user_id"] == user["id"]:
        conn.close()
        return jsonify({"error": "Нельзя откликнуться на своё задание"}), 400
    if job["status"] != "active":
        conn.close()
        return jsonify({"error": "Задание уже закрыто"}), 400

    exists = conn.execute("""
        SELECT id FROM responses WHERE job_id=? AND user_id=?
    """, (job_id, user["id"])).fetchone()
    if exists:
        conn.close()
        return jsonify({"error": "Вы уже откликались на это задание"}), 409

    conn.execute("""
        INSERT INTO responses (job_id, user_id, message)
        VALUES (?, ?, ?)
    """, (job_id, user["id"], message))

    conn.execute("""
        INSERT INTO notifications (user_id, type, title, message)
        VALUES (?, 'response', 'Новый отклик', ?)
    """, (
        job["user_id"],
        f"{user['name']} откликнулся на «{job['title']}»"
    ))

    conn.commit()
    conn.close()
    return jsonify({"status": "ok"}), 201


@app.patch("/api/responses/<int:response_id>")
@require_auth
def update_response(user, response_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip()

    if status not in ("accepted", "rejected", "pending"):
        return jsonify({"error": "Некорректный статус"}), 400

    conn = get_db()
    row = conn.execute("""
        SELECT r.*, j.user_id AS owner_id, j.title
        FROM responses r
        JOIN jobs j ON j.id = r.job_id
        WHERE r.id = ?
    """, (response_id,)).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Отклик не найден"}), 404
    if row["owner_id"] != user["id"]:
        conn.close()
        return jsonify({"error": "Нет доступа"}), 403

    conn.execute("UPDATE responses SET status=? WHERE id=?", (status, response_id))

    if status == "accepted":
        conn.execute(
            "UPDATE jobs SET status='closed' WHERE id=?",
            (row["job_id"],)
        )

    conn.execute("""
        INSERT INTO notifications (user_id, type, title, message)
        VALUES (?, 'response_status', 'Статус отклика изменён', ?)
    """, (
        row["user_id"],
        f"Ваш отклик на «{row['title']}»: {status}"
    ))

    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.get("/api/my-responses")
@require_auth
def my_responses(user):
    conn = get_db()
    rows = conn.execute("""
        SELECT r.*, j.title, j.price, j.status AS job_status,
               u.name AS owner_name
        FROM responses r
        JOIN jobs j ON j.id = r.job_id
        JOIN users u ON u.id = j.user_id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
    """, (user["id"],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ============================================================
# FAVORITES
# ============================================================

@app.get("/api/favorites")
@require_auth
def favorites(user):
    conn = get_db()
    rows = conn.execute("""
        SELECT j.*,
               u.id AS author_id, u.name AS author_name,
               u.rating AS author_rating, u.avatar_url AS author_avatar,
               1 AS favorite_id
        FROM favorites f
        JOIN jobs j ON j.id=f.job_id
        JOIN users u ON u.id=j.user_id
        WHERE f.user_id=?
        ORDER BY f.created_at DESC
    """, (user["id"],)).fetchall()
    conn.close()
    return jsonify([job_dict(r, user["id"]) for r in rows])


@app.post("/api/favorites/<int:job_id>")
@require_auth
def toggle_favorite(user, job_id):
    conn = get_db()
    job = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        conn.close()
        return jsonify({"error": "Задание не найдено"}), 404

    existing = conn.execute("""
        SELECT id FROM favorites WHERE user_id=? AND job_id=?
    """, (user["id"], job_id)).fetchone()

    if existing:
        conn.execute("DELETE FROM favorites WHERE id=?", (existing["id"],))
        action = "removed"
    else:
        conn.execute(
            "INSERT INTO favorites (user_id, job_id) VALUES (?, ?)",
            (user["id"], job_id)
        )
        action = "added"

    conn.commit()
    conn.close()
    return jsonify({"action": action})


# ============================================================
# NOTIFICATIONS
# ============================================================

@app.get("/api/notifications")
@require_auth
def notifications(user):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM notifications
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT 100
    """, (user["id"],)).fetchall()
    unread = conn.execute("""
        SELECT COUNT(*) AS n FROM notifications
        WHERE user_id=? AND read=0
    """, (user["id"],)).fetchone()["n"]
    conn.close()
    return jsonify({
        "unread": unread,
        "items": [dict(r) for r in rows]
    })


@app.post("/api/notifications/read")
@require_auth
def notifications_read(user):
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET read=1 WHERE user_id=?",
        (user["id"],)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ============================================================
# REVIEWS
# ============================================================

@app.post("/api/reviews")
@require_auth
def create_review(user):
    data = request.get_json(silent=True) or {}
    to_user_id = int(data.get("to_user_id", 0))
    job_id = data.get("job_id")
    rating = int(data.get("rating", 0))
    comment = str(data.get("comment", "")).strip()

    if rating < 1 or rating > 5:
        return jsonify({"error": "Оценка должна быть от 1 до 5"}), 400
    if to_user_id == user["id"]:
        return jsonify({"error": "Нельзя оценить самого себя"}), 400

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO reviews
            (from_user_id, to_user_id, job_id, rating, comment)
            VALUES (?, ?, ?, ?, ?)
        """, (user["id"], to_user_id, job_id, rating, comment))

        stats = conn.execute("""
            SELECT AVG(rating) AS avg_rating, COUNT(*) AS cnt
            FROM reviews WHERE to_user_id=?
        """, (to_user_id,)).fetchone()

        conn.execute("""
            UPDATE users SET rating=?, reviews_count=?
            WHERE id=?
        """, (
            round(float(stats["avg_rating"] or 0), 2),
            stats["cnt"],
            to_user_id
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Не удалось сохранить отзыв"}), 400
    finally:
        conn.close()

    return jsonify({"status": "ok"}), 201


# ============================================================
# PWA
# ============================================================

@app.get("/manifest.json")
def manifest():
    return jsonify({
        "name": "Near Gig",
        "short_name": "Near Gig",
        "description": "Подработка рядом с вами",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f5f5f7",
        "theme_color": "#111214",
        "lang": "ru",
        "icons": [
            {"src": APP_ICON, "sizes": "512x512", "type": "image/png"}
        ]
    })


@app.get("/sw.js")
def service_worker():
    return Response("""
const CACHE = "near-gig-v2";
self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE));
});
self.addEventListener("activate", e => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
""", mimetype="application/javascript")


# ============================================================
# FRONTEND
# ============================================================

HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1,maximum-scale=1,
               viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#f5f5f7">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="https://cdn-icons-png.flaticon.com/512/1041/1041916.png">
<title>Near Gig</title>

<script src="https://api-maps.yandex.ru/2.1/?lang=ru_RU"></script>
<script src="https://cdn.tailwindcss.com"></script>

<style>
:root{
  --bg:#f5f5f7;
  --surface:#ffffff;
  --surface2:#f0f1f3;
  --text:#18191c;
  --muted:#777b83;
  --border:#e4e5e8;
  --accent:#5f5ce6;
  --accent-soft:#ecebff;
  --success:#3c9b68;
  --danger:#d45d63;
  --shadow:0 10px 30px rgba(20,20,30,.08);
  --nav-h:74px;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;width:100%;height:100%;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",sans-serif;background:var(--bg);color:var(--text)}
body{overscroll-behavior:none}
button,input,textarea,select{font:inherit}
button{cursor:pointer}
#app{height:100dvh;min-height:100%;overflow:hidden}
.page{display:none;height:100%;overflow:auto;padding-bottom:calc(var(--nav-h) + env(safe-area-inset-bottom) + 20px)}
.page.active{display:block}
.topbar{
  position:sticky;top:0;z-index:30;
  height:64px;padding:10px 16px;
  display:flex;align-items:center;justify-content:space-between;
  background:color-mix(in srgb,var(--surface) 94%,transparent);
  backdrop-filter:blur(18px);border-bottom:1px solid var(--border)
}
.logo{font-size:20px;font-weight:800;letter-spacing:-.5px}
.icon-btn{
  width:42px;height:42px;border:0;border-radius:13px;
  display:grid;place-items:center;background:var(--surface2);color:var(--text)
}
.avatar{width:40px;height:40px;border-radius:50%;object-fit:cover;background:var(--surface2)}
.container{max-width:720px;margin:auto;padding:16px}
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:20px;box-shadow:0 5px 20px rgba(0,0,0,.035)
}
.btn{
  border:0;border-radius:14px;padding:13px 16px;font-weight:700;
  min-height:48px;transition:transform .12s,opacity .12s
}
.btn:active{transform:scale(.98)}
.btn-primary{background:var(--accent);color:#fff}
.btn-secondary{background:var(--surface2);color:var(--text)}
.btn-danger{background:#fbecef;color:var(--danger)}
.btn-success{background:#eaf7ef;color:var(--success)}
.input{
  width:100%;border:1px solid var(--border);background:var(--surface);
  color:var(--text);border-radius:14px;padding:13px 14px;outline:0;
  min-height:48px
}
.input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
textarea.input{min-height:100px;resize:vertical}
.label{display:block;font-size:13px;font-weight:700;color:var(--muted);margin:0 0 7px}
.field{margin-bottom:14px}
.muted{color:var(--muted)}
.small{font-size:13px}
.chips{display:flex;gap:8px;overflow-x:auto;padding:4px 0 10px;scrollbar-width:none}
.chips::-webkit-scrollbar{display:none}
.chip{
  white-space:nowrap;border:1px solid var(--border);background:var(--surface);
  color:var(--muted);border-radius:999px;padding:9px 13px;font-size:13px;font-weight:700
}
.chip.active{background:var(--text);color:var(--surface);border-color:var(--text)}
.job-card{padding:15px;margin-bottom:10px}
.job-card:active{background:var(--surface2)}
.job-head{display:flex;justify-content:space-between;gap:12px}
.job-title{font-weight:800;font-size:16px;line-height:1.25}
.price{font-weight:850;white-space:nowrap}
.job-meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px;color:var(--muted);font-size:12px}
.bottom-nav{
  position:fixed;left:0;right:0;bottom:0;z-index:60;
  min-height:var(--nav-h);padding:7px 10px calc(7px + env(safe-area-inset-bottom));
  background:color-mix(in srgb,var(--surface) 94%,transparent);
  backdrop-filter:blur(20px);border-top:1px solid var(--border);
  display:grid;grid-template-columns:repeat(4,1fr)
}
.nav-btn{
  border:0;background:transparent;color:var(--muted);font-size:11px;font-weight:700;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;border-radius:13px
}
.nav-btn.active{color:var(--text);background:var(--surface2)}
.nav-icon{font-size:20px;line-height:1}
#mapPage{position:relative;padding-bottom:0;overflow:hidden}
#map{position:absolute;inset:0 0 0 0}
.map-top{
  position:absolute;top:12px;left:12px;right:12px;z-index:20;
  display:flex;gap:8px;align-items:center
}
.search{
  flex:1;min-width:0;background:var(--surface);border:1px solid var(--border);
  border-radius:15px;height:48px;padding:0 14px;box-shadow:var(--shadow)
}
.map-action{
  width:48px;height:48px;border:0;border-radius:15px;background:var(--surface);
  box-shadow:var(--shadow);font-size:20px
}
.map-bottom{
  position:absolute;left:12px;right:12px;bottom:90px;z-index:20
}
.map-sheet{
  background:color-mix(in srgb,var(--surface) 95%,transparent);
  backdrop-filter:blur(16px);border:1px solid var(--border);
  border-radius:20px;padding:12px;box-shadow:var(--shadow)
}
.sheet-row{display:flex;align-items:center;justify-content:space-between;gap:10px}
.overlay{
  position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.48);
  display:none;align-items:flex-end
}
.overlay.open{display:flex}
.modal{
  width:100%;max-height:92dvh;overflow:auto;background:var(--surface);
  color:var(--text);border-radius:24px 24px 0 0;
  padding:20px 16px calc(20px + env(safe-area-inset-bottom))
}
.modal-center{align-items:center;justify-content:center;padding:16px}
.modal-center .modal{max-width:460px;border-radius:24px;max-height:90dvh}
.modal-title{font-size:22px;font-weight:850;margin-bottom:16px}
.handle{width:38px;height:4px;background:var(--border);border-radius:99px;margin:-7px auto 16px}
.row{display:flex;align-items:center;gap:12px}
.between{display:flex;align-items:center;justify-content:space-between;gap:12px}
.stat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.stat{padding:13px;text-align:center;background:var(--surface2);border-radius:15px}
.stat b{display:block;font-size:18px}
.list-empty{text-align:center;padding:50px 20px;color:var(--muted)}
.toast{
  position:fixed;left:50%;bottom:92px;transform:translate(-50%,20px);
  z-index:200;background:#202125;color:#fff;padding:12px 16px;border-radius:14px;
  opacity:0;pointer-events:none;transition:.2s;max-width:calc(100% - 30px);
  text-align:center;font-size:14px
}
.toast.show{opacity:1;transform:translate(-50%,0)}
.spinner{display:inline-block;width:18px;height:18px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.toggle{width:50px;height:30px;position:relative;display:inline-block}
.toggle input{display:none}
.toggle span{position:absolute;inset:0;border-radius:30px;background:#d6d7da;transition:.2s}
.toggle span:before{content:"";position:absolute;width:26px;height:26px;left:2px;top:2px;background:#fff;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,.18);transition:.2s}
.toggle input:checked+span{background:#5e5d67}
.toggle input:checked+span:before{transform:translateX(20px)}
.dark{
  --bg:#101112;--surface:#18191b;--surface2:#232528;
  --text:#e5e5e7;--muted:#a0a2a7;--border:#2c2e32;
  --accent:#8784d8;--accent-soft:#2b2a3c;
  --shadow:0 12px 30px rgba(0,0,0,.25)
}
.dark .chip.active{background:#e5e5e7;color:#17181a;border-color:#e5e5e7}
.dark .btn-primary{background:#7b78cc;color:#fff}
.dark .btn-danger{background:#322126;color:#e58a90}
.dark .btn-success{background:#1e3227;color:#8bd1a8}
.dark .toast{background:#f0f0f2;color:#17181a}
@media (min-width:700px){
  :root{--nav-h:76px}
  .bottom-nav{left:50%;right:auto;width:560px;transform:translateX(-50%);border:1px solid var(--border);border-radius:22px;margin-bottom:10px;box-shadow:var(--shadow)}
  .map-bottom{bottom:105px}
  .container{padding:24px}
  .modal{max-width:600px;border-radius:24px;margin:auto}
  .overlay{align-items:center;justify-content:center;padding:20px}
}
@media (min-width:1100px){
  .bottom-nav{width:640px}
  .container{max-width:860px}
}
@media (max-height:650px){
  :root{--nav-h:66px}
  .bottom-nav{min-height:var(--nav-h)}
  .map-bottom{bottom:76px}
}
</style>
</head>

<body>
<div id="app">
  <main id="mapPage" class="page active">
    <div id="map"></div>
    <div class="map-top">
      <input id="mapSearch" class="search" placeholder="Поиск подработки..." autocomplete="off">
      <button class="map-action" id="locateBtn" aria-label="Моё местоположение">⌖</button>
      <button class="map-action" id="filterBtn" aria-label="Фильтры">☷</button>
    </div>
    <div class="map-bottom">
      <div class="map-sheet">
        <div class="sheet-row">
          <div>
            <div style="font-weight:800">Подработка рядом</div>
            <div class="small muted" id="mapCounter">Загрузка...</div>
          </div>
          <button class="btn btn-primary" style="min-height:42px;padding:10px 14px" onclick="openCreate()">+ Создать</button>
        </div>
      </div>
    </div>
  </main>

  <main id="jobsPage" class="page">
    <header class="topbar">
      <div class="logo">Задания</div>
      <button class="icon-btn" onclick="openFilters()">☷</button>
    </header>
    <div class="container">
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <input id="jobsSearch" class="input" placeholder="Найти задание...">
      </div>
      <div id="categoryChips" class="chips"></div>
      <div id="jobsList"></div>
    </div>
  </main>

  <main id="createPage" class="page">
    <header class="topbar">
      <div class="logo">Новое задание</div>
    </header>
    <div class="container">
      <div class="card" style="padding:16px">
        <div class="field">
          <label class="label">Что нужно сделать?</label>
          <input id="createTitle" class="input" maxlength="120" placeholder="Например: забрать посылку">
        </div>
        <div class="field">
          <label class="label">Описание</label>
          <textarea id="createDescription" class="input" placeholder="Опишите задачу, требования и детали"></textarea>
        </div>
        <div class="field">
          <label class="label">Стоимость, ₽</label>
          <input id="createPrice" class="input" type="number" min="1" step="1" placeholder="1500">
        </div>
        <div class="field">
          <label class="label">Категория</label>
          <select id="createCategory" class="input"></select>
        </div>
        <div class="field">
          <label class="label">Адрес или ориентир</label>
          <input id="createAddress" class="input" placeholder="Улица, дом, ориентир">
        </div>
        <div class="card" style="padding:13px;background:var(--surface2);box-shadow:none">
          <div class="between">
            <div>
              <b>Место на карте</b>
              <div id="createCoords" class="small muted">Определяем ваше местоположение...</div>
            </div>
            <button class="btn btn-secondary" onclick="useMyLocation()" style="min-height:42px">Определить</button>
          </div>
        </div>
        <button class="btn btn-primary" style="width:100%;margin-top:14px" onclick="submitCreate()">
          Опубликовать
        </button>
      </div>
    </div>
  </main>

  <main id="profilePage" class="page">
    <header class="topbar">
      <div class="logo">Профиль</div>
      <button class="icon-btn" onclick="openSettings()">⚙</button>
    </header>
    <div class="container">
      <div id="profileBox"></div>
      <div id="profileActions"></div>
    </div>
  </main>

  <nav class="bottom-nav">
    <button class="nav-btn active" data-page="mapPage" onclick="navigate('mapPage')"><span class="nav-icon">⌖</span>Карта</button>
    <button class="nav-btn" data-page="jobsPage" onclick="navigate('jobsPage')"><span class="nav-icon">☷</span>Задания</button>
    <button class="nav-btn" data-page="createPage" onclick="openCreate()"><span class="nav-icon">＋</span>Создать</button>
    <button class="nav-btn" data-page="profilePage" onclick="navigate('profilePage')"><span class="nav-icon">○</span>Профиль</button>
  </nav>
</div>

<div id="authOverlay" class="overlay modal-center">
  <div class="modal">
    <div class="modal-title" id="authTitle">Войти</div>
    <form onsubmit="submitAuth(event)">
      <div class="field" id="authNameField" style="display:none">
        <label class="label">Имя</label>
        <input id="authName" class="input" maxlength="80" placeholder="Ваше имя">
      </div>
      <div class="field">
        <label class="label">Email</label>
        <input id="authEmail" class="input" type="email" autocomplete="email" required>
      </div>
      <div class="field">
        <label class="label">Пароль</label>
        <input id="authPassword" class="input" type="password" autocomplete="current-password" minlength="6" required>
      </div>
      <div class="field" id="authRoleField" style="display:none">
        <label class="label">Я хочу</label>
        <select id="authRole" class="input">
          <option value="executor">Искать подработку</option>
          <option value="customer">Размещать задания</option>
        </select>
      </div>
      <button class="btn btn-primary" style="width:100%" id="authSubmit">Войти</button>
    </form>
    <div style="text-align:center;margin-top:14px" class="small">
      <span id="authSwitchText">Нет аккаунта?</span>
      <button style="border:0;background:none;color:var(--accent);font-weight:800" onclick="toggleAuth()">Зарегистрироваться</button>
    </div>
    <button class="btn btn-secondary" style="width:100%;margin-top:10px" onclick="closeOverlay('authOverlay')">Отмена</button>
  </div>
</div>

<div id="createOverlay" class="overlay">
  <div class="modal">
    <div class="handle"></div>
    <div class="modal-title">Новая подработка</div>
    <div class="field">
      <label class="label">Название</label>
      <input id="mTitle" class="input" maxlength="120" placeholder="Например: помощь с переездом">
    </div>
    <div class="field">
      <label class="label">Описание</label>
      <textarea id="mDescription" class="input" placeholder="Что нужно сделать?"></textarea>
    </div>
    <div class="field">
      <label class="label">Стоимость, ₽</label>
      <input id="mPrice" class="input" type="number" min="1" step="1" placeholder="2000">
    </div>
    <div class="field">
      <label class="label">Категория</label>
      <select id="mCategory" class="input"></select>
    </div>
    <div class="field">
      <label class="label">Адрес</label>
      <input id="mAddress" class="input" placeholder="Адрес или ориентир">
    </div>
    <button class="btn btn-primary" style="width:100%" onclick="submitModalCreate()">Опубликовать</button>
    <button class="btn btn-secondary" style="width:100%;margin-top:8px" onclick="closeOverlay('createOverlay')">Отмена</button>
  </div>
</div>

<div id="detailOverlay" class="overlay">
  <div class="modal">
    <div class="handle"></div>
    <div class="between">
      <div class="modal-title" id="detailTitle" style="margin-bottom:0"></div>
      <button class="icon-btn" onclick="closeOverlay('detailOverlay')">×</button>
    </div>
    <div id="detailBody" style="margin-top:16px"></div>
  </div>
</div>

<div id="filtersOverlay" class="overlay">
  <div class="modal">
    <div class="handle"></div>
    <div class="modal-title">Фильтры</div>
    <div class="field">
      <label class="label">Категория</label>
      <select id="filterCategory" class="input"></select>
    </div>
    <div class="field">
      <label class="label">Максимальная цена, ₽</label>
      <input id="filterPrice" class="input" type="number" min="0" placeholder="Без ограничений">
    </div>
    <div class="field">
      <label class="label">Радиус, км</label>
      <select id="filterRadius" class="input">
        <option value="">Везде</option>
        <option value="2">До 2 км</option>
        <option value="5">До 5 км</option>
        <option value="10">До 10 км</option>
        <option value="25">До 25 км</option>
        <option value="50">До 50 км</option>
      </select>
    </div>
    <button class="btn btn-primary" style="width:100%" onclick="applyFilters()">Применить</button>
    <button class="btn btn-secondary" style="width:100%;margin-top:8px" onclick="closeOverlay('filtersOverlay')">Закрыть</button>
  </div>
</div>

<div id="settingsOverlay" class="overlay">
  <div class="modal">
    <div class="handle"></div>
    <div class="modal-title">Настройки</div>

    <div class="card" style="padding:5px;box-shadow:none">
      <div class="between" style="padding:12px">
        <div><b>Тёмная тема</b><div class="small muted">Спокойный серо-белый интерфейс</div></div>
        <label class="toggle"><input id="darkToggle" type="checkbox" onchange="toggleDark(this.checked)"><span></span></label>
      </div>
      <div class="between" style="padding:12px;border-top:1px solid var(--border)">
        <div><b>Уведомления</b><div class="small muted">Новые отклики и изменения</div></div>
        <label class="toggle"><input id="notifyToggle" type="checkbox" checked onchange="localStorage.setItem('ng_notifications',this.checked)"><span></span></label>
      </div>
    </div>

    <button class="btn btn-secondary" style="width:100%;margin-top:12px" onclick="editProfile()">Изменить профиль</button>
    <button class="btn btn-danger" style="width:100%;margin-top:8px" onclick="logout()">Выйти</button>
    <button class="btn btn-secondary" style="width:100%;margin-top:8px" onclick="closeOverlay('settingsOverlay')">Закрыть</button>
  </div>
</div>

<div id="editProfileOverlay" class="overlay">
  <div class="modal">
    <div class="handle"></div>
    <div class="modal-title">Мой профиль</div>
    <div class="field"><label class="label">Имя</label><input id="editName" class="input"></div>
    <div class="field"><label class="label">Телефон</label><input id="editPhone" class="input" type="tel"></div>
    <div class="field"><label class="label">Ссылка на аватар</label><input id="editAvatar" class="input" type="url"></div>
    <button class="btn btn-primary" style="width:100%" onclick="saveProfile()">Сохранить</button>
    <button class="btn btn-secondary" style="width:100%;margin-top:8px" onclick="closeOverlay('editProfileOverlay')">Отмена</button>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
const CATEGORIES = ["Все","Курьер","Уборка","Ремонт","IT","Доставка","Помощь","Авто","Репетитор","Другое"];

let state = {
  user: null,
  token: localStorage.getItem("ng_token"),
  page: "mapPage",
  map: null,
  tempPlacemark: null,
  coords: null,
  mapObjects: [],
  filters: {category:"",max_price:"",radius:""},
  device: "desktop",
  authRegister: false,
  category: ""
};

const $ = id => document.getElementById(id);

function esc(value){
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[c]));
}

function money(v){
  return new Intl.NumberFormat("ru-RU").format(Number(v || 0)) + " ₽";
}

function toast(message){
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(window.__toast);
  window.__toast = setTimeout(()=>el.classList.remove("show"),2500);
}

function detectDevice(){
  const w = window.innerWidth;
  const touch = navigator.maxTouchPoints > 0;
  state.device = w < 600 ? "phone" : (w < 1000 || touch ? "tablet" : "desktop");
  document.documentElement.dataset.device = state.device;
}

function applyTheme(){
  const dark = localStorage.getItem("ng_dark") === "1";
  document.documentElement.classList.toggle("dark", dark);
  if($("darkToggle")) $("darkToggle").checked = dark;
}

function toggleDark(value){
  localStorage.setItem("ng_dark", value ? "1" : "0");
  applyTheme();
}

function navigate(page){
  if(page === "createPage"){
    if(!state.user){ openAuth(); return; }
  }
  if(page === "profilePage"){
    if(!state.user){ openAuth(); return; }
  }

  document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));
  $(page).classList.add("active");
  document.querySelectorAll(".nav-btn").forEach(b=>{
    b.classList.toggle("active", b.dataset.page === page);
  });
  state.page = page;

  if(page === "jobsPage") loadJobs();
  if(page === "profilePage") loadProfile();
  if(page === "mapPage") setTimeout(()=>state.map && state.map.container.fitToViewport(),100);
}

function openOverlay(id){ $(id).classList.add("open"); }
function closeOverlay(id){ $(id).classList.remove("open"); }

function api(path, options={}){
  options.headers = Object.assign({}, options.headers || {});
  if(state.token) options.headers.Authorization = "Bearer " + state.token;
  if(options.body && typeof options.body !== "string"){
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  return fetch(path, options).then(async r=>{
    const data = await r.json().catch(()=>({}));
    if(r.status === 401){
      state.user = null;
      state.token = null;
      localStorage.removeItem("ng_token");
      updateUI();
    }
    if(!r.ok) throw new Error(data.error || "Ошибка запроса");
    return data;
  });
}

function updateUI(){
  renderProfile();
}

function openAuth(register=false){
  state.authRegister = register;
  $("authTitle").textContent = register ? "Создать аккаунт" : "Войти";
  $("authNameField").style.display = register ? "block" : "none";
  $("authRoleField").style.display = register ? "block" : "none";
  $("authSubmit").textContent = register ? "Зарегистрироваться" : "Войти";
  $("authSwitchText").textContent = register ? "Уже есть аккаунт?" : "Нет аккаунта?";
  document.querySelector("#authOverlay button[onclick='toggleAuth()']").textContent =
    register ? "Войти" : "Зарегистрироваться";
  openOverlay("authOverlay");
}

function toggleAuth(){
  openAuth(!state.authRegister);
}

async function submitAuth(e){
  e.preventDefault();
  const payload = {
    email:$("authEmail").value.trim(),
    password:$("authPassword").value
  };
  if(state.authRegister){
    payload.name = $("authName").value.trim();
    payload.role = $("authRole").value;
  }
  try{
    $("authSubmit").disabled = true;
    const data = await api(state.authRegister ? "/api/register" : "/api/login", {
      method:"POST",body:payload
    });
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem("ng_token", state.token);
    closeOverlay("authOverlay");
    toast(state.authRegister ? "Аккаунт создан" : "Вы вошли");
    updateUI();
    loadJobs();
    loadMapJobs();
  }catch(err){ toast(err.message); }
  finally{ $("authSubmit").disabled = false; }
}

async function logout(){
  try{ await api("/api/logout",{method:"POST"}); }catch(e){}
  state.user = null;
  state.token = null;
  localStorage.removeItem("ng_token");
  closeOverlay("settingsOverlay");
  closeOverlay("editProfileOverlay");
  toast("Вы вышли из аккаунта");
  updateUI();
}

function categoriesInto(selectId){
  const el = $(selectId);
  if(!el) return;
  el.innerHTML = CATEGORIES.map(c=>`<option value="${esc(c==="Все"?"":c)}">${esc(c)}</option>`).join("");
}

function initCategoryUI(){
  ["createCategory","mCategory","filterCategory"].forEach(categoriesInto);
  $("categoryChips").innerHTML = CATEGORIES.map(c =>
    `<button class="chip ${c==="Все"?"active":""}" onclick="chooseCategory('${esc(c)}',this)">${esc(c)}</button>`
  ).join("");
}

function chooseCategory(category, button){
  state.category = category === "Все" ? "" : category;
  document.querySelectorAll("#categoryChips .chip").forEach(x=>x.classList.remove("active"));
  button.classList.add("active");
  loadJobs();
}

function openFilters(){
  $("filterCategory").value = state.filters.category;
  $("filterPrice").value = state.filters.max_price;
  $("filterRadius").value = state.filters.radius;
  openOverlay("filtersOverlay");
}

function applyFilters(){
  state.filters.category = $("filterCategory").value;
  state.filters.max_price = $("filterPrice").value;
  state.filters.radius = $("filterRadius").value;
  closeOverlay("filtersOverlay");
  loadJobs();
  loadMapJobs();
}

function queryParams(){
  const p = new URLSearchParams();
  if(state.category) p.set("category",state.category);
  if(state.filters.category) p.set("category",state.filters.category);
  if(state.filters.max_price) p.set("max_price",state.filters.max_price);
  if($("jobsSearch").value.trim()) p.set("search",$("jobsSearch").value.trim());
  if(state.coords && state.filters.radius){
    p.set("lat",state.coords[0]);
    p.set("lng",state.coords[1]);
    p.set("radius",state.filters.radius);
  }
  return p;
}

async function loadJobs(){
  const list = $("jobsList");
  list.innerHTML = `<div class="list-empty"><span class="spinner"></span></div>`;
  try{
    const jobs = await api("/api/jobs?" + queryParams().toString());
    if(!jobs.length){
      list.innerHTML = `<div class="list-empty">По вашему запросу пока ничего нет.</div>`;
      return;
    }
    list.innerHTML = jobs.map(jobCard).join("");
  }catch(err){
    list.innerHTML = `<div class="list-empty">${esc(err.message)}</div>`;
  }
}

function jobCard(j){
  return `
  <div class="card job-card" onclick="openJob(${j.id})">
    <div class="job-head">
      <div>
        <div class="job-title">${esc(j.title)}</div>
        <div class="job-meta">
          <span>${esc(j.category)}</span>
          ${j.address ? `<span>• ${esc(j.address)}</span>` : ""}
          ${j.distance != null ? `<span>• ${j.distance} км</span>` : ""}
        </div>
      </div>
      <div class="price">${money(j.price)}</div>
    </div>
    <div class="muted small" style="margin-top:10px">
      ${esc((j.description||"").slice(0,130))}${(j.description||"").length>130?"…":""}
    </div>
    <div class="between" style="margin-top:12px">
      <div class="row">
        <img class="avatar" style="width:28px;height:28px" src="${esc(j.author.avatar)}">
        <span class="small">${esc(j.author.name)} · ★ ${j.author.rating}</span>
      </div>
      <button class="icon-btn" style="width:36px;height:36px" onclick="event.stopPropagation();favorite(${j.id})">
        ${j.is_favorite ? "♥" : "♡"}
      </button>
    </div>
  </div>`;
}

async function openJob(id){
  try{
    const j = await api("/api/jobs/"+id);
    $("detailTitle").textContent = j.title;
    const isOwner = state.user && state.user.id === j.user_id;

    $("detailBody").innerHTML = `
      <div class="between">
        <div class="price" style="font-size:26px">${money(j.price)}</div>
        <span class="chip">${esc(j.category)}</span>
      </div>
      <div class="muted" style="margin:12px 0">${esc(j.description || "Описание не указано")}</div>
      ${j.address ? `<div class="small" style="margin:8px 0">⌖ ${esc(j.address)}</div>` : ""}
      <div class="row small muted" style="margin:12px 0">
        <img class="avatar" style="width:34px;height:34px" src="${esc(j.author.avatar)}">
        <span>${esc(j.author.name)} · ★ ${j.author.rating} · ${j.author.reviews_count || 0} отзывов</span>
      </div>
      <div class="stat-grid">
        <div class="stat"><b>${j.views}</b><span class="small muted">просмотров</span></div>
        <div class="stat"><b>${j.responses.length}</b><span class="small muted">откликов</span></div>
        <div class="stat"><b>${esc(j.status)}</b><span class="small muted">статус</span></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px">
        ${!isOwner ? `<button class="btn btn-primary" onclick="respond(${j.id})">Откликнуться</button>` : `<button class="btn btn-secondary" onclick="editJob(${j.id})">Редактировать</button>`}
        <button class="btn btn-secondary" onclick="favorite(${j.id})">${j.is_favorite?"♥ В избранном":"♡ В избранное"}</button>
      </div>
      ${isOwner ? renderResponses(j.responses) : ""}
    `;
    openOverlay("detailOverlay");
  }catch(err){ toast(err.message); }
}

function renderResponses(responses){
  if(!responses.length) return `<div style="margin-top:20px" class="muted">Откликов пока нет.</div>`;
  return `
    <div style="margin-top:20px">
      <b>Отклики</b>
      ${responses.map(r=>`
        <div class="card" style="padding:12px;margin-top:8px;box-shadow:none">
          <div class="row">
            <img class="avatar" style="width:34px;height:34px" src="${esc(r.avatar_url)}">
            <div style="flex:1"><b>${esc(r.name)}</b><div class="small muted">★ ${r.rating}</div></div>
            <span class="small">${esc(r.status)}</span>
          </div>
          <div class="small" style="margin-top:8px">${esc(r.message || "Без сообщения")}</div>
          ${r.status==="pending" ? `
            <div style="display:flex;gap:8px;margin-top:10px">
              <button class="btn btn-success" style="flex:1;min-height:40px;padding:8px" onclick="responseStatus(${r.id},'accepted')">Принять</button>
              <button class="btn btn-danger" style="flex:1;min-height:40px;padding:8px" onclick="responseStatus(${r.id},'rejected')">Отклонить</button>
            </div>` : ""}
        </div>`).join("")}
    </div>`;
}

async function responseStatus(id,status){
  try{
    await api("/api/responses/"+id,{method:"PATCH",body:{status}});
    toast(status==="accepted"?"Исполнитель выбран":"Отклик отклонён");
    closeOverlay("detailOverlay");
    loadJobs();
  }catch(err){toast(err.message)}
}

async function respond(jobId){
  if(!state.user){openAuth();return}
  const message = prompt("Сообщение исполнителю:", "");
  if(message === null) return;
  try{
    await api("/api/jobs/"+jobId+"/respond",{method:"POST",body:{message}});
    toast("Отклик отправлен");
    closeOverlay("detailOverlay");
  }catch(err){toast(err.message)}
}

async function favorite(jobId){
  if(!state.user){openAuth();return}
  try{
    const d = await api("/api/favorites/"+jobId,{method:"POST"});
    toast(d.action==="added" ? "Добавлено в избранное" : "Удалено из избранного");
    loadJobs();
    loadMapJobs();
  }catch(err){toast(err.message)}
}

function openCreate(){
  if(!state.user){openAuth();return}
  if(state.device === "phone"){
    openOverlay("createOverlay");
  }else{
    navigate("createPage");
    useMyLocation(false);
  }
}

function getCreateValues(prefix){
  return {
    title:$(prefix+"Title").value.trim(),
    description:$(prefix+"Description").value.trim(),
    price:parseFloat($(prefix+"Price").value),
    category:$(prefix+"Category").value,
    address:$(prefix+"Address").value.trim()
  };
}

async function publishJob(values){
  if(!state.coords){toast("Сначала определите место задания");return false}
  if(!values.title || !values.price || values.price<=0){
    toast("Заполните название и цену");return false
  }
  try{
    await api("/api/jobs",{method:"POST",body:{
      ...values,lat:state.coords[0],lng:state.coords[1]
    }});
    toast("Задание опубликовано");
    loadJobs();loadMapJobs();
    return true;
  }catch(err){toast(err.message);return false}
}

async function submitCreate(){
  const ok = await publishJob(getCreateValues("create"));
  if(ok) navigate("jobsPage");
}

async function submitModalCreate(){
  const ok = await publishJob(getCreateValues("m"));
  if(ok){
    closeOverlay("createOverlay");
    ["mTitle","mDescription","mPrice","mAddress"].forEach(id=>$(id).value="");
  }
}

function useMyLocation(showToast=true){
  if(!navigator.geolocation){
    toast("Геолокация не поддерживается устройством");return;
  }
  navigator.geolocation.getCurrentPosition(
    pos=>{
      state.coords=[pos.coords.latitude,pos.coords.longitude];
      if(state.map) state.map.setCenter(state.coords,15);
      if(state.tempPlacemark) state.map.geoObjects.remove(state.tempPlacemark);
      if(state.map){
        state.tempPlacemark=new ymaps.Placemark(state.coords,{hintContent:"Место задания"});
        state.map.geoObjects.add(state.tempPlacemark);
      }
      if($("createCoords")) $("createCoords").textContent =
        `${state.coords[0].toFixed(5)}, ${state.coords[1].toFixed(5)}`;
      if(showToast) toast("Местоположение определено");
      loadJobs();
      loadMapJobs();
    },
    ()=>toast("Разрешите доступ к геолокации в настройках браузера"),
    {enableHighAccuracy:true,timeout:10000,maximumAge:60000}
  );
}

function initMap(){
  if(typeof ymaps==="undefined") return;
  ymaps.ready(()=>{
    state.map = new ymaps.Map("map",{
      center:[55.7558,37.6173],
      zoom:12,
      controls:["zoomControl","typeSelector"],
      type:"yandex#map"
    });
    state.map.events.add("click", e=>{
      if(!$("createOverlay").classList.contains("open")) return;
      state.coords=e.get("coords");
      if(state.tempPlacemark) state.map.geoObjects.remove(state.tempPlacemark);
      state.tempPlacemark=new ymaps.Placemark(state.coords,{hintContent:"Место задания"});
      state.map.geoObjects.add(state.tempPlacemark);
      $("mAddress").focus();
    });
    loadMapJobs();
    setTimeout(()=>useMyLocation(false),500);
  });
}

async function loadMapJobs(){
  if(!state.map) return;
  state.mapObjects.forEach(x=>{try{state.map.geoObjects.remove(x)}catch(e){}});
  state.mapObjects=[];
  const p = new URLSearchParams();
  if(state.category) p.set("category",state.category);
  if(state.filters.category) p.set("category",state.filters.category);
  if(state.filters.max_price) p.set("max_price",state.filters.max_price);
  try{
    const jobs=await api("/api/jobs?"+p.toString());
    $("mapCounter").textContent = `${jobs.length} ${plural(jobs.length,"задание","задания","заданий")}`;
    jobs.forEach(j=>{
      const mark=new ymaps.Placemark([j.lat,j.lng],{
        balloonContent:`
          <div style="min-width:180px">
            <b>${esc(j.title)}</b><br>
            <strong>${money(j.price)}</strong><br>
            <small>${esc(j.category)}</small><br><br>
            <button onclick="openJob(${j.id})" style="padding:7px 10px;border:0;border-radius:8px;background:#5f5ce6;color:#fff">Подробнее</button>
          </div>`
      });
      state.map.geoObjects.add(mark);
      state.mapObjects.push(mark);
    });
  }catch(e){}
}

function plural(n,a,b,c){
  n=Math.abs(n)%100;const n1=n%10;
  if(n>10&&n<20)return c;
  if(n1>1&&n1<5)return b;
  if(n1===1)return a;
  return c;
}

async function loadProfile(){
  if(!state.user){renderProfile();return}
  try{
    const [mine,favs,responses] = await Promise.all([
      api("/api/jobs?user_id="+state.user.id),
      api("/api/favorites"),
      api("/api/my-responses")
    ]);
    state.profileData={mine,favs,responses};
    renderProfile();
  }catch(err){toast(err.message)}
}

function renderProfile(){
  const box=$("profileBox"), actions=$("profileActions");
  if(!state.user){
    box.innerHTML=`
      <div class="card" style="padding:22px;text-align:center">
        <div style="font-size:48px">○</div>
        <h2 style="font-size:22px;font-weight:850;margin:8px">Войдите в аккаунт</h2>
        <p class="muted">Создавайте задания, откликайтесь и сохраняйте понравившиеся.</p>
        <button class="btn btn-primary" style="width:100%;margin-top:14px" onclick="openAuth()">Войти</button>
      </div>`;
    actions.innerHTML="";
    return;
  }
  const d=state.profileData||{mine:[],favs:[],responses:[]};
  box.innerHTML=`
    <div class="card" style="padding:18px">
      <div class="row">
        <img class="avatar" style="width:72px;height:72px" src="${esc(state.user.avatar_url)}">
        <div style="min-width:0">
          <h2 style="font-size:22px;font-weight:850">${esc(state.user.name)}</h2>
          <div class="muted">${esc(state.user.email)}</div>
          <div class="small" style="margin-top:4px">★ ${state.user.rating} · ${state.user.reviews_count} отзывов</div>
        </div>
      </div>
      <div class="stat-grid" style="margin-top:16px">
        <div class="stat"><b>${d.mine.length}</b><span class="small muted">мои задания</span></div>
        <div class="stat"><b>${d.favs.length}</b><span class="small muted">избранное</span></div>
        <div class="stat"><b>${d.responses.length}</b><span class="small muted">отклики</span></div>
      </div>
    </div>
    <div style="margin-top:14px">
      <button class="btn btn-secondary" style="width:100%;margin-bottom:8px" onclick="showMyJobs()">Мои задания</button>
      <button class="btn btn-secondary" style="width:100%;margin-bottom:8px" onclick="showFavorites()">Избранное</button>
      <button class="btn btn-secondary" style="width:100%" onclick="showMyResponses()">Мои отклики</button>
    </div>`;
  actions.innerHTML="";
}

function openSettings(){
  if(!state.user){openAuth();return}
  $("darkToggle").checked=localStorage.getItem("ng_dark")==="1";
  $("notifyToggle").checked=localStorage.getItem("ng_notifications")!=="0";
  openOverlay("settingsOverlay");
}

function editProfile(){
  $("editName").value=state.user.name||"";
  $("editPhone").value=state.user.phone||"";
  $("editAvatar").value=state.user.avatar_url||"";
  closeOverlay("settingsOverlay");
  openOverlay("editProfileOverlay");
}

async function saveProfile(){
  try{
    const u=await api("/api/me",{method:"PATCH",body:{
      name:$("editName").value.trim(),
      phone:$("editPhone").value.trim(),
      avatar_url:$("editAvatar").value.trim()
    }});
    state.user=u;
    closeOverlay("editProfileOverlay");
    renderProfile();
    toast("Профиль сохранён");
  }catch(err){toast(err.message)}
}

async function showMyJobs(){
  if(!state.user){openAuth();return}
  const jobs=(state.profileData||{}).mine||[];
  $("detailTitle").textContent="Мои задания";
  $("detailBody").innerHTML=jobs.length ? jobs.map(j=>`
    <div class="card" style="padding:13px;margin-bottom:8px" onclick="openJob(${j.id})">
      <div class="between"><b>${esc(j.title)}</b><span>${money(j.price)}</span></div>
      <div class="small muted" style="margin-top:5px">${esc(j.status)} · ${j.views} просмотров</div>
    </div>`).join("") : `<div class="list-empty">Вы ещё не создавали задания.</div>`;
  openOverlay("detailOverlay");
}

async function showFavorites(){
  if(!state.user){openAuth();return}
  const favs=(state.profileData||{}).favs||[];
  $("detailTitle").textContent="Избранное";
  $("detailBody").innerHTML=favs.length ? favs.map(j=>`
    <div class="card" style="padding:13px;margin-bottom:8px" onclick="openJob(${j.id})">
      <div class="between"><b>${esc(j.title)}</b><span>${money(j.price)}</span></div>
      <div class="small muted" style="margin-top:5px">${esc(j.category)}</div>
    </div>`).join("") : `<div class="list-empty">В избранном пока пусто.</div>`;
  openOverlay("detailOverlay");
}

function showMyResponses(){
  if(!state.user){openAuth();return}
  const rows=(state.profileData||{}).responses||[];
  $("detailTitle").textContent="Мои отклики";
  $("detailBody").innerHTML=rows.length ? rows.map(r=>`
    <div class="card" style="padding:13px;margin-bottom:8px">
      <div class="between"><b>${esc(r.title)}</b><span>${money(r.price)}</span></div>
      <div class="small muted" style="margin-top:5px">Статус: ${esc(r.status)}</div>
      <div class="small" style="margin-top:7px">${esc(r.message||"Без сообщения")}</div>
    </div>`).join("") : `<div class="list-empty">Вы ещё никуда не откликались.</div>`;
  openOverlay("detailOverlay");
}

function editJob(id){
  toast("Редактирование можно выполнить из карточки задания после загрузки формы.");
}

$("jobsSearch").addEventListener("input",()=>{
  clearTimeout(window.__search);
  window.__search=setTimeout(loadJobs,300);
});
$("mapSearch").addEventListener("input",()=>{
  clearTimeout(window.__mapSearch);
  window.__mapSearch=setTimeout(async()=>{
    const q=$("mapSearch").value.trim();
    if(!q){loadMapJobs();return}
    try{
      const jobs=await api("/api/jobs?search="+encodeURIComponent(q));
      if(state.map){
        state.mapObjects.forEach(x=>state.map.geoObjects.remove(x));
        state.mapObjects=[];
        jobs.forEach(j=>{
          const m=new ymaps.Placemark([j.lat,j.lng],{
            balloonContent:`<b>${esc(j.title)}</b><br>${money(j.price)}<br><button onclick="openJob(${j.id})">Подробнее</button>`
          });
          state.map.geoObjects.add(m);state.mapObjects.push(m);
        });
      }
      $("mapCounter").textContent=`${jobs.length} найдено`;
    }catch(e){}
  },300);
});

$("locateBtn").addEventListener("click",()=>useMyLocation(true));
$("filterBtn").addEventListener("click",openFilters);

window.addEventListener("resize",()=>{
  detectDevice();
  if(state.map) state.map.container.fitToViewport();
});

window.addEventListener("online",()=>toast("Соединение восстановлено"));
window.addEventListener("offline",()=>toast("Нет соединения с интернетом"));

async function bootstrap(){
  detectDevice();
  applyTheme();
  initCategoryUI();

  if(localStorage.getItem("ng_notifications")===null)
    localStorage.setItem("ng_notifications","1");

  if(state.token){
    try{
      state.user=await api("/api/me");
    }catch(e){}
  }

  updateUI();
  initMap();
  loadJobs();
  if(state.user) loadProfile();

  if("serviceWorker" in navigator){
    navigator.serviceWorker.register("/sw.js").catch(()=>{});
  }
}

bootstrap();
</script>
</body>
</html>"""


@app.get("/")
def index():
    return HTML


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Маршрут не найден"}), 404
    return HTML


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500
    return "Internal Server Error", 500


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
