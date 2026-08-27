import os, sqlite3, secrets, hashlib
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from flask import Flask, request, jsonify, Response
from cryptography.fernet import Fernet

BASE=os.path.dirname(os.path.abspath(__file__))
DB_PATH=os.environ.get('DB_PATH', os.path.join(BASE,'jobs.db'))
SECRET_KEY=os.environ.get('SECRET_KEY', secrets.token_hex(32))
PASSPORT_KEY=os.environ.get('PASSPORT_ENCRYPTION_KEY','')
app=Flask(__name__); app.secret_key=SECRET_KEY
fernet=Fernet(PASSPORT_KEY.encode()) if PASSPORT_KEY else None
AVATAR='https://cdn-icons-png.flaticon.com/512/149/149071.png'

def db():
    os.makedirs(os.path.dirname(DB_PATH) or '.',exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=30); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def cols(c,t): return {x['name'] for x in c.execute(f'PRAGMA table_info({t})')}
def addcol(c,t,n,d):
    if n not in cols(c,t): c.execute(f'ALTER TABLE {t} ADD COLUMN {n} {d}')

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,name TEXT NOT NULL,phone TEXT DEFAULT '',birth_date TEXT DEFAULT '',occupation TEXT DEFAULT '',role TEXT DEFAULT 'executor',avatar_url TEXT DEFAULT '',rating REAL DEFAULT 0,reviews_count INTEGER DEFAULT 0,completed_jobs INTEGER DEFAULT 0,created_at TEXT DEFAULT (datetime('now')),last_login TEXT,passport_series_enc TEXT DEFAULT '',passport_number_enc TEXT DEFAULT '',passport_issued_by_enc TEXT DEFAULT '',passport_issue_date TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,token TEXT UNIQUE NOT NULL,created_at TEXT DEFAULT (datetime('now')),expires_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT NOT NULL,description TEXT DEFAULT '',price REAL NOT NULL,lat REAL,lng REAL,address TEXT DEFAULT '',category TEXT DEFAULT 'Другое',status TEXT DEFAULT 'active',created_at TEXT DEFAULT (datetime('now')),expires_at TEXT,views INTEGER DEFAULT 0,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS responses(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER NOT NULL,user_id INTEGER NOT NULL,message TEXT DEFAULT '',status TEXT DEFAULT 'pending',created_at TEXT DEFAULT (datetime('now')),FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,UNIQUE(job_id,user_id));
    CREATE TABLE IF NOT EXISTS favorites(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,job_id INTEGER NOT NULL,created_at TEXT DEFAULT (datetime('now')),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,UNIQUE(user_id,job_id));
    CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT,from_user_id INTEGER NOT NULL,to_user_id INTEGER NOT NULL,job_id INTEGER,rating INTEGER CHECK(rating BETWEEN 1 AND 5),comment TEXT DEFAULT '',created_at TEXT DEFAULT (datetime('now')),FOREIGN KEY(from_user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(to_user_id) REFERENCES users(id) ON DELETE CASCADE);
    ''')
    for n,d in {'phone':"TEXT DEFAULT ''",'birth_date':"TEXT DEFAULT ''",'occupation':"TEXT DEFAULT ''",'avatar_url':f"TEXT DEFAULT '{AVATAR}'",'rating':'REAL DEFAULT 0','reviews_count':'INTEGER DEFAULT 0','completed_jobs':'INTEGER DEFAULT 0','last_login':'TEXT','passport_series_enc':"TEXT DEFAULT ''",'passport_number_enc':"TEXT DEFAULT ''",'passport_issued_by_enc':"TEXT DEFAULT ''",'passport_issue_date':"TEXT DEFAULT ''"}.items(): addcol(c,'users',n,d)
    for n,d in {'address':"TEXT DEFAULT ''",'expires_at':'TEXT','views':'INTEGER DEFAULT 0','status':"TEXT DEFAULT 'active'"}.items(): addcol(c,'jobs',n,d)
    c.execute('UPDATE users SET avatar_url=? WHERE avatar_url IS NULL OR avatar_url=""',(AVATAR,)); c.commit(); c.close()
init_db()

def pwd(p):
    salt=secrets.token_bytes(16); h=hashlib.pbkdf2_hmac('sha256',p.encode(),salt,210000); return f'pbkdf2$210000${salt.hex()}${h.hex()}'
def check(p,s):
    try:
        if s.startswith('pbkdf2$'):
            _,it,sa,di=s.split('$',3); h=hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(sa),int(it)); return secrets.compare_digest(h.hex(),di)
        return secrets.compare_digest(hashlib.sha256(p.encode()).hexdigest(),s)
    except: return False
def enc(x):
    if not x:return ''
    if not fernet: raise RuntimeError('На сервере не задан PASSPORT_ENCRYPTION_KEY')
    return fernet.encrypt(x.encode()).decode()
def dec(x):
    if not x or not fernet:return ''
    try:return fernet.decrypt(x.encode()).decode()
    except:return ''
def token():
    a=request.headers.get('Authorization',''); return a[7:].strip() if a.lower().startswith('bearer ') else ''
def user():
    t=token();
    if not t:return None
    c=db(); r=c.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires_at>datetime('now')",(t,)).fetchone(); c.close(); return dict(r) if r else None
def pub(u,private=False):
    x=dict(u); r={'id':x['id'],'email':x['email'],'name':x['name'],'phone':x.get('phone',''),'birth_date':x.get('birth_date',''),'occupation':x.get('occupation',''),'role':x.get('role','executor'),'avatar_url':x.get('avatar_url') or AVATAR,'rating':round(float(x.get('rating') or 0),2),'reviews_count':x.get('reviews_count',0),'completed_jobs':x.get('completed_jobs',0)}
    if private:
        r.update(passport_series=dec(x.get('passport_series_enc')),passport_number=dec(x.get('passport_number_enc')),passport_issued_by=dec(x.get('passport_issued_by_enc')),passport_issue_date=x.get('passport_issue_date',''))
    return r
def body():return request.get_json(silent=True) or {}
def dist(a,b,c,d):
    if None in(a,b,c,d):return None
    q=radians(c-a); w=radians(d-b); z=sin(q/2)**2+cos(radians(a))*cos(radians(c))*sin(w/2)**2; return 6371*2*atan2(sqrt(z),sqrt(1-z))

@app.post('/api/register')
def register():
    d=body(); fields=['email','password','name','phone','birth_date','occupation','passport_series','passport_number','passport_issued_by','passport_issue_date']
    if any(not str(d.get(x,'')).strip() for x in fields):return jsonify(error='Заполните все поля регистрации'),400
    if len(d['password'])<6:return jsonify(error='Пароль минимум 6 символов'),400
    role=d.get('role','executor') if d.get('role') in ('executor','customer') else 'executor'
    try: es, en, ei=enc(str(d['passport_series']).strip()),enc(str(d['passport_number']).strip()),enc(str(d['passport_issued_by']).strip())
    except RuntimeError as e:return jsonify(error=str(e)),500
    c=db()
    if c.execute('SELECT id FROM users WHERE email=?',(d['email'].strip().lower(),)).fetchone():c.close();return jsonify(error='Этот email уже зарегистрирован. Войдите в аккаунт.'),409
    cur=c.execute('INSERT INTO users(email,password_hash,name,phone,birth_date,occupation,role,avatar_url,passport_series_enc,passport_number_enc,passport_issued_by_enc,passport_issue_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(d['email'].strip().lower(),pwd(d['password']),d['name'].strip(),d['phone'].strip(),d['birth_date'],d['occupation'].strip(),role,AVATAR,es,en,ei,d['passport_issue_date']))
    uid=cur.lastrowid; t=secrets.token_hex(32); c.execute('INSERT INTO sessions(user_id,token,expires_at) VALUES(?,?,?)',(uid,t,(datetime.utcnow()+timedelta(days=30)).isoformat())); c.commit(); u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return jsonify(token=t,user=pub(u,True)),201

@app.post('/api/login')
def login():
    d=body(); c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(str(d.get('email','')).strip().lower(),)).fetchone()
    if not u or not check(str(d.get('password','')),u['password_hash']):c.close();return jsonify(error='Неверный email или пароль'),401
    t=secrets.token_hex(32); c.execute('INSERT INTO sessions(user_id,token,expires_at) VALUES(?,?,?)',(u['id'],t,(datetime.utcnow()+timedelta(days=30)).isoformat())); c.execute("UPDATE users SET last_login=datetime('now') WHERE id=?",(u['id'],)); c.commit(); u=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); c.close(); return jsonify(token=t,user=pub(u,True))
@app.post('/api/logout')
def logout():
    t=token(); c=db(); c.execute('DELETE FROM sessions WHERE token=?',(t,)); c.commit(); c.close(); return jsonify(status='ok')
@app.get('/api/me')
def me():
    u=user(); return (jsonify(pub(u,True)),200) if u else (jsonify(error='Не авторизован'),401)

@app.put('/api/profile')
def profile():
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    d=body(); name=str(d.get('name',u['name'])).strip(); phone=str(d.get('phone',u.get('phone',''))).strip(); birth=str(d.get('birth_date',u.get('birth_date',''))); occ=str(d.get('occupation',u.get('occupation',''))).strip()
    try: es,en,ei=enc(str(d.get('passport_series',dec(u.get('passport_series_enc')))).strip()),enc(str(d.get('passport_number',dec(u.get('passport_number_enc')))).strip()),enc(str(d.get('passport_issued_by',dec(u.get('passport_issued_by_enc')))).strip())
    except RuntimeError as e:return jsonify(error=str(e)),500
    c=db(); c.execute('UPDATE users SET name=?,phone=?,birth_date=?,occupation=?,passport_series_enc=?,passport_number_enc=?,passport_issued_by_enc=?,passport_issue_date=? WHERE id=?',(name,phone,birth,occ,es,en,ei,d.get('passport_issue_date',u.get('passport_issue_date','')),u['id'])); c.commit(); u=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); c.close(); return jsonify(pub(u,True))

def jobrow(r,lat=None,lng=None):
    x=dict(r); x['author']={'id':x.pop('author_id'),'name':x.pop('author_name'),'rating':x.pop('author_rating') or 0,'avatar':x.pop('author_avatar') or AVATAR}; x['distance']=dist(lat,lng,x['lat'],x['lng']) if lat is not None and lng is not None else None; return x
@app.get('/api/jobs')
def jobs():
    cat=request.args.get('category'); status=request.args.get('status','active'); search=request.args.get('search',''); uid=request.args.get('user_id',type=int); mx=request.args.get('max_price',type=float); lat=request.args.get('lat',type=float); lng=request.args.get('lng',type=float); radius=request.args.get('radius',type=float)
    q="SELECT j.*,u.name author_name,u.rating author_rating,u.avatar_url author_avatar,u.id author_id FROM jobs j JOIN users u ON u.id=j.user_id WHERE 1=1"; p=[]
    if status:q+=' AND j.status=?';p.append(status)
    if cat:q+=' AND j.category=?';p.append(cat)
    if uid:q+=' AND j.user_id=?';p.append(uid)
    if mx is not None:q+=' AND j.price<=?';p.append(mx)
    if search:q+=' AND (j.title LIKE ? OR j.description LIKE ? OR j.address LIKE ?)';p += [f'%{search}%']*3
    q+=' ORDER BY j.created_at DESC'; c=db(); rows=c.execute(q,p).fetchall(); c.close(); out=[]
    for r in rows:
        x=jobrow(r,lat,lng)
        if radius is None or x['distance'] is None or x['distance']<=radius:out.append(x)
    return jsonify(out)
@app.get('/api/jobs/<int:i>')
def job(i):
    c=db(); r=c.execute('SELECT j.*,u.name author_name,u.rating author_rating,u.avatar_url author_avatar,u.id author_id FROM jobs j JOIN users u ON u.id=j.user_id WHERE j.id=?',(i,)).fetchone()
    if not r:c.close();return jsonify(error='Задание не найдено'),404
    c.execute('UPDATE jobs SET views=views+1 WHERE id=?',(i,)); rs=c.execute('SELECT r.*,u.name,u.avatar_url,u.rating FROM responses r JOIN users u ON u.id=r.user_id WHERE r.job_id=? ORDER BY r.created_at DESC',(i,)).fetchall(); c.commit(); c.close(); x=jobrow(r); x['responses']=[dict(a) for a in rs]; return jsonify(x)
@app.post('/api/jobs')
def create_job():
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    d=body()
    try:price=float(d['price']);lat=float(d['lat']);lng=float(d['lng'])
    except:return jsonify(error='Укажите цену и точку на карте'),400
    if not str(d.get('title','')).strip():return jsonify(error='Укажите название'),400
    c=db(); cur=c.execute('INSERT INTO jobs(user_id,title,description,price,lat,lng,address,category,expires_at) VALUES(?,?,?,?,?,?,?,?,?)',(u['id'],d['title'].strip(),str(d.get('description','')).strip(),price,lat,lng,str(d.get('address','')).strip(),d.get('category','Другое'),(datetime.utcnow()+timedelta(days=30)).isoformat()));c.commit();i=cur.lastrowid;c.close();return jsonify(status='ok',job_id=i),201
@app.put('/api/jobs/<int:i>')
def update_job(i):
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    d=body();c=db();j=c.execute('SELECT * FROM jobs WHERE id=?',(i,)).fetchone()
    if not j:c.close();return jsonify(error='Не найдено'),404
    if j['user_id']!=u['id']:c.close();return jsonify(error='Нет доступа'),403
    c.execute('UPDATE jobs SET title=?,description=?,price=?,lat=?,lng=?,address=?,category=?,status=? WHERE id=?',(d.get('title',j['title']),d.get('description',j['description']),d.get('price',j['price']),d.get('lat',j['lat']),d.get('lng',j['lng']),d.get('address',j['address']),d.get('category',j['category']),d.get('status',j['status']),i));c.commit();c.close();return jsonify(status='ok')
@app.delete('/api/jobs/<int:i>')
def delete_job(i):
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    c=db();j=c.execute('SELECT user_id FROM jobs WHERE id=?',(i,)).fetchone()
    if not j:c.close();return jsonify(error='Не найдено'),404
    if j['user_id']!=u['id']:c.close();return jsonify(error='Нет доступа'),403
    c.execute('DELETE FROM jobs WHERE id=?',(i,));c.commit();c.close();return jsonify(status='ok')

@app.post('/api/jobs/<int:i>/respond')
def respond(i):
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    c=db();j=c.execute('SELECT * FROM jobs WHERE id=?',(i,)).fetchone()
    if not j:c.close();return jsonify(error='Задание не найдено'),404
    if j['user_id']==u['id']:c.close();return jsonify(error='Нельзя откликнуться на своё задание'),400
    try:c.execute('INSERT INTO responses(job_id,user_id,message) VALUES(?,?,?)',(i,u['id'],str(body().get('message','')).strip()));c.commit()
    except sqlite3.IntegrityError:c.close();return jsonify(error='Вы уже откликались'),409
    c.close();return jsonify(status='ok'),201
@app.put('/api/responses/<int:i>')
def response_status(i):
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    st=body().get('status');c=db();r=c.execute('SELECT r.*,j.user_id owner FROM responses r JOIN jobs j ON j.id=r.job_id WHERE r.id=?',(i,)).fetchone()
    if not r:c.close();return jsonify(error='Отклик не найден'),404
    if r['owner']!=u['id']:c.close();return jsonify(error='Нет доступа'),403
    c.execute('UPDATE responses SET status=? WHERE id=?',(st,i))
    if st=='accepted':c.execute("UPDATE jobs SET status='completed' WHERE id=?",(r['job_id'],));c.execute("UPDATE responses SET status='rejected' WHERE job_id=? AND id<>? AND status='pending'",(r['job_id'],i));c.execute('UPDATE users SET completed_jobs=completed_jobs+1 WHERE id=?',(r['user_id'],))
    c.commit();c.close();return jsonify(status='ok')

@app.get('/api/favorites')
def favorites():
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    c=db();rs=c.execute('SELECT j.*,u.name author_name,u.rating author_rating,u.avatar_url author_avatar,u.id author_id FROM favorites f JOIN jobs j ON j.id=f.job_id JOIN users u ON u.id=j.user_id WHERE f.user_id=? ORDER BY f.created_at DESC',(u['id'],)).fetchall();c.close();return jsonify([jobrow(r) for r in rs])
@app.post('/api/favorites/<int:i>')
def favorite(i):
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    c=db();r=c.execute('SELECT id FROM favorites WHERE user_id=? AND job_id=?',(u['id'],i)).fetchone()
    if r:c.execute('DELETE FROM favorites WHERE id=?',(r['id'],));a='removed'
    else:c.execute('INSERT INTO favorites(user_id,job_id) VALUES(?,?)',(u['id'],i));a='added'
    c.commit();c.close();return jsonify(action=a)

@app.post('/api/reviews')
def review():
    u=user();
    if not u:return jsonify(error='Не авторизован'),401
    d=body(); rating=int(d.get('rating',0)); to=int(d.get('to_user_id',0));
    if rating<1 or rating>5 or to==u['id']:return jsonify(error='Некорректная оценка'),400
    c=db();c.execute('INSERT INTO reviews(from_user_id,to_user_id,job_id,rating,comment) VALUES(?,?,?,?,?)',(u['id'],to,d.get('job_id'),rating,str(d.get('comment',''))));s=c.execute('SELECT AVG(rating) a,COUNT(*) n FROM reviews WHERE to_user_id=?',(to,)).fetchone();c.execute('UPDATE users SET rating=?,reviews_count=? WHERE id=?',(s['a'] or 0,s['n'],to));c.commit();c.close();return jsonify(status='ok'),201

@app.get('/manifest.json')
def manifest():
    return jsonify(name='Near Gig',short_name='Near Gig',start_url='/',scope='/',display='standalone',orientation='portrait-primary',theme_color='#17181c',background_color='#111216',icons=[{'src':'https://cdn-icons-png.flaticon.com/512/1041/1041916.png','sizes':'512x512','type':'image/png','purpose':'any maskable'}])
@app.get('/sw.js')
def sw():
    return Response("self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>self.clients.claim());",mimetype='application/javascript')

HTML='''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#5267A8">
<link rel="manifest" href="/manifest.json">
<script src="https://api-maps.yandex.ru/2.1/?lang=ru_RU"></script>
<title>Near Gig</title>
<style>
:root{--bg:#f4f6fa;--surface:#fff;--surface2:#eef2f8;--text:#202635;--muted:#747d8f;--line:#e0e5ee;--primary:#5267a8;--primary2:#697db9;--primarySoft:#e8ecf8;--success:#4f8a68;--successSoft:#e8f3ec;--danger:#b66b6b;--shadow:0 12px 35px rgba(31,42,68,.13);--shadow2:0 5px 18px rgba(31,42,68,.10)}
body.dark{--bg:#15171c;--surface:#1d2026;--surface2:#252932;--text:#e4e7ed;--muted:#a3a9b5;--line:#30343d;--primary:#929fc9;--primary2:#a1add3;--primarySoft:#2b3040;--success:#7cad91;--successSoft:#26372e;--danger:#d18a8a;--shadow:0 15px 38px rgba(0,0,0,.30);--shadow2:0 6px 20px rgba(0,0,0,.22)}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}html,body{margin:0;width:100%;height:100%;overflow:hidden;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text)}button,input,textarea,select{font:inherit}button{cursor:pointer}#map{position:absolute;inset:0}
.top{position:absolute;z-index:8;top:10px;left:10px;right:10px;display:flex;gap:8px;padding-top:env(safe-area-inset-top);animation:drop .45s ease both}.brand{display:flex;align-items:center;padding:0 14px;border-radius:17px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow2);font-weight:800;white-space:nowrap}.search{min-width:0;flex:1;display:flex;align-items:center;border-radius:17px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow2);overflow:hidden}.search input{min-width:0;flex:1;border:0;outline:0;background:transparent;color:var(--text);padding:13px}.iconbtn{width:46px;height:46px;flex:0 0 46px;border:1px solid var(--line);border-radius:16px;background:var(--surface);color:var(--text);box-shadow:var(--shadow2);transition:transform .18s,background .18s}.iconbtn:active,.nav button:active,.primary:active,.secondary:active{transform:scale(.95)}
.sheet{position:absolute;z-index:7;left:10px;right:10px;bottom:88px;max-height:66%;overflow:auto;border:1px solid var(--line);border-radius:24px;background:rgba(255,255,255,.94);background:var(--surface);box-shadow:var(--shadow);padding:15px;animation:sheetIn .3s ease both}.sheet h2{margin:2px 0 10px}.card{background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:14px;margin:8px 0;box-shadow:0 3px 12px rgba(30,40,65,.06);transition:transform .18s,box-shadow .18s}.card:active{transform:scale(.985)}.price{font-weight:800;color:var(--success)}.muted{color:var(--muted)}
.nav{position:absolute;z-index:9;left:10px;right:10px;bottom:calc(10px + env(safe-area-inset-bottom));display:flex;gap:3px;padding:6px;border:1px solid var(--line);border-radius:22px;background:rgba(255,255,255,.96);background:var(--surface);box-shadow:var(--shadow)}.nav button{position:relative;flex:1;border:0;background:transparent;color:var(--muted);padding:7px 3px;border-radius:16px;font-size:12px;line-height:1.25;transition:all .2s}.nav button.active{background:var(--primarySoft);color:var(--primary);font-weight:700}.nav .createDot{display:block;font-size:22px;line-height:18px;margin-bottom:2px}
.modal{position:fixed;z-index:30;inset:0;background:rgba(12,16,25,.58);backdrop-filter:blur(5px);display:flex;align-items:flex-end;justify-content:center;padding:10px}.modalbox{width:min(620px,100%);max-height:92vh;overflow:auto;border-radius:26px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow);padding:18px;animation:modalUp .3s ease both}.modalhead{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px}.close{border:0;background:var(--surface2);color:var(--muted);width:38px;height:38px;border-radius:12px}.field{width:100%;padding:13px 14px;border:1px solid var(--line);border-radius:14px;outline:0;background:var(--surface);color:var(--text);transition:border .2s,box-shadow .2s}.field:focus{border-color:var(--primary2);box-shadow:0 0 0 3px var(--primarySoft)}textarea.field{resize:vertical}.primary,.secondary,.ghost{width:100%;padding:13px;border-radius:14px;font-weight:750;border:0;transition:transform .18s,filter .18s}.primary{background:var(--primary);color:#fff}.primary:hover{filter:brightness(1.04)}.secondary{background:var(--primarySoft);color:var(--text)}.ghost{background:transparent;color:var(--muted);border:1px solid var(--line)}.row{display:flex;gap:9px}.row>*{min-width:0;flex:1}
.picker{position:fixed;z-index:50;inset:0;background:var(--bg)}#pm{position:absolute;inset:0}.hint{position:absolute;z-index:52;top:calc(72px + env(safe-area-inset-top));left:50%;transform:translateX(-50%);white-space:nowrap;padding:10px 15px;border-radius:15px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow2);font-weight:700}.pickerPin{position:absolute;z-index:51;left:50%;top:50%;width:34px;height:34px;transform:translate(-50%,-100%);border-radius:50% 50% 50% 0;background:var(--primary);border:4px solid #fff;box-shadow:0 5px 16px rgba(30,40,70,.28);rotate:-45deg;pointer-events:none}.pickerPin:after{content:"";position:absolute;left:8px;top:8px;width:10px;height:10px;border-radius:50%;background:#fff}.picker-actions{position:absolute;z-index:53;left:10px;right:10px;bottom:calc(10px + env(safe-area-inset-bottom));padding:14px;border-radius:23px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow)}
.toast{position:fixed;z-index:100;left:50%;bottom:calc(94px + env(safe-area-inset-bottom));transform:translate(-50%,20px);opacity:0;pointer-events:none;background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow);border-radius:15px;padding:12px 16px;max-width:calc(100% - 30px);transition:.25s}.toast.show{opacity:1;transform:translate(-50%,0)}.toggle{display:flex;align-items:center;justify-content:space-between;padding:13px 0;border-bottom:1px solid var(--line)}.switch{width:48px;height:28px;border-radius:30px;background:var(--line);position:relative;border:0}.switch:after{content:"";position:absolute;width:22px;height:22px;top:3px;left:3px;border-radius:50%;background:#fff;transition:.2s}.switch.on{background:var(--success)}.switch.on:after{transform:translateX(20px)}.hidden{display:none!important}
@media(min-width:800px){.top{top:18px;left:18px;right:18px;max-width:780px}.brand{padding:0 18px}.nav{left:50%;right:auto;width:560px;transform:translateX(-50%)}.sheet{left:20px;right:auto;width:470px;bottom:92px;max-height:68%}.modal{align-items:center;padding:28px}.modalbox{border-radius:26px}.picker-actions{left:50%;right:auto;transform:translateX(-50%);width:520px}.hint{top:90px}}
@media(max-width:420px){.brand{padding:0 11px}.search input{padding:12px 8px}.top{gap:6px}.iconbtn{width:43px;height:43px;flex-basis:43px}.nav{left:7px;right:7px}.sheet{left:7px;right:7px}.modal{padding:0}.modalbox{border-radius:26px 26px 0 0}}
@keyframes drop{from{opacity:0;transform:translateY(-12px)}to{opacity:1;transform:none}}@keyframes sheetIn{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}@keyframes modalUp{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:none}}
</style></head>
<body>
<div id="map"></div>
<div class="top"><div class="brand">Near Gig</div><div class="search"><input id="q" placeholder="Найти подработку..." onkeydown="if(event.key==='Enter')search()"><button class="iconbtn" onclick="search()">⌕</button></div><button class="iconbtn" onclick="locate()">⌖</button></div>
<div id="sheet" class="sheet hidden"></div>
<div class="nav"><button id="nmap" class="active" onclick="goMap()">⌖<br>Карта</button><button id="njobs" onclick="jobs()">▤<br>Задания</button><button id="ncreate" onclick="create()"><span class="createDot">＋</span>Создать</button><button id="nprof" onclick="profile()">♙<br>Профиль</button></div>
<div id="toast" class="toast"></div>

<div id="auth" class="modal hidden"><div class="modalbox"><div class="modalhead"><h2 id="at">Вход</h2><button class="close" onclick="closeM('auth')">×</button></div><div id="login"><input id="le" class="field" placeholder="Email"><br><br><input id="lp" type="password" class="field" placeholder="Пароль"><br><br><button class="primary" onclick="doLogin()">Войти</button></div><div id="reg" class="hidden"><div id="rf"></div><button class="primary" onclick="doReg()">Создать аккаунт</button></div><br><button class="ghost" onclick="toggleAuth()" id="authSwitch">Нет аккаунта? Зарегистрироваться</button></div></div>

<div id="createM" class="modal hidden"><div class="modalbox"><div class="modalhead"><h2>Новая подработка</h2><button class="close" onclick="closeM('createM')">×</button></div><input id="jt" class="field" placeholder="Название задания"><br><br><textarea id="jd" class="field" rows="4" placeholder="Что нужно сделать?"></textarea><br><br><div class="row"><input id="jp" type="number" min="1" class="field" placeholder="Цена, ₽"><select id="jc" class="field"><option>Курьер</option><option>Уборка</option><option>Ремонт</option><option>IT</option><option>Помощь по дому</option><option>Другое</option></select></div><br><div class="card"><b>📍 Место выполнения</b><div id="addr" class="muted" style="margin-top:5px">Точка не выбрана</div><br><button class="secondary" onclick="pick()">Выбрать точку на карте</button></div><button class="primary" onclick="saveJob()">Опубликовать задание</button></div></div>
<div id="detail" class="modal hidden"><div class="modalbox"><div class="modalhead"><h2 id="dt"></h2><button class="close" onclick="closeM('detail')">×</button></div><div id="dc"></div></div></div>
<div id="prof" class="modal hidden"><div class="modalbox"><div class="modalhead"><h2>Профиль</h2><button class="close" onclick="closeM('prof')">×</button></div><div id="pc"></div></div></div>
<div id="picker" class="picker hidden"><div id="pm"></div><div class="hint">Нажмите на карте в нужном месте</div><div class="pickerPin"></div><div class="picker-actions"><div id="pa" class="muted">Точка не выбрана</div><br><button class="primary" onclick="confirmPick()">✓ Подтвердить место</button><br><br><button class="ghost" onclick="closePick()">Отмена</button></div></div>

<script>
let map,pm,mark,pc=null,chosen=null,userNow=null,t=localStorage.getItem('near_token')||'',auth='login',dark=localStorage.getItem('near_dark')==='1';
document.body.classList.toggle('dark',dark);const $=x=>document.getElementById(x);
const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function api(u,o={}){o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});if(t)o.headers.Authorization='Bearer '+t;let r=await fetch(u,o),d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.error||'Ошибка');return d}
function toast(x){const e=$('toast');e.textContent=x;e.classList.add('show');clearTimeout(window._toast);window._toast=setTimeout(()=>e.classList.remove('show'),2600)}
function closeM(x){$(x).classList.add('hidden')}
function setActive(id){document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));$(id)?.classList.add('active')}
function init(){ymaps.ready(()=>{map=new ymaps.Map('map',{center:[55.7558,37.6173],zoom:12,controls:['zoomControl','typeSelector'],suppressMapOpenBlock:true});load()});restore()}
async function load(){if(!map)return;map.geoObjects.removeAll();try{for(const j of await api('/api/jobs?status=active')){if(j.lat==null||j.lng==null)continue;let p=new ymaps.Placemark([j.lat,j.lng],{balloonContent:'<b>'+esc(j.title)+'</b><br><span>'+esc(j.address||'Место на карте')+'</span><br><b>'+j.price+' ₽</b>'},{preset:'islands#blueCircleDotIcon'});p.events.add('click',()=>show(j.id));map.geoObjects.add(p)}}catch(e){toast(e.message)}}
function locate(){navigator.geolocation?.getCurrentPosition(p=>{map.setCenter([p.coords.latitude,p.coords.longitude],15);toast('Местоположение найдено')},()=>toast('Не удалось определить местоположение'),{enableHighAccuracy:true,timeout:10000})}
function goMap(){setActive('nmap');$('sheet').classList.add('hidden');map?.container.fitToViewport()}
async function jobs(){setActive('njobs');let s=$('sheet');s.classList.remove('hidden');s.innerHTML='<h2>Задания</h2><div id="jl">Загрузка...</div>';try{let a=await api('/api/jobs?status=active');$('jl').innerHTML=a.map(card).join('')||'<span class="muted">Пока нет активных заданий</span>'}catch(e){$('jl').textContent=e.message}}
function card(j){return `<div class="card" onclick="show(${j.id})"><div><b>${esc(j.title)}</b><span style="float:right" class="price">${j.price} ₽</span></div><div class="muted" style="margin-top:6px">${esc(j.description||'')}</div><small class="muted">${esc(j.category)} · ${esc(j.address||'Точка на карте')}</small></div>`}
async function search(){let q=$('q').value.trim();if(!q)return jobs();let s=$('sheet');s.classList.remove('hidden');s.innerHTML='<h2>Поиск</h2><div class="muted">Ищем...</div>';try{let a=await api('/api/jobs?status=active&search='+encodeURIComponent(q));s.innerHTML='<h2>Результаты</h2>'+(a.map(card).join('')||'<span class="muted">Ничего не найдено</span>')}catch(e){s.innerHTML='<span class="muted">'+esc(e.message)+'</span>'}}
function create(){setActive('ncreate');if(!userNow)return openAuth();$('createM').classList.remove('hidden')}
function pick(){if(!map)return;pc=null;$('pa').textContent='Точка не выбрана';$('picker').classList.remove('hidden');setTimeout(()=>{if(!pm){pm=new ymaps.Map('pm',{center:map.getCenter(),zoom:15,controls:['zoomControl']});pm.events.add('click',e=>point(e.get('coords')))}else{pm.container.fitToViewport();pm.setCenter(map.getCenter(),15)}},80)}
function point(c){pc=c;if(mark)pm.geoObjects.remove(mark);mark=new ymaps.Placemark(c,{balloonContent:'Выбранное место'},{preset:'islands#redDotIcon'});pm.geoObjects.add(mark);$('pa').textContent='Определяем адрес...';ymaps.geocode(c).then(r=>{let x=r.geoObjects.get(0);$('pa').textContent=x?x.getAddressLine():'Точка: '+c[0].toFixed(5)+', '+c[1].toFixed(5)})}
function confirmPick(){if(!pc)return toast('Сначала выберите точку на карте');chosen=[...pc];$('addr').textContent=$('pa').textContent;closePick();toast('Место выбрано')}
function closePick(){ $('picker').classList.add('hidden') }
async function saveJob(){if(!chosen)return toast('Выберите точку на карте');let title=$('jt').value.trim(),price=Number($('jp').value);if(!title||!price)return toast('Заполните название и цену');try{await api('/api/jobs',{method:'POST',body:JSON.stringify({title,description:$('jd').value.trim(),price,category:$('jc').value,lat:chosen[0],lng:chosen[1],address:$('addr').textContent})});closeM('createM');$('jt').value='';$('jd').value='';$('jp').value='';chosen=null;$('addr').textContent='Точка не выбрана';await load();goMap();toast('Задание опубликовано')}catch(e){toast(e.message)}}
async function show(id){try{let j=await api('/api/jobs/'+id);$('dt').textContent=j.title;let h=`<div class="card"><div class="price" style="font-size:22px">${j.price} ₽</div><p>${esc(j.description||'Без описания')}</p><div class="muted">📍 ${esc(j.address||'Место на карте')}</div></div><button class="secondary" onclick="map.setCenter([${j.lat},${j.lng}],16);closeM('detail');goMap()">Показать на карте</button><br><br><div class="muted">Автор: ${esc(j.author.name)} · ⭐ ${j.author.rating}</div>`;if(userNow&&userNow.id!==j.user_id&&j.status==='active')h+=`<br><button class="primary" onclick="respond(${j.id})">Откликнуться</button><br><br><button class="secondary" onclick="fav(${j.id})">♡ В избранное</button>`;$('dc').innerHTML=h;$('detail').classList.remove('hidden')}catch(e){toast(e.message)}}
async function respond(id){let m=prompt('Сообщение заказчику (необязательно)')||'';try{await api('/api/jobs/'+id+'/respond',{method:'POST',body:JSON.stringify({message:m})});toast('Отклик отправлен')}catch(e){toast(e.message)}}
async function fav(id){try{let x=await api('/api/favorites/'+id,{method:'POST'});toast(x.action==='added'?'Добавлено в избранное':'Удалено из избранного')}catch(e){toast(e.message)}}
function openAuth(){auth='login';$('auth').classList.remove('hidden');$('login').classList.remove('hidden');$('reg').classList.add('hidden');$('at').textContent='Вход';$('authSwitch').textContent='Нет аккаунта? Зарегистрироваться'}
function toggleAuth(){auth=auth==='login'?'reg':'login';$('login').classList.toggle('hidden',auth!=='login');$('reg').classList.toggle('hidden',auth!=='reg');$('at').textContent=auth==='login'?'Вход':'Регистрация';$('authSwitch').textContent=auth==='login'?'Нет аккаунта? Зарегистрироваться':'Уже есть аккаунт? Войти';if(auth==='reg'&&!$('rf').innerHTML)$('rf').innerHTML='<input id="rn" class="field" placeholder="Имя и фамилия"><br><br><input id="rph" class="field" placeholder="Телефон"><br><br><label class="muted">Дата рождения</label><br><input id="rb" type="date" class="field"><br><br><input id="ro" class="field" placeholder="Род деятельности"><br><br><select id="rr" class="field"><option value="executor">Исполнитель</option><option value="customer">Заказчик</option></select><br><br><input id="re" class="field" placeholder="Email"><br><br><input id="rp" type="password" class="field" placeholder="Пароль (минимум 6 символов)"><br><br><input id="rs" class="field" placeholder="Серия паспорта"><br><br><input id="rnumb" class="field" placeholder="Номер паспорта"><br><br><input id="ri" class="field" placeholder="Кем выдан паспорт"><br><br><label class="muted">Дата выдачи паспорта</label><br><input id="rid" type="date" class="field"><br><br>'}
async function doLogin(){try{let x=await api('/api/login',{method:'POST',body:JSON.stringify({email:$('le').value.trim(),password:$('lp').value})});t=x.token;userNow=x.user;localStorage.setItem('near_token',t);closeM('auth');toast('Вход выполнен')}catch(e){toast(e.message)}}
async function doReg(){let x={name:$('rn').value,phone:$('rph').value,birth_date:$('rb').value,occupation:$('ro').value,role:$('rr').value,email:$('re').value,password:$('rp').value,passport_series:$('rs').value,passport_number:$('rnumb').value,passport_issued_by:$('ri').value,passport_issue_date:$('rid').value};try{let z=await api('/api/register',{method:'POST',body:JSON.stringify(x)});t=z.token;userNow=z.user;localStorage.setItem('near_token',t);closeM('auth');toast('Аккаунт создан')}catch(e){toast(e.message)}}
async function profile(){if(!userNow)return openAuth();setActive('nprof');$('pc').innerHTML=`<div class="card"><h3 style="margin-top:0">${esc(userNow.name)}</h3><div class="muted">${esc(userNow.email)}</div><p>📱 ${esc(userNow.phone||'—')}</p><p>🎂 ${esc(userNow.birth_date||'—')}</p><p>💼 ${esc(userNow.occupation||'—')}</p><p>⭐ ${userNow.rating} · ${userNow.reviews_count} отзывов</p></div><div class="toggle"><span>Тёмная тема<br><small class="muted">Мягкая цветовая схема для вечера</small></span><button class="switch ${dark?'on':''}" onclick="toggleDark(this)"></button></div><br><button class="ghost" onclick="logout()">Выйти из аккаунта</button>`;$('prof').classList.remove('hidden')}
function toggleDark(b){dark=!dark;localStorage.setItem('near_dark',dark?'1':'0');document.body.classList.toggle('dark',dark);b.classList.toggle('on',dark)}
async function logout(){try{await api('/api/logout',{method:'POST'})}catch{}t='';userNow=null;localStorage.removeItem('near_token');closeM('prof');setActive('nmap');toast('Вы вышли из аккаунта')}
async function restore(){if(!t)return;try{userNow=await api('/api/me')}catch{t='';localStorage.removeItem('near_token')}}
init();
</script></body></html>'''
@app.get('/')
def index(): return HTML
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
