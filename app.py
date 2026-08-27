import os, sqlite3, secrets, hashlib
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from flask import Flask, request, jsonify, Response, render_template
from cryptography.fernet import Fernet

BASE=os.path.dirname(os.path.abspath(__file__))
DB_PATH=os.environ.get('DB_PATH', os.path.join(BASE,'jobs.db'))
SECRET_KEY=os.environ.get('SECRET_KEY', secrets.token_hex(32))
PASSPORT_KEY=os.environ.get('PASSPORT_ENCRYPTION_KEY','')
app=Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key=SECRET_KEY
fernet=Fernet(PASSPORT_KEY.encode()) if PASSPORT_KEY else None
AVATAR='https://cdn-icons-png.flaticon.com/512/149/149071.png'

def db():
    os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=30); c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); return c

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
    except Exception: return False
def enc(x):
    if not x:return ''
    if not fernet: raise RuntimeError('На сервере не задан PASSPORT_ENCRYPTION_KEY. Добавьте эту переменную в Render.')
    return fernet.encrypt(x.encode()).decode()
def dec(x):
    if not x or not fernet:return ''
    try:return fernet.decrypt(x.encode()).decode()
    except Exception:return ''
def token():
    a=request.headers.get('Authorization',''); return a[7:].strip() if a.lower().startswith('bearer ') else ''
def user():
    t=token()
    if not t:return None
    c=db(); r=c.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires_at>datetime('now')",(t,)).fetchone(); c.close(); return dict(r) if r else None
def pub(u,private=False):
    x=dict(u); r={'id':x['id'],'email':x['email'],'name':x['name'],'phone':x.get('phone',''),'birth_date':x.get('birth_date',''),'occupation':x.get('occupation',''),'role':x.get('role','executor'),'avatar_url':x.get('avatar_url') or AVATAR,'rating':round(float(x.get('rating') or 0),2),'reviews_count':x.get('reviews_count',0),'completed_jobs':x.get('completed_jobs',0)}
    if private:r.update(passport_series=dec(x.get('passport_series_enc')),passport_number=dec(x.get('passport_number_enc')),passport_issued_by=dec(x.get('passport_issued_by_enc')),passport_issue_date=x.get('passport_issue_date',''))
    return r
def body(): return request.get_json(silent=True) or {}
def dist(a,b,c,d):
    if None in(a,b,c,d):return None
    q=radians(c-a); w=radians(d-b); z=sin(q/2)**2+cos(radians(a))*cos(radians(c))*sin(w/2)**2; return 6371*2*atan2(sqrt(z),sqrt(1-z))
def jobrow(r,lat=None,lng=None):
    x=dict(r); x['author']={'id':x.pop('author_id'),'name':x.pop('author_name'),'rating':x.pop('author_rating') or 0,'avatar':x.pop('author_avatar') or AVATAR}; x['distance']=dist(lat,lng,x['lat'],x['lng']) if lat is not None and lng is not None else None; return x

@app.post('/api/register')
def register():
    d=body(); fields=['email','password','name','phone','birth_date','occupation','passport_series','passport_number','passport_issued_by','passport_issue_date']
    if any(not str(d.get(x,'')).strip() for x in fields):return jsonify(error='Заполните все поля регистрации'),400
    if len(str(d['password']))<6:return jsonify(error='Пароль минимум 6 символов'),400
    role=d.get('role','executor') if d.get('role') in ('executor','customer') else 'executor'
    try: es,en,ei=enc(str(d['passport_series']).strip()),enc(str(d['passport_number']).strip()),enc(str(d['passport_issued_by']).strip())
    except RuntimeError as e:return jsonify(error=str(e)),500
    email=str(d['email']).strip().lower(); c=db()
    if c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone():c.close();return jsonify(error='Этот email уже зарегистрирован. Войдите в аккаунт.'),409
    cur=c.execute('INSERT INTO users(email,password_hash,name,phone,birth_date,occupation,role,avatar_url,passport_series_enc,passport_number_enc,passport_issued_by_enc,passport_issue_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(email,pwd(str(d['password'])),str(d['name']).strip(),str(d['phone']).strip(),str(d['birth_date']),str(d['occupation']).strip(),role,AVATAR,es,en,ei,str(d['passport_issue_date'])))
    uid=cur.lastrowid; t=secrets.token_hex(32); c.execute('INSERT INTO sessions(user_id,token,expires_at) VALUES(?,?,?)',(uid,t,(datetime.utcnow()+timedelta(days=30)).isoformat())); c.commit(); u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return jsonify(token=t,user=pub(u,True)),201

@app.post('/api/login')
def login():
    d=body(); c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(str(d.get('email','')).strip().lower(),)).fetchone()
    if not u or not check(str(d.get('password','')),u['password_hash']):c.close();return jsonify(error='Неверный email или пароль'),401
    t=secrets.token_hex(32); c.execute('INSERT INTO sessions(user_id,token,expires_at) VALUES(?,?,?)',(u['id'],t,(datetime.utcnow()+timedelta(days=30)).isoformat())); c.execute("UPDATE users SET last_login=datetime('now') WHERE id=?",(u['id'],)); c.commit(); u=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); c.close(); return jsonify(token=t,user=pub(u,True))
@app.post('/api/logout')
def logout():
    c=db(); c.execute('DELETE FROM sessions WHERE token=?',(token(),)); c.commit(); c.close(); return jsonify(status='ok')
@app.get('/api/me')
def me():
    u=user(); return (jsonify(pub(u,True)),200) if u else (jsonify(error='Не авторизован'),401)
@app.put('/api/profile')
def profile():
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    d=body(); name=str(d.get('name',u['name'])).strip(); phone=str(d.get('phone',u.get('phone',''))).strip(); birth=str(d.get('birth_date',u.get('birth_date',''))); occ=str(d.get('occupation',u.get('occupation',''))).strip()
    try: es,en,ei=enc(str(d.get('passport_series',dec(u.get('passport_series_enc')))).strip()),enc(str(d.get('passport_number',dec(u.get('passport_number_enc')))).strip()),enc(str(d.get('passport_issued_by',dec(u.get('passport_issued_by_enc')))).strip())
    except RuntimeError as e:return jsonify(error=str(e)),500
    c=db(); c.execute('UPDATE users SET name=?,phone=?,birth_date=?,occupation=?,passport_series_enc=?,passport_number_enc=?,passport_issued_by_enc=?,passport_issue_date=? WHERE id=?',(name,phone,birth,occ,es,en,ei,str(d.get('passport_issue_date',u.get('passport_issue_date',''))),u['id'])); c.commit(); u=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); c.close(); return jsonify(pub(u,True))

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
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    d=body()
    try:price=float(d['price']);lat=float(d['lat']);lng=float(d['lng'])
    except:return jsonify(error='Укажите цену и точку на карте'),400
    title=str(d.get('title','')).strip()
    if not title:return jsonify(error='Укажите название'),400
    c=db(); cur=c.execute('INSERT INTO jobs(user_id,title,description,price,lat,lng,address,category,expires_at) VALUES(?,?,?,?,?,?,?,?,?)',(u['id'],title,str(d.get('description','')).strip(),price,lat,lng,str(d.get('address','')).strip(),d.get('category','Другое'),(datetime.utcnow()+timedelta(days=30)).isoformat())); c.commit(); i=cur.lastrowid; c.close(); return jsonify(status='ok',job_id=i),201
@app.put('/api/jobs/<int:i>')
def update_job(i):
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    d=body(); c=db(); j=c.execute('SELECT * FROM jobs WHERE id=?',(i,)).fetchone()
    if not j:c.close();return jsonify(error='Не найдено'),404
    if j['user_id']!=u['id']:c.close();return jsonify(error='Нет доступа'),403
    c.execute('UPDATE jobs SET title=?,description=?,price=?,lat=?,lng=?,address=?,category=?,status=? WHERE id=?',(d.get('title',j['title']),d.get('description',j['description']),d.get('price',j['price']),d.get('lat',j['lat']),d.get('lng',j['lng']),d.get('address',j['address']),d.get('category',j['category']),d.get('status',j['status']),i)); c.commit(); c.close(); return jsonify(status='ok')
@app.delete('/api/jobs/<int:i>')
def delete_job(i):
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    c=db(); j=c.execute('SELECT user_id FROM jobs WHERE id=?',(i,)).fetchone()
    if not j:c.close();return jsonify(error='Не найдено'),404
    if j['user_id']!=u['id']:c.close();return jsonify(error='Нет доступа'),403
    c.execute('DELETE FROM jobs WHERE id=?',(i,)); c.commit(); c.close(); return jsonify(status='ok')
@app.post('/api/jobs/<int:i>/respond')
def respond(i):
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    c=db(); j=c.execute('SELECT * FROM jobs WHERE id=?',(i,)).fetchone()
    if not j:c.close();return jsonify(error='Задание не найдено'),404
    if j['user_id']==u['id']:c.close();return jsonify(error='Нельзя откликнуться на своё задание'),400
    try:c.execute('INSERT INTO responses(job_id,user_id,message) VALUES(?,?,?)',(i,u['id'],str(body().get('message','')).strip()));c.commit()
    except sqlite3.IntegrityError:c.close();return jsonify(error='Вы уже откликались'),409
    c.close();return jsonify(status='ok'),201
@app.put('/api/responses/<int:i>')
def response_status(i):
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    st=body().get('status')
    if st not in ('pending','accepted','rejected'):return jsonify(error='Некорректный статус'),400
    c=db();r=c.execute('SELECT r.*,j.user_id owner FROM responses r JOIN jobs j ON j.id=r.job_id WHERE r.id=?',(i,)).fetchone()
    if not r:c.close();return jsonify(error='Отклик не найден'),404
    if r['owner']!=u['id']:c.close();return jsonify(error='Нет доступа'),403
    c.execute('UPDATE responses SET status=? WHERE id=?',(st,i))
    if st=='accepted':
        c.execute("UPDATE jobs SET status='completed' WHERE id=?",(r['job_id'],)); c.execute("UPDATE responses SET status='rejected' WHERE job_id=? AND id<>? AND status='pending'",(r['job_id'],i)); c.execute('UPDATE users SET completed_jobs=completed_jobs+1 WHERE id=?',(r['user_id'],))
    c.commit();c.close();return jsonify(status='ok')
@app.get('/api/favorites')
def favorites():
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    c=db();rs=c.execute('SELECT j.*,u.name author_name,u.rating author_rating,u.avatar_url author_avatar,u.id author_id FROM favorites f JOIN jobs j ON j.id=f.job_id JOIN users u ON u.id=j.user_id WHERE f.user_id=? ORDER BY f.created_at DESC',(u['id'],)).fetchall();c.close();return jsonify([jobrow(r) for r in rs])
@app.post('/api/favorites/<int:i>')
def favorite(i):
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    c=db();r=c.execute('SELECT id FROM favorites WHERE user_id=? AND job_id=?',(u['id'],i)).fetchone()
    if r:c.execute('DELETE FROM favorites WHERE id=?',(r['id'],));a='removed'
    else:c.execute('INSERT INTO favorites(user_id,job_id) VALUES(?,?)',(u['id'],i));a='added'
    c.commit();c.close();return jsonify(action=a)
@app.post('/api/reviews')
def review():
    u=user()
    if not u:return jsonify(error='Не авторизован'),401
    d=body()
    try:rating=int(d.get('rating',0));to=int(d.get('to_user_id',0))
    except:return jsonify(error='Некорректная оценка'),400
    if rating<1 or rating>5 or to==u['id']:return jsonify(error='Некорректная оценка'),400
    c=db();c.execute('INSERT INTO reviews(from_user_id,to_user_id,job_id,rating,comment) VALUES(?,?,?,?,?)',(u['id'],to,d.get('job_id'),rating,str(d.get('comment','')).strip()));s=c.execute('SELECT AVG(rating) a,COUNT(*) n FROM reviews WHERE to_user_id=?',(to,)).fetchone();c.execute('UPDATE users SET rating=?,reviews_count=? WHERE id=?',(s['a'] or 0,s['n'],to));c.commit();c.close();return jsonify(status='ok'),201
@app.get('/manifest.json')
def manifest():
    return jsonify(name='Near Gig',short_name='Near Gig',start_url='/',scope='/',display='standalone',orientation='portrait-primary',theme_color='#5B67B7',background_color='#F5F7FB',icons=[{'src':'https://cdn-icons-png.flaticon.com/512/1041/1041916.png','sizes':'512x512','type':'image/png','purpose':'any maskable'}])
@app.get('/sw.js')
def sw():
    return Response("const CACHE='near-gig-v4';self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/','/static/css/style.css','/static/js/app.js'])))});self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))})",mimetype='application/javascript')
@app.get('/')
def index(): return render_template('index.html')
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
