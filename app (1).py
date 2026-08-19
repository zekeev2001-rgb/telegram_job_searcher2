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

HTML='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover"><meta name="theme-color" content="#17181c"><link rel="manifest" href="/manifest.json"><script src="https://api-maps.yandex.ru/2.1/?lang=ru_RU"></script><title>Near Gig</title><style>:root{--bg:#f5f6f8;--s:#fff;--t:#17181c;--m:#747983;--l:#e4e6eb;--a:#6366f1;--as:#eef0ff}body.dark{--bg:#111216;--s:#191a1f;--t:#e5e7eb;--m:#9da1aa;--l:#2b2d34;--a:#a4a7e8;--as:#292a3b}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:15px system-ui;overflow:hidden}#map,#picker{position:absolute;inset:0}.top{position:absolute;z-index:5;top:10px;left:10px;right:10px;display:flex;gap:8px;padding-top:env(safe-area-inset-top)}.brand,.search,.ib,.nav,.sheet,.card,.modalbox,.pickerbox{background:var(--s);border:1px solid var(--l);box-shadow:0 8px 30px #0002}.brand,.search,.ib,.nav{border-radius:16px}.brand{padding:12px;font-weight:800}.search{flex:1;display:flex}.search input{min-width:0;flex:1;border:0;outline:0;background:transparent;color:var(--t);padding:12px}.ib{width:46px;height:46px;border:1px solid var(--l);color:var(--t)}.nav{position:absolute;z-index:5;left:10px;right:10px;bottom:calc(10px + env(safe-area-inset-bottom));display:flex;padding:5px}.nav button{flex:1;border:0;background:transparent;color:var(--m);padding:8px;border-radius:13px}.nav button.active{background:var(--as);color:var(--a)}.sheet{position:absolute;z-index:10;left:10px;right:10px;bottom:85px;max-height:72%;overflow:auto;border-radius:22px;padding:14px}.modal{position:fixed;z-index:20;inset:0;background:#0007;display:flex;align-items:center;justify-content:center;padding:12px}.modalbox{width:min(620px,100%);max-height:92vh;overflow:auto;border-radius:22px;padding:16px}.field{width:100%;padding:12px;border:1px solid var(--l);border-radius:13px;background:var(--s);color:var(--t)}.primary,.secondary,.ghost{width:100%;padding:12px;border-radius:13px;border:0;font-weight:700}.primary{background:var(--a);color:white}.secondary{background:var(--as);color:var(--t)}.ghost{background:transparent;border:1px solid var(--l);color:var(--m)}.card{border-radius:16px;padding:13px;margin:8px 0}.muted{color:var(--m)}.row{display:flex;gap:8px}.hidden{display:none!important}.picker{position:fixed;inset:0;z-index:30;background:var(--bg)}.picker-actions{position:absolute;z-index:31;left:10px;right:10px;bottom:calc(10px + env(safe-area-inset-bottom));padding:12px;border-radius:20px;background:var(--s);border:1px solid var(--l);box-shadow:0 8px 30px #0003}.hint{position:absolute;z-index:31;top:75px;left:50%;transform:translateX(-50%);white-space:nowrap;background:var(--s);padding:10px 14px;border-radius:14px;border:1px solid var(--l)}@media(min-width:800px){.nav{left:50%;right:auto;width:520px;transform:translateX(-50%)}.sheet{left:20px;right:auto;width:470px}.modal{padding:30px}}</style></head><body><div id="map"></div><div class="top"><div class="brand">Near Gig</div><div class="search"><input id="q" placeholder="Найти подработку..." onkeydown="if(event.key==='Enter')search()"><button class="ib" onclick="search()">⌕</button></div><button class="ib" onclick="locate()">⌖</button></div><div id="sheet" class="sheet hidden"></div><div class="nav"><button id="nmap" class="active" onclick="goMap()">⌖<br>Карта</button><button onclick="jobs()">▤<br>Задания</button><button onclick="create()">＋<br>Создать</button><button id="nprof" onclick="profile()">♙<br>Профиль</button></div>
<div id="auth" class="modal hidden"><div class="modalbox"><h2 id="at">Вход</h2><div id="login"><input id="le" class="field" placeholder="Email"><br><br><input id="lp" type="password" class="field" placeholder="Пароль"><br><br><button class="primary" onclick="doLogin()">Войти</button></div><div id="reg" class="hidden"><div id="rf"></div><button class="primary" onclick="doReg()">Создать аккаунт</button></div><br><button class="ghost" onclick="toggleAuth()">Нет аккаунта? Зарегистрироваться</button><br><br><button class="ghost" onclick="closeM('auth')">Закрыть</button></div></div>
<div id="createM" class="modal hidden"><div class="modalbox"><h2>Новая подработка</h2><input id="jt" class="field" placeholder="Название"><br><br><textarea id="jd" class="field" rows="4" placeholder="Описание"></textarea><br><br><div class="row"><input id="jp" type="number" class="field" placeholder="Цена"><select id="jc" class="field"><option>Курьер</option><option>Уборка</option><option>Ремонт</option><option>IT</option><option>Помощь по дому</option><option>Другое</option></select></div><br><div class="card"><b>Место</b><div id="addr" class="muted">Точка не выбрана</div><br><button class="secondary" onclick="pick()">Выбрать точку на карте</button></div><button class="primary" onclick="saveJob()">Опубликовать</button><br><br><button class="ghost" onclick="closeM('createM')">Закрыть</button></div></div>
<div id="detail" class="modal hidden"><div class="modalbox"><h2 id="dt"></h2><div id="dc"></div><br><button class="ghost" onclick="closeM('detail')">Закрыть</button></div></div><div id="prof" class="modal hidden"><div class="modalbox"><h2>Профиль</h2><div id="pc"></div><button class="ghost" onclick="closeM('prof')">Закрыть</button></div></div>
<div id="picker" class="picker hidden"><div id="pm" style="position:absolute;inset:0"></div><div class="hint">Нажмите или коснитесь нужной точки</div><div class="picker-actions"><div id="pa" class="muted">Точка не выбрана</div><br><button class="primary" onclick="confirmPick()">Подтвердить место</button><br><br><button class="ghost" onclick="closePick()">Отмена</button></div></div>
<script>let map,pm,mark,pc=null,chosen=null,userNow=null,t=localStorage.getItem('near_token')||'',auth='login',dark=localStorage.getItem('near_dark')==='1';document.body.classList.toggle('dark',dark);const $=x=>document.getElementById(x);const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));async function api(u,o={}){o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});if(t)o.headers.Authorization='Bearer '+t;let r=await fetch(u,o),d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.error||'Ошибка');return d}function closeM(x){$(x).classList.add('hidden')}function init(){ymaps.ready(()=>{map=new ymaps.Map('map',{center:[55.7558,37.6173],zoom:12,controls:['zoomControl','typeSelector']});load()});restore()}async function load(){if(!map)return;map.geoObjects.removeAll();for(const j of await api('/api/jobs?status=active')){if(j.lat==null)continue;let p=new ymaps.Placemark([j.lat,j.lng],{balloonContent:esc(j.title)+'<br>'+j.price+' ₽'});p.events.add('click',()=>show(j.id));map.geoObjects.add(p)}}function locate(){navigator.geolocation?.getCurrentPosition(p=>map.setCenter([p.coords.latitude,p.coords.longitude],15),()=>alert('Не удалось определить местоположение'))}function goMap(){$('sheet').classList.add('hidden')}function jobs(){let s=$('sheet');s.classList.remove('hidden');s.innerHTML='<h2>Задания</h2><div id="jl">Загрузка...</div>';api('/api/jobs?status=active').then(a=>$('jl').innerHTML=a.map(card).join('')||'<span class="muted">Нет заданий</span>')}function card(j){return `<div class="card" onclick="show(${j.id})"><b>${esc(j.title)}</b><span style="float:right"><b>${j.price} ₽</b></span><div class="muted">${esc(j.description||'')}</div><small>${esc(j.category)} · ${esc(j.address||'Точка на карте')}</small></div>`}function search(){let q=$('q').value;api('/api/jobs?status=active&search='+encodeURIComponent(q)).then(a=>{$('sheet').classList.remove('hidden');$('sheet').innerHTML=a.map(card).join('')||'<span class="muted">Ничего не найдено</span>'})}function create(){if(!userNow)return openAuth();$('createM').classList.remove('hidden')}function pick(){$('picker').classList.remove('hidden');setTimeout(()=>{if(!pm){pm=new ymaps.Map('pm',{center:map.getCenter(),zoom:13,controls:['zoomControl']});pm.events.add('click',e=>point(e.get('coords')))}else pm.container.fitToViewport()},50)}function point(c){pc=c;if(mark)pm.geoObjects.remove(mark);mark=new ymaps.Placemark(c,{}, {preset:'islands#redDotIcon'});pm.geoObjects.add(mark);$('pa').textContent='Выбрана точка: '+c[0].toFixed(6)+', '+c[1].toFixed(6);ymaps.geocode(c).then(r=>{let x=r.geoObjects.get(0);if(x)$('pa').textContent=x.getAddressLine()})}function confirmPick(){if(!pc)return alert('Выберите точку');chosen=[...pc];$('addr').textContent=$('pa').textContent;closePick()}function closePick(){$('picker').classList.add('hidden')}async function saveJob(){if(!chosen)return alert('Выберите точку на карте');try{await api('/api/jobs',{method:'POST',body:JSON.stringify({title:$('jt').value,description:$('jd').value,price:Number($('jp').value),category:$('jc').value,lat:chosen[0],lng:chosen[1],address:$('addr').textContent})});closeM('createM');chosen=null;load();alert('Задание опубликовано')}catch(e){alert(e.message)}}async function show(id){let j=await api('/api/jobs/'+id);$('dt').textContent=j.title;let h=`<div class="card"><b>${j.price} ₽</b><br>${esc(j.description||'')}</div><div class="muted">${esc(j.address||'Место на карте')}</div><br><button class="secondary" onclick="map.setCenter([${j.lat},${j.lng}],16);closeM('detail')">Показать на карте</button><br><br><div class="muted">Автор: ${esc(j.author.name)} · ⭐ ${j.author.rating}</div>`;if(userNow&&userNow.id!==j.user_id&&j.status==='active')h+=`<br><button class="primary" onclick="respond(${j.id})">Откликнуться</button><br><br><button class="secondary" onclick="fav(${j.id})">В избранное</button>`;$('dc').innerHTML=h;$('detail').classList.remove('hidden')}async function respond(id){let m=prompt('Сообщение')||'';try{await api('/api/jobs/'+id+'/respond',{method:'POST',body:JSON.stringify({message:m})});alert('Отклик отправлен')}catch(e){alert(e.message)}}async function fav(id){try{let x=await api('/api/favorites/'+id,{method:'POST'});alert(x.action==='added'?'Добавлено':'Удалено')}catch(e){alert(e.message)}}function openAuth(){$('auth').classList.remove('hidden')}function toggleAuth(){auth=auth==='login'?'reg':'login';$('login').classList.toggle('hidden',auth!=='login');$('reg').classList.toggle('hidden',auth!=='reg');$('at').textContent=auth==='login'?'Вход':'Регистрация';if(auth==='reg')$('rf').innerHTML='<input id="rn" class="field" placeholder="Имя и фамилия"><br><br><input id="rph" class="field" placeholder="Телефон"><br><br><input id="rb" type="date" class="field"><br><br><input id="ro" class="field" placeholder="Род деятельности"><br><br><select id="rr" class="field"><option value="executor">Исполнитель</option><option value="customer">Заказчик</option></select><br><br><input id="re" class="field" placeholder="Email"><br><br><input id="rp" type="password" class="field" placeholder="Пароль"><br><br><input id="rs" class="field" placeholder="Серия паспорта"><br><br><input id="rnumb" class="field" placeholder="Номер паспорта"><br><br><input id="ri" class="field" placeholder="Кем выдан"><br><br><input id="rid" type="date" class="field"><br><br>'}async function doLogin(){try{let x=await api('/api/login',{method:'POST',body:JSON.stringify({email:$('le').value,password:$('lp').value})});t=x.token;userNow=x.user;localStorage.setItem('near_token',t);closeM('auth');alert('Вход выполнен')}catch(e){alert(e.message)}}async function doReg(){let x={name:$('rn').value,phone:$('rph').value,birth_date:$('rb').value,occupation:$('ro').value,role:$('rr').value,email:$('re').value,password:$('rp').value,passport_series:$('rs').value,passport_number:$('rnumb').value,passport_issued_by:$('ri').value,passport_issue_date:$('rid').value};try{let z=await api('/api/register',{method:'POST',body:JSON.stringify(x)});t=z.token;userNow=z.user;localStorage.setItem('near_token',t);closeM('auth');alert('Аккаунт создан')}catch(e){alert(e.message)}}async function profile(){if(!userNow)return openAuth();$('pc').innerHTML=`<div class="card"><h3>${esc(userNow.name)}</h3><div class="muted">${esc(userNow.email)}</div><div>Телефон: ${esc(userNow.phone)}</div><div>Дата рождения: ${esc(userNow.birth_date)}</div><div>Род деятельности: ${esc(userNow.occupation)}</div><div>⭐ ${userNow.rating} · ${userNow.reviews_count} отзывов</div></div><button class="secondary" onclick="dark=!dark;localStorage.setItem('near_dark',dark?'1':'0');document.body.classList.toggle('dark',dark)">Тёмная тема</button><br><br><button class="ghost" onclick="logout()">Выйти</button>`;$('prof').classList.remove('hidden')}async function logout(){try{await api('/api/logout',{method:'POST'})}catch{}t='';userNow=null;localStorage.removeItem('near_token');closeM('prof');alert('Вы вышли')}async function restore(){if(!t)return;try{userNow=await api('/api/me')}catch{t='';localStorage.removeItem('near_token')}}init();</script></body></html>'''
@app.get('/')
def index(): return HTML
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
