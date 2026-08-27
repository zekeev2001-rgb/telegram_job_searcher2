let map=null;
let pickerMap=null;
let jobsCache=[];
let selectedCoords=null;
let selectedAddress='';
let currentUser=null;
let authMode='login';
let token=localStorage.getItem('near_token')||'';
let dark=localStorage.getItem('near_dark')==='1';

const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const money=v=>new Intl.NumberFormat('ru-RU').format(Number(v||0))+' ₽';

document.body.classList.toggle('dark',dark);

async function api(url,options={}){
  const headers=Object.assign({'Content-Type':'application/json'},options.headers||{});
  if(token)headers.Authorization='Bearer '+token;
  const response=await fetch(url,{...options,headers});
  let data={};
  try{data=await response.json()}catch{}
  if(!response.ok)throw new Error(data.error||'Не удалось выполнить запрос');
  return data;
}

function toast(text){
  const t=$('toast');t.textContent=text;t.classList.add('show');
  clearTimeout(window.__toastTimer);
  window.__toastTimer=setTimeout(()=>t.classList.remove('show'),2800);
}
function closeModal(id){$(id).classList.add('hidden')}
function setNav(id){
  document.querySelectorAll('.bottom-nav button').forEach(x=>x.classList.remove('active'));
  $(id)?.classList.add('active');
}
function normalizeJobs(data){
  if(Array.isArray(data))return data;
  if(Array.isArray(data.jobs))return data.jobs;
  return [];
}
function getAuthor(j){
  return j.author||{};
}
function addressOf(j){
  return j.address||j.location||'Точка на карте';
}

function init(){
  if(typeof ymaps==='undefined'){
    toast('Карта не загрузилась. Обновите страницу.');
    return;
  }
  ymaps.ready(()=>{
    map=new ymaps.Map('map',{
      center:[55.7558,37.6173],
      zoom:12,
      controls:['zoomControl','typeSelector'],
      suppressMapOpenBlock:true
    });
    map.events.add('click',e=>{
      if(window.mapPickMode){
        const coords=e.get('coords');
        setMainMapPoint(coords);
      }
    });
    loadJobs();
  });
  restoreUser();
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
}

async function loadJobs(){
  if(!map)return;
  try{
    const data=await api('/api/jobs?status=active');
    jobsCache=normalizeJobs(data);
    drawJobs();
  }catch(e){
    toast(e.message);
  }
}
function drawJobs(){
  if(!map)return;
  map.geoObjects.removeAll();
  jobsCache.forEach(j=>{
    if(j.lat==null||j.lng==null)return;
    const marker=new ymaps.Placemark([Number(j.lat),Number(j.lng)],{
      balloonContent:`<div style="padding:5px"><b>${esc(j.title)}</b><br>${esc(addressOf(j))}<br><b>${money(j.price)}</b></div>`
    },{
      preset:'islands#circleDotIcon',
      iconColor:'#5062B8'
    });
    marker.events.add('click',()=>openJob(j.id));
    map.geoObjects.add(marker);
  });
}
function setMainMapPoint(coords){
  selectedCoords=[Number(coords[0]),Number(coords[1])];
  if(window.mainSelectedMarker)map.geoObjects.remove(window.mainSelectedMarker);
  window.mainSelectedMarker=new ymaps.Placemark(selectedCoords,{},{preset:'islands#circleDotIcon',iconColor:'#5062B8'});
  map.geoObjects.add(window.mainSelectedMarker);
  resolveAddress(selectedCoords).then(address=>{
    selectedAddress=address;
    toast('Точка выбрана: '+address);
  });
}

function locateMe(){
  if(!navigator.geolocation)return toast('Геолокация недоступна');
  navigator.geolocation.getCurrentPosition(
    p=>{
      map?.setCenter([p.coords.latitude,p.coords.longitude],15,{duration:400});
      toast('Местоположение найдено');
    },
    ()=>toast('Разрешите доступ к геолокации'),
    {enableHighAccuracy:true,timeout:10000}
  );
}
function showAllOnMap(){
  if(!map||!map.geoObjects.getLength())return toast('На карте пока нет заданий');
  try{map.setBounds(map.geoObjects.getBounds(),{checkZoomRange:true,zoomMargin:60,duration:450})}catch{}
}
function goMap(){
  setNav('navMap');
  $('bottomSheet').classList.add('hidden');
  window.mapPickMode=false;
  loadJobs();
}
async function openJobs(){
  setNav('navJobs');
  const sheet=$('bottomSheet');sheet.classList.remove('hidden');
  sheet.innerHTML='<h2>Задания рядом</h2><div class="sheet-note">Свежие предложения пользователей Near Gig</div><div id="jobList">Загрузка…</div>';
  await loadCacheIfNeeded();
  renderList(jobsCache);
}
async function loadCacheIfNeeded(){
  if(jobsCache.length)return;
  try{jobsCache=normalizeJobs(await api('/api/jobs?status=active'));drawJobs()}catch(e){toast(e.message)}
}
function renderList(list){
  $('jobList').innerHTML=list.length?list.map(jobCard).join(''):'<div class="muted">Подходящих заданий пока нет.</div>';
}
function jobCard(j){
  return `<article class="job-card" onclick="openJob(${Number(j.id)})">
    <div class="job-line"><div class="job-title">${esc(j.title)}</div><div class="price">${money(j.price)}</div></div>
    <div class="muted" style="margin-top:7px">${esc(j.description||'Без описания')}</div>
    <div class="chips">
      <span class="chip">${esc(j.category||'Другое')}</span>
      <span class="chip">⌖ ${esc(addressOf(j))}</span>
      ${j.distance!=null?`<span class="chip">${Number(j.distance).toFixed(1)} км</span>`:''}
    </div>
  </article>`;
}
async function searchJobs(){
  const q=$('searchInput').value.trim().toLowerCase();
  await loadCacheIfNeeded();
  setNav('navJobs');
  $('bottomSheet').classList.remove('hidden');
  $('bottomSheet').innerHTML='<h2>Поиск</h2><div class="sheet-note">Результаты по названию, описанию и категории</div><div id="jobList"></div>';
  if(!q)return renderList(jobsCache);
  const result=jobsCache.filter(j=>
    [j.title,j.description,j.category,j.address].join(' ').toLowerCase().includes(q)
  );
  renderList(result);
}

function openCreate(){
  setNav('navCreate');
  if(!currentUser)return openAuth();
  selectedCoords=null;selectedAddress='';
  $('selectedAddress').textContent='Точка не выбрана';
  $('createModal').classList.remove('hidden');
}
function openPicker(){
  closeModal('createModal');
  $('picker').classList.remove('hidden');
  $('pickerAddress').textContent='Определяем адрес…';
  const center=map?map.getCenter():[55.7558,37.6173];
  setTimeout(()=>{
    if(!pickerMap){
      pickerMap=new ymaps.Map('pickerMap',{center,zoom:15,controls:['zoomControl']});
      pickerMap.events.add('actionend',updatePicker);
    }else{
      pickerMap.container.fitToViewport();
      pickerMap.setCenter(center,15);
    }
    updatePicker();
  },100);
}
function updatePicker(){
  if(!pickerMap)return;
  selectedCoords=pickerMap.getCenter().map(Number);
  $('pickerAddress').textContent='Определяем адрес…';
  resolveAddress(selectedCoords).then(a=>{
    selectedAddress=a;
    $('pickerAddress').textContent=a;
  });
}
async function resolveAddress(coords){
  try{
    const r=await ymaps.geocode(coords);
    const obj=r.geoObjects.get(0);
    return obj?obj.getAddressLine():`Точка ${coords[0].toFixed(5)}, ${coords[1].toFixed(5)}`;
  }catch{
    return `Точка ${coords[0].toFixed(5)}, ${coords[1].toFixed(5)}`;
  }
}
function confirmPicker(){
  if(!selectedCoords)return toast('Выберите место на карте');
  $('selectedAddress').textContent=selectedAddress||`Точка ${selectedCoords[0].toFixed(5)}, ${selectedCoords[1].toFixed(5)}`;
  closePicker();
  $('createModal').classList.remove('hidden');
  toast('Место выбрано');
}
function closePicker(){
  $('picker').classList.add('hidden');
  window.mapPickMode=false;
}
async function publishJob(){
  if(!selectedCoords)return toast('Сначала выберите точку на карте');
  const title=$('jobTitle').value.trim();
  const price=Number($('jobPrice').value);
  if(!title)return toast('Введите название задания');
  if(!price||price<1)return toast('Введите корректную оплату');
  try{
    await api('/api/jobs',{method:'POST',body:JSON.stringify({
      title,
      description:$('jobDescription').value.trim(),
      price,
      category:$('jobCategory').value,
      lat:selectedCoords[0],
      lng:selectedCoords[1],
      address:selectedAddress
    })});
    closeModal('createModal');
    $('jobTitle').value='';$('jobDescription').value='';$('jobPrice').value='';
    selectedCoords=null;selectedAddress='';
    await loadJobs();
    goMap();
    toast('Задание опубликовано');
  }catch(e){toast(e.message)}
}

async function openJob(id){
  try{
    const j=await api('/api/jobs/'+id);
    $('detailTitle').textContent=j.title||'Задание';
    const a=getAuthor(j);
    let html=`<div class="profile-hero">
      ${a.avatar_url?`<img class="avatar" src="${esc(a.avatar_url)}" onerror="this.style.display='none'">`:''}
      <div><b>${esc(a.name||j.author_name||'Пользователь')}</b><div class="muted">★ ${Number(a.rating??j.author_rating??0).toFixed(1)}</div></div>
      <div style="margin-left:auto" class="price">${money(j.price)}</div>
    </div>
    <div class="job-card" style="cursor:default">
      <div>${esc(j.description||'Без описания')}</div>
      <div class="chips"><span class="chip">${esc(j.category||'Другое')}</span><span class="chip">⌖ ${esc(addressOf(j))}</span></div>
    </div>`;
    if(j.lat!=null&&j.lng!=null)html+=`<button class="secondary" onclick="focusJob(${Number(j.lat)},${Number(j.lng)})">Показать на карте</button>`;
    if(currentUser&&Number(currentUser.id)!==Number(j.user_id)&&j.status==='active'){
      html+=`<div style="height:9px"></div><button class="primary" onclick="respondTo(${Number(j.id)})">Откликнуться</button><button class="ghost" onclick="toggleFavorite(${Number(j.id)})">♡ Добавить в избранное</button>`;
    }
    if(currentUser&&Number(currentUser.id)===Number(j.user_id)){
      html+=`<div style="height:9px"></div><button class="ghost" onclick="deleteJob(${Number(j.id)})">Удалить задание</button>`;
    }
    $('detailContent').innerHTML=html;
    $('detailModal').classList.remove('hidden');
  }catch(e){toast(e.message)}
}
function focusJob(lat,lng){
  closeModal('detailModal');goMap();map?.setCenter([lat,lng],16,{duration:450});
}
async function respondTo(id){
  const message=prompt('Сообщение заказчику (необязательно):')||'';
  try{await api('/api/jobs/'+id+'/respond',{method:'POST',body:JSON.stringify({message})});toast('Отклик отправлен')}catch(e){toast(e.message)}
}
async function toggleFavorite(id){
  try{
    const x=await api('/api/favorites/'+id,{method:'POST'});
    toast(x.action==='added'?'Добавлено в избранное':'Удалено из избранного');
  }catch(e){toast(e.message)}
}
async function deleteJob(id){
  if(!confirm('Удалить это задание?'))return;
  try{
    await api('/api/jobs/'+id,{method:'DELETE'});
    closeModal('detailModal');await loadJobs();toast('Задание удалено');
  }catch(e){toast(e.message)}
}

async function openFavorites(){
  if(!currentUser)return openAuth();
  setNav('navFav');
  const s=$('bottomSheet');s.classList.remove('hidden');
  s.innerHTML='<h2>Избранное</h2><div class="sheet-note">Сохранённые задания</div><div id="jobList">Загрузка…</div>';
  try{const a=normalizeJobs(await api('/api/favorites'));renderList(a)}catch(e){$('jobList').textContent=e.message}
}

function openAuth(){
  authMode='login';
  $('authModal').classList.remove('hidden');
  $('loginForm').classList.remove('hidden');
  $('registerForm').classList.add('hidden');
  $('authTitle').textContent='Вход';
  $('authSwitch').textContent='Нет аккаунта? Зарегистрироваться';
}
function switchAuth(){
  authMode=authMode==='login'?'register':'login';
  $('loginForm').classList.toggle('hidden',authMode!=='login');
  $('registerForm').classList.toggle('hidden',authMode!=='register');
  $('authTitle').textContent=authMode==='login'?'Вход':'Регистрация';
  $('authSwitch').textContent=authMode==='login'?'Нет аккаунта? Зарегистрироваться':'Уже есть аккаунт? Войти';
  if(authMode==='register'&&!$('registerFields').innerHTML){
    $('registerFields').innerHTML=`
      <label>Имя и фамилия<input id="regName" class="field" placeholder="Иван Иванов"></label>
      <label>Телефон<input id="regPhone" class="field" type="tel" placeholder="+49 ..."></label>
      <label>Дата рождения<input id="regBirth" class="field" type="date"></label>
      <label>Род деятельности<input id="regOccupation" class="field" placeholder="Например: студент, водитель"></label>
      <label>Роль<select id="regRole" class="field"><option value="executor">Исполнитель</option><option value="customer">Заказчик</option></select></label>
      <label>Email<input id="regEmail" class="field" type="email" placeholder="you@example.com"></label>
      <label>Пароль<input id="regPassword" class="field" type="password" placeholder="Минимум 6 символов"></label>
      <div class="location-box">
        <b>Данные паспорта</b>
        <div class="muted" style="font-size:12px;margin:4px 0 10px">Эти поля передаются серверу для защищённого хранения.</div>
        <label>Серия<input id="regPassportSeries" class="field" placeholder="0000"></label>
        <label>Номер<input id="regPassportNumber" class="field" placeholder="000000"></label>
        <label>Кем выдан<input id="regPassportIssuedBy" class="field" placeholder="Орган выдачи"></label>
        <label>Дата выдачи<input id="regPassportIssueDate" class="field" type="date"></label>
      </div>`;
  }
}
async function login(){
  try{
    const x=await api('/api/login',{method:'POST',body:JSON.stringify({
      email:$('loginEmail').value.trim(),password:$('loginPassword').value
    })});
    token=x.token;currentUser=x.user||x;
    localStorage.setItem('near_token',token);
    closeModal('authModal');
    toast('С возвращением, '+(currentUser.name||'пользователь'));
  }catch(e){toast(e.message)}
}
async function register(){
  const data={
    name:$('regName').value.trim(),
    phone:$('regPhone').value.trim(),
    birth_date:$('regBirth').value,
    occupation:$('regOccupation').value.trim(),
    role:$('regRole').value,
    email:$('regEmail').value.trim(),
    password:$('regPassword').value,
    passport_series:$('regPassportSeries').value.trim(),
    passport_number:$('regPassportNumber').value.trim(),
    passport_issued_by:$('regPassportIssuedBy').value.trim(),
    passport_issue_date:$('regPassportIssueDate').value
  };
  try{
    const x=await api('/api/register',{method:'POST',body:JSON.stringify(data)});
    token=x.token;currentUser=x.user||x;
    localStorage.setItem('near_token',token);
    closeModal('authModal');toast('Аккаунт создан');
  }catch(e){toast(e.message)}
}
async function restoreUser(){
  if(!token)return;
  try{currentUser=await api('/api/me')}catch{token='';localStorage.removeItem('near_token')}
}
async function openProfile(){
  if(!currentUser)return openAuth();
  setNav('navProfile');
  $('profileContent').innerHTML=`
    <div class="profile-hero">
      ${currentUser.avatar_url?`<img class="avatar" src="${esc(currentUser.avatar_url)}" onerror="this.style.display='none'">`:''}
      <div><b>${esc(currentUser.name||'Пользователь')}</b><div class="muted">${esc(currentUser.email||'')}</div></div>
    </div>
    <div class="stats">
      <div class="stat"><b>${Number(currentUser.rating||0).toFixed(1)}</b><span>рейтинг</span></div>
      <div class="stat"><b>${currentUser.reviews_count||0}</b><span>отзывов</span></div>
      <div class="stat"><b>${currentUser.completed_jobs||0}</b><span>выполнено</span></div>
    </div>
    <div class="profile-info">
      <p>📱 ${esc(currentUser.phone||'Телефон не указан')}</p>
      <p>🎂 ${esc(currentUser.birth_date||'Дата рождения не указана')}</p>
      <p>💼 ${esc(currentUser.occupation||'Род деятельности не указан')}</p>
      <p>🪪 Паспорт: защищённые данные</p>
    </div>
    <div class="setting">
      <div><b>Тёмная тема</b><div class="muted">Спокойная схема для вечера</div></div>
      <button class="switch ${dark?'on':''}" onclick="toggleTheme(this)"></button>
    </div>
    <button class="secondary" style="margin-top:12px" onclick="myJobs()">Мои задания</button>
    <button class="ghost" onclick="logout()">Выйти из аккаунта</button>`;
  $('profileModal').classList.remove('hidden');
}
async function myJobs(){
  closeModal('profileModal');
  const s=$('bottomSheet');s.classList.remove('hidden');
  s.innerHTML='<h2>Мои задания</h2><div class="sheet-note">Опубликованные тобой задания</div><div id="jobList">Загрузка…</div>';
  try{
    const a=normalizeJobs(await api('/api/jobs?user_id='+encodeURIComponent(currentUser.id)));
    renderList(a);
  }catch(e){$('jobList').textContent=e.message}
}
function toggleTheme(button){
  dark=!dark;localStorage.setItem('near_dark',dark?'1':'0');
  document.body.classList.toggle('dark',dark);
  button.classList.toggle('on',dark);
}
async function logout(){
  try{await api('/api/logout',{method:'POST'})}catch{}
  token='';currentUser=null;localStorage.removeItem('near_token');
  closeModal('profileModal');setNav('navMap');toast('Вы вышли из аккаунта');
}

document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    ['authModal','createModal','detailModal','profileModal'].forEach(closeModal);
    closePicker();
  }
});
$('searchInput').addEventListener('keydown',e=>{if(e.key==='Enter')searchJobs()});
init();
