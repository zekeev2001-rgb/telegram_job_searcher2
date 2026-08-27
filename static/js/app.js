let map, pickerMap, pickerMarker, pickerCoords=null, chosen=null, userNow=null;
let tokenValue=localStorage.getItem('near_token')||'';
let dark=localStorage.getItem('near_dark')==='1';
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));

document.body.classList.toggle('dark',dark);

async function api(url,opts={}){opts.headers=Object.assign({'Content-Type':'application/json'},opts.headers||{});if(tokenValue)opts.headers.Authorization='Bearer '+tokenValue;const r=await fetch(url,opts);let d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.error||'Ошибка запроса');return d}
function toast(text){const e=$('toast');e.textContent=text;e.classList.add('show');clearTimeout(window.__toast);window.__toast=setTimeout(()=>e.classList.remove('show'),2600)}
function closeM(id){$(id).classList.add('hidden')}
function setActive(id){document.querySelectorAll('.bottom-nav button').forEach(b=>b.classList.remove('active'));$(id)?.classList.add('active')}
function formatPrice(v){return new Intl.NumberFormat('ru-RU').format(Number(v||0))+' ₽'}

function init(){
  ymaps.ready(()=>{
    map=new ymaps.Map('map',{center:[55.7558,37.6173],zoom:12,controls:['zoomControl','typeSelector'],suppressMapOpenBlock:true});
    loadJobsOnMap();
  });
  restoreSession();
  if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
}

async function loadJobsOnMap(){
  if(!map)return;
  map.geoObjects.removeAll();
  try{
    const jobs=await api('/api/jobs?status=active');
    jobs.forEach(j=>{
      if(j.lat==null||j.lng==null)return;
      const p=new ymaps.Placemark([j.lat,j.lng],{balloonContent:`<b>${esc(j.title)}</b><br>${esc(j.address||'Место на карте')}<br><b>${formatPrice(j.price)}</b>`},{preset:'islands#blueCircleDotIcon'});
      p.events.add('click',()=>show(j.id));map.geoObjects.add(p);
    });
  }catch(e){toast(e.message)}
}
function locate(){
  if(!navigator.geolocation)return toast('Геолокация недоступна');
  navigator.geolocation.getCurrentPosition(p=>{map?.setCenter([p.coords.latitude,p.coords.longitude],15,{duration:350});toast('Местоположение найдено')},()=>toast('Разрешите доступ к геолокации'),{enableHighAccuracy:true,timeout:10000});
}
function fitJobs(){
  if(!map)return;
  const objects=map.geoObjects.toArray();if(!objects.length)return toast('Пока нет заданий на карте');
  try{map.setBounds(map.geoObjects.getBounds(),{checkZoomRange:true,zoomMargin:45,duration:350})}catch{}
}
function goMap(){setActive('nmap');$('sheet').classList.add('hidden');map?.container.fitToViewport();loadJobsOnMap()}

async function jobs(){
  setActive('njobs');const s=$('sheet');s.classList.remove('hidden');s.innerHTML='<h2>Задания рядом</h2><div class="sheet-sub">Свежие предложения от пользователей Near Gig</div><div id="jl">Загрузка...</div>';
  try{const a=await api('/api/jobs?status=active');$('jl').innerHTML=a.map(card).join('')||'<div class="muted">Пока нет активных заданий.</div>'}catch(e){$('jl').textContent=e.message}
}
function card(j){return `<article class="job-card" onclick="show(${j.id})"><div class="job-top"><div class="job-title">${esc(j.title)}</div><div class="price">${formatPrice(j.price)}</div></div><div class="muted" style="margin-top:7px">${esc(j.description||'Без описания')}</div><div class="chips"><span class="chip">${esc(j.category)}</span><span class="chip">⌖ ${esc(j.address||'Точка на карте')}</span>${j.distance!=null?`<span class="chip">${j.distance.toFixed(1)} км</span>`:''}</div></article>`}
async function search(){const q=$('q').value.trim();if(!q)return jobs();const s=$('sheet');s.classList.remove('hidden');s.innerHTML='<h2>Поиск</h2><div class="sheet-sub">Ищем подходящие задания</div><div id="jl">Загрузка...</div>';try{const a=await api('/api/jobs?status=active&search='+encodeURIComponent(q));$('jl').innerHTML=a.map(card).join('')||'<div class="muted">Ничего не найдено.</div>'}catch(e){$('jl').textContent=e.message}}

function create(){setActive('ncreate');if(!userNow)return openAuth();chosen=null;$('addr').textContent='Точка не выбрана';$('createM').classList.remove('hidden')}
function pick(){
  if(!map)return;
  pickerCoords=null;$('pa').textContent='Нажмите на карту в нужном месте';$('map-hint').classList.add('hidden');$('picker').classList.remove('hidden');
  setTimeout(()=>{
    const center=map.getCenter();
    if(!pickerMap){pickerMap=new ymaps.Map('pm',{center,zoom:15,controls:['zoomControl']});pickerMap.events.add('click',e=>selectPoint(e.get('coords')))}else{pickerMap.container.fitToViewport();pickerMap.setCenter(center,15)}
  },100);
}
function selectPoint(coords){
  pickerCoords=coords;
  if(pickerMarker)pickerMap.geoObjects.remove(pickerMarker);
  pickerMarker=new ymaps.Placemark(coords,{balloonContent:'Выбранная точка'},{preset:'islands#redDotIcon'});pickerMap.geoObjects.add(pickerMarker);
  $('pa').textContent='Определяем адрес...';
  ymaps.geocode(coords).then(r=>{const x=r.geoObjects.get(0);$('pa').textContent=x?x.getAddressLine():`Точка: ${coords[0].toFixed(5)}, ${coords[1].toFixed(5)}`}).catch(()=>{$('pa').textContent=`Точка: ${coords[0].toFixed(5)}, ${coords[1].toFixed(5)}`});
}
function confirmPick(){if(!pickerCoords)return toast('Сначала нажмите на карту');chosen=[...pickerCoords];$('addr').textContent=$('pa').textContent;closePick();toast('Точка выбрана')}
function closePick(){$('picker').classList.add('hidden');$('map-hint').classList.add('hidden')}
async function saveJob(){
  if(!chosen)return toast('Выберите точку на карте');
  const title=$('jt').value.trim(),price=Number($('jp').value);if(!title||!price)return toast('Заполните название и цену');
  try{await api('/api/jobs',{method:'POST',body:JSON.stringify({title,description:$('jd').value.trim(),price,category:$('jc').value,lat:chosen[0],lng:chosen[1],address:$('addr').textContent})});closeM('createM');$('jt').value='';$('jd').value='';$('jp').value='';chosen=null;$('addr').textContent='Точка не выбрана';await loadJobsOnMap();goMap();toast('Задание опубликовано')}catch(e){toast(e.message)}
}

async function show(id){
  try{
    const j=await api('/api/jobs/'+id);$('dt').textContent=j.title;
    let html=`<div class="profile-hero"><img class="avatar" src="${esc(j.author.avatar)}"><div><b>${esc(j.author.name)}</b><div class="muted">★ ${Number(j.author.rating||0).toFixed(1)} · ${j.views||0} просмотров</div></div><div style="margin-left:auto" class="price">${formatPrice(j.price)}</div></div><div class="job-card"><div>${esc(j.description||'Без описания')}</div><div class="chips"><span class="chip">${esc(j.category)}</span><span class="chip">⌖ ${esc(j.address||'Место на карте')}</span></div></div><button class="secondary" onclick="showOnMap(${j.lat},${j.lng})">Показать на карте</button>`;
    if(userNow&&userNow.id!==j.user_id&&j.status==='active')html+=`<div style="height:9px"></div><button class="primary" onclick="respond(${j.id})">Откликнуться</button><button class="ghost" onclick="fav(${j.id})">♡ Добавить в избранное</button>`;
    if(userNow&&userNow.id===j.user_id)html+=`<div style="height:9px"></div><button class="ghost" onclick="deleteMyJob(${j.id})">Удалить задание</button>`;
    $('dc').innerHTML=html;$('detail').classList.remove('hidden');
  }catch(e){toast(e.message)}
}
function showOnMap(lat,lng){closeM('detail');goMap();if(lat!=null&&lng!=null)map.setCenter([lat,lng],16,{duration:400})}
async function respond(id){const message=prompt('Сообщение заказчику (необязательно):')||'';try{await api('/api/jobs/'+id+'/respond',{method:'POST',body:JSON.stringify({message})});toast('Отклик отправлен')}catch(e){toast(e.message)}}
async function fav(id){try{const x=await api('/api/favorites/'+id,{method:'POST'});toast(x.action==='added'?'Добавлено в избранное':'Удалено из избранного')}catch(e){toast(e.message)}}
async function deleteMyJob(id){if(!confirm('Удалить это задание?'))return;try{await api('/api/jobs/'+id,{method:'DELETE'});closeM('detail');await loadJobsOnMap();toast('Задание удалено')}catch(e){toast(e.message)}}

async function favoritesView(){
  if(!userNow)return openAuth();setActive('nfav');const s=$('sheet');s.classList.remove('hidden');s.innerHTML='<h2>Избранное</h2><div id="jl">Загрузка...</div>';try{const a=await api('/api/favorites');$('jl').innerHTML=a.map(card).join('')||'<div class="muted">В избранном пока пусто.</div>'}catch(e){$('jl').textContent=e.message}
}

function openAuth(){auth='login';$('auth').classList.remove('hidden');$('login').classList.remove('hidden');$('reg').classList.add('hidden');$('at').textContent='Вход';$('authSwitch').textContent='Нет аккаунта? Зарегистрироваться'}
let auth='login';
function toggleAuth(){auth=auth==='login'?'reg':'login';$('login').classList.toggle('hidden',auth!=='login');$('reg').classList.toggle('hidden',auth!=='reg');$('at').textContent=auth==='login'?'Вход':'Регистрация';$('authSwitch').textContent=auth==='login'?'Нет аккаунта? Зарегистрироваться':'Уже есть аккаунт? Войти';if(auth==='reg'&&!$('rf').innerHTML)$('rf').innerHTML=`<label>Имя и фамилия<input id="rn" class="field" placeholder="Иван Иванов"></label><label>Телефон<input id="rph" class="field" type="tel" placeholder="+49 ..."></label><label>Дата рождения<input id="rb" type="date" class="field"></label><label>Род деятельности<input id="ro" class="field" placeholder="Например: студент, мастер, водитель"></label><label>Роль<select id="rr" class="field"><option value="executor">Исполнитель</option><option value="customer">Заказчик</option></select></label><label>Email<input id="re" class="field" type="email" placeholder="you@example.com"></label><label>Пароль<input id="rp" class="field" type="password" placeholder="Минимум 6 символов"></label><div class="location-card"><b>Данные паспорта</b><div class="muted" style="margin:4px 0 10px;font-size:12px">Данные хранятся в зашифрованном виде.</div><label>Серия<input id="rs" class="field" placeholder="0000"></label><label>Номер<input id="rnumb" class="field" placeholder="000000"></label><label>Кем выдан<input id="ri" class="field" placeholder="Орган выдачи"></label><label>Дата выдачи<input id="rid" type="date" class="field"></label></div>`}
async function doLogin(){try{const x=await api('/api/login',{method:'POST',body:JSON.stringify({email:$('le').value.trim(),password:$('lp').value})});tokenValue=x.token;userNow=x.user;localStorage.setItem('near_token',tokenValue);closeM('auth');toast('С возвращением, '+userNow.name.split(' ')[0])}catch(e){toast(e.message)}}
async function doReg(){const d={name:$('rn').value,phone:$('rph').value,birth_date:$('rb').value,occupation:$('ro').value,role:$('rr').value,email:$('re').value,password:$('rp').value,passport_series:$('rs').value,passport_number:$('rnumb').value,passport_issued_by:$('ri').value,passport_issue_date:$('rid').value};try{const x=await api('/api/register',{method:'POST',body:JSON.stringify(d)});tokenValue=x.token;userNow=x.user;localStorage.setItem('near_token',tokenValue);closeM('auth');toast('Аккаунт создан')}catch(e){toast(e.message)}}

async function profile(){
  if(!userNow)return openAuth();setActive('nprof');
  $('pc').innerHTML=`<div class="profile-hero"><img class="avatar" src="${esc(userNow.avatar_url)}"><div><b>${esc(userNow.name)}</b><div class="muted">${esc(userNow.email)}</div></div></div><div class="stat-row"><div class="stat"><b>${Number(userNow.rating||0).toFixed(1)}</b><span class="muted">рейтинг</span></div><div class="stat"><b>${userNow.reviews_count||0}</b><span class="muted">отзывов</span></div><div class="stat"><b>${userNow.completed_jobs||0}</b><span class="muted">выполнено</span></div></div><div class="job-card"><p>📱 ${esc(userNow.phone||'Не указан')}</p><p>🎂 ${esc(userNow.birth_date||'Не указана')}</p><p>💼 ${esc(userNow.occupation||'Не указана')}</p><p>🪪 Паспорт: данные защищены</p></div><div class="toggle"><div><b>Тёмная тема</b><div class="muted">Спокойная схема для вечернего использования</div></div><button class="switch ${dark?'on':''}" onclick="toggleDark(this)"></button></div><button class="secondary" style="margin-top:12px" onclick="jobsMine()">Мои задания</button><button class="ghost" onclick="logout()">Выйти из аккаунта</button>`;
  $('prof').classList.remove('hidden');
}
async function jobsMine(){closeM('prof');setActive('nprof');const s=$('sheet');s.classList.remove('hidden');s.innerHTML='<h2>Мои задания</h2><div id="jl">Загрузка...</div>';try{const a=await api('/api/jobs?status=&user_id='+userNow.id);$('jl').innerHTML=a.map(card).join('')||'<div class="muted">Вы ещё не создавали задания.</div>'}catch(e){$('jl').textContent=e.message}
}
function toggleDark(btn){dark=!dark;localStorage.setItem('near_dark',dark?'1':'0');document.body.classList.toggle('dark',dark);btn.classList.toggle('on',dark)}
async function logout(){try{await api('/api/logout',{method:'POST'})}catch{}tokenValue='';userNow=null;localStorage.removeItem('near_token');closeM('prof');setActive('nmap');toast('Вы вышли из аккаунта')}
async function restoreSession(){if(!tokenValue)return;try{userNow=await api('/api/me')}catch{tokenValue='';localStorage.removeItem('near_token')}}

document.addEventListener('keydown',e=>{if(e.key==='Escape'){['auth','createM','detail','prof'].forEach(id=>$(id).classList.add('hidden'));closePick()}});
init();
