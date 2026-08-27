/* =========================================================
   NEAR GIG — APP.JS
   Новая версия интерфейса
   Карта + задания + поиск + профиль + избранное
   ========================================================= */

let map = null;
let pickerMap = null;

let jobsCache = [];

let selectedCoords = null;
let selectedAddress = '';

let pickerCoords = null;
let pickerAddress = '';

let pickerMarker = null;
let mainSelectedMarker = null;

let currentUser = null;
let authMode = 'login';

let token = localStorage.getItem('near_token') || '';
let dark = localStorage.getItem('near_dark') === '1';

let currentJobFilter = 'all';
let currentSearchQuery = '';

const $ = id => document.getElementById(id);


/* =========================================================
   БЕЗОПАСНЫЙ HTML
   ========================================================= */

const esc = value =>
  String(value ?? '').replace(
    /[&<>"']/g,
    char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    }[char])
  );


const money = value =>
  new Intl.NumberFormat('ru-RU').format(
    Number(value || 0)
  ) + ' ₽';


/* =========================================================
   ДОПОЛНИТЕЛЬНЫЕ СТИЛИ ИНТЕРФЕЙСА
   Добавляем из JS, чтобы не ломать style.css
   ========================================================= */

function injectAppStyles() {

  if ($('near-gig-app-styles')) return;

  const style = document.createElement('style');

  style.id = 'near-gig-app-styles';

  style.textContent = `
    .jobs-modern {
      max-width: 760px;
      margin: 0 auto;
      padding: 4px 0 120px;
    }

    .jobs-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    .jobs-header h2 {
      margin: 0;
      font-size: 27px;
      line-height: 1.1;
      letter-spacing: -0.7px;
    }

    .jobs-header p {
      margin: 7px 0 0;
      opacity: .58;
      font-size: 14px;
    }

    .jobs-count {
      min-width: 42px;
      height: 42px;
      padding: 0 12px;
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(83,103,201,.10);
      color: #5367c9;
      font-weight: 800;
      font-size: 14px;
    }

    .jobs-search {
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--card-bg, #fff);
      border: 1px solid rgba(80,90,130,.10);
      border-radius: 16px;
      padding: 7px 8px 7px 14px;
      margin-bottom: 14px;
      box-shadow: 0 8px 30px rgba(30,40,80,.06);
    }

    .jobs-search span {
      opacity: .45;
      font-size: 19px;
    }

    .jobs-search input {
      flex: 1;
      min-width: 0;
      border: 0;
      outline: 0;
      background: transparent;
      font: inherit;
      color: inherit;
      padding: 9px 0;
    }

    .jobs-search button {
      border: 0;
      background: #5367c9;
      color: #fff;
      border-radius: 11px;
      padding: 10px 15px;
      font-weight: 700;
      cursor: pointer;
    }

    .job-filters {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding: 2px 0 12px;
      scrollbar-width: none;
    }

    .job-filters::-webkit-scrollbar {
      display: none;
    }

    .job-filter {
      flex: 0 0 auto;
      border: 1px solid rgba(80,90,130,.12);
      background: var(--card-bg, #fff);
      color: inherit;
      border-radius: 999px;
      padding: 9px 14px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }

    .job-filter.active {
      background: #5367c9;
      border-color: #5367c9;
      color: #fff;
    }

    .jobs-list {
      display: grid;
      gap: 12px;
    }

    .modern-job-card {
      position: relative;
      background: var(--card-bg, #fff);
      border: 1px solid rgba(80,90,130,.09);
      border-radius: 20px;
      padding: 17px;
      cursor: pointer;
      transition:
        transform .18s ease,
        box-shadow .18s ease,
        border-color .18s ease;
      box-shadow: 0 8px 28px rgba(30,40,80,.055);
    }

    .modern-job-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 13px 35px rgba(30,40,80,.10);
      border-color: rgba(83,103,201,.22);
    }

    .modern-job-card:active {
      transform: scale(.99);
    }

    .modern-job-top {
      display: flex;
      align-items: flex-start;
      gap: 12px;
    }

    .modern-job-icon {
      width: 44px;
      height: 44px;
      flex: 0 0 44px;
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(83,103,201,.10);
      color: #5367c9;
      font-size: 20px;
    }

    .modern-job-main {
      flex: 1;
      min-width: 0;
      padding-right: 38px;
    }

    .modern-job-title {
      font-weight: 800;
      font-size: 16px;
      line-height: 1.25;
      margin-bottom: 5px;
    }

    .modern-job-category {
      font-size: 12px;
      font-weight: 700;
      opacity: .55;
    }

    .modern-job-price {
      position: absolute;
      top: 17px;
      right: 17px;
      font-weight: 900;
      font-size: 16px;
      color: #5367c9;
      white-space: nowrap;
    }

    .modern-job-description {
      margin: 13px 0;
      font-size: 13px;
      line-height: 1.45;
      opacity: .68;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .modern-job-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
    }

    .modern-job-chip {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border-radius: 9px;
      padding: 6px 9px;
      background: rgba(80,90,130,.07);
      font-size: 11px;
      font-weight: 650;
      opacity: .82;
    }

    .modern-job-fav {
      position: absolute;
      right: 14px;
      bottom: 14px;
      width: 34px;
      height: 34px;
      border-radius: 50%;
      border: 0;
      background: rgba(80,90,130,.07);
      cursor: pointer;
      font-size: 17px;
      color: inherit;
    }

    .modern-job-fav.active {
      color: #5367c9;
      background: rgba(83,103,201,.12);
    }

    .jobs-empty {
      text-align: center;
      padding: 42px 20px;
      background: var(--card-bg, #fff);
      border-radius: 20px;
      border: 1px dashed rgba(80,90,130,.18);
    }

    .jobs-empty-icon {
      font-size: 38px;
      margin-bottom: 12px;
      opacity: .55;
    }

    .jobs-empty b {
      display: block;
      margin-bottom: 6px;
    }

    .jobs-empty span {
      font-size: 13px;
      opacity: .55;
    }

    .modern-detail {
      display: grid;
      gap: 15px;
    }

    .detail-price-box {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 15px;
      padding: 15px;
      border-radius: 17px;
      background: rgba(83,103,201,.08);
    }

    .detail-price-box span {
      font-size: 12px;
      opacity: .55;
    }

    .detail-price-box b {
      font-size: 22px;
      color: #5367c9;
    }

    .detail-section {
      padding: 14px;
      border-radius: 15px;
      background: rgba(80,90,130,.055);
    }

    .detail-section-title {
      font-size: 12px;
      font-weight: 800;
      opacity: .5;
      text-transform: uppercase;
      letter-spacing: .5px;
      margin-bottom: 7px;
    }

    .detail-description {
      font-size: 14px;
      line-height: 1.55;
      white-space: pre-wrap;
    }

    .detail-actions {
      display: grid;
      gap: 9px;
      margin-top: 3px;
    }

    @media (max-width: 700px) {

      .jobs-modern {
        padding-bottom: 105px;
      }

      .jobs-header h2 {
        font-size: 24px;
      }

      .modern-job-card {
        border-radius: 17px;
      }

    }
  `;

  document.head.appendChild(style);
}


/* =========================================================
   ТЕМА
   ========================================================= */

document.body.classList.toggle('dark', dark);


function toggleTheme(button) {

  dark = !dark;

  localStorage.setItem(
    'near_dark',
    dark ? '1' : '0'
  );

  document.body.classList.toggle(
    'dark',
    dark
  );

  if (button) {
    button.classList.toggle(
      'on',
      dark
    );
  }
}


/* =========================================================
   API
   ========================================================= */

async function api(url, options = {}) {

  const headers = Object.assign(
    {
      'Content-Type': 'application/json'
    },
    options.headers || {}
  );

  if (token) {
    headers.Authorization =
      'Bearer ' + token;
  }

  const response = await fetch(
    url,
    {
      ...options,
      headers
    }
  );

  let data = {};

  try {
    data = await response.json();
  } catch (_) {}

  if (!response.ok) {

    throw new Error(
      data.error ||
      'Не удалось выполнить запрос'
    );

  }

  return data;
}


/* =========================================================
   УВЕДОМЛЕНИЯ
   ========================================================= */

function toast(text) {

  const t = $('toast');

  if (!t) return;

  t.textContent = text;

  t.classList.add('show');

  clearTimeout(
    window.__toastTimer
  );

  window.__toastTimer =
    setTimeout(
      () => t.classList.remove('show'),
      2800
    );
}


/* =========================================================
   МОДАЛЬНЫЕ ОКНА
   ========================================================= */

function closeM(id) {

  const element = $(id);

  if (element) {
    element.classList.add('hidden');
  }
}


function setNav(id) {

  document
    .querySelectorAll('.bottom-nav button')
    .forEach(button => {
      button.classList.remove('active');
    });

  const button = $(id);

  if (button) {
    button.classList.add('active');
  }
}


/* =========================================================
   ДАННЫЕ
   ========================================================= */

function normalizeJobs(data) {

  if (Array.isArray(data)) {
    return data;
  }

  if (Array.isArray(data.jobs)) {
    return data.jobs;
  }

  return [];
}


function getAuthor(job) {
  return job.author || {};
}


function addressOf(job) {

  return (
    job.address ||
    job.location ||
    'Точка на карте'
  );
}


/* =========================================================
   ИНИЦИАЛИЗАЦИЯ
   ========================================================= */

function init() {

  injectAppStyles();

  if (typeof ymaps === 'undefined') {

    toast(
      'Карта не загрузилась. Проверьте ключ Яндекс.Карт.'
    );

    return;
  }

  ymaps.ready(() => {

    createMainMap();

    restoreUser();

    loadJobs();

  });


  if (
    'serviceWorker' in navigator
  ) {

    navigator.serviceWorker
      .register('/sw.js')
      .catch(() => {});

  }
}


/* =========================================================
   ОСНОВНАЯ КАРТА
   ========================================================= */

function createMainMap() {

  const mapElement = $('map');

  if (!mapElement) {

    console.error(
      'Near Gig: элемент #map отсутствует'
    );

    return;
  }


  map = new ymaps.Map(
    'map',
    {
      center: [
        55.7558,
        37.6173
      ],

      zoom: 12,

      controls: [
        'zoomControl',
        'typeSelector'
      ],

      suppressMapOpenBlock: true
    }
  );


  map.events.add(
    'click',
    event => {

      if (!window.mapPickMode) {
        return;
      }

      const coords =
        event.get('coords');

      setMainMapPoint(coords);

    }
  );


  setTimeout(
    () => {

      try {
        map.container.fitToViewport();
      } catch (_) {}

    },
    300
  );
}


/* =========================================================
   ЗАГРУЗКА ЗАДАНИЙ
   ========================================================= */

async function loadJobs() {

  if (!map) {
    return;
  }

  try {

    const data =
      await api(
        '/api/jobs?status=active'
      );

    jobsCache =
      normalizeJobs(data);

    drawJobs();

  } catch (error) {

    console.error(error);

    toast(error.message);

  }
}


/* =========================================================
   МАРКЕРЫ ЗАДАНИЙ
   ========================================================= */

function drawJobs() {

  if (!map) {
    return;
  }

  map.geoObjects.removeAll();

  jobsCache.forEach(job => {

    if (
      job.lat == null ||
      job.lng == null
    ) {
      return;
    }

    const marker =
      new ymaps.Placemark(
        [
          Number(job.lat),
          Number(job.lng)
        ],
        {
          balloonContent:
            `
              <div style="
                padding:8px;
                min-width:190px;
                font-family:Arial,sans-serif
              ">
                <b>${esc(job.title)}</b>
                <br><br>
                <span>${esc(addressOf(job))}</span>
                <br><br>
                <strong style="color:#5367c9">
                  ${money(job.price)}
                </strong>
              </div>
            `
        },
        {
          preset:
            'islands#circleDotIcon',

          iconColor:
            '#5367C9'
        }
      );

    marker.events.add(
      'click',
      () => openJob(job.id)
    );

    map.geoObjects.add(
      marker
    );

  });


  if (mainSelectedMarker) {

    map.geoObjects.add(
      mainSelectedMarker
    );

  }
}


/* =========================================================
   ТОЧКА НА ОСНОВНОЙ КАРТЕ
   ========================================================= */

function setMainMapPoint(coords) {

  if (!coords) {
    return;
  }

  selectedCoords = [
    Number(coords[0]),
    Number(coords[1])
  ];

  if (
    mainSelectedMarker &&
    map
  ) {

    try {

      map.geoObjects.remove(
        mainSelectedMarker
      );

    } catch (_) {}

  }


  mainSelectedMarker =
    new ymaps.Placemark(
      selectedCoords,
      {
        hintContent:
          'Выбранное место',

        balloonContent:
          'Выбранное место'
      },
      {
        preset:
          'islands#redDotIcon'
      }
    );


  map.geoObjects.add(
    mainSelectedMarker
  );


  map.setCenter(
    selectedCoords,
    Math.max(
      map.getZoom(),
      15
    ),
    {
      duration: 250
    }
  );


  resolveAddress(
    selectedCoords
  ).then(address => {

    selectedAddress =
      address;

    toast(
      'Точка выбрана: ' +
      address
    );

  });

}


/* =========================================================
   ГЕОЛОКАЦИЯ
   ========================================================= */

function locate() {

  if (!navigator.geolocation) {

    toast(
      'Геолокация недоступна'
    );

    return;
  }

  navigator.geolocation.getCurrentPosition(

    position => {

      const coords = [
        position.coords.latitude,
        position.coords.longitude
      ];

      if (map) {

        map.setCenter(
          coords,
          15,
          {
            duration: 500
          }
        );

      }

      toast(
        'Местоположение найдено'
      );

    },

    () => {

      toast(
        'Разрешите доступ к геолокации'
      );

    },

    {
      enableHighAccuracy: true,
      timeout: 10000
    }

  );
}


/* =========================================================
   ПОКАЗАТЬ ВСЕ ЗАДАНИЯ
   ========================================================= */

function fitJobs() {

  if (!map) {
    return;
  }

  if (
    !map.geoObjects.getLength()
  ) {

    toast(
      'На карте пока нет заданий'
    );

    return;
  }

  try {

    map.setBounds(
      map.geoObjects.getBounds(),
      {
        checkZoomRange: true,
        zoomMargin: 60,
        duration: 450
      }
    );

  } catch (_) {}

}


/* =========================================================
   КАРТА
   ========================================================= */

function goMap() {

  setNav('nmap');

  const sheet = $('sheet');

  if (sheet) {
    sheet.classList.add(
      'hidden'
    );
  }

  window.mapPickMode = false;

  if (map) {

    setTimeout(
      () => {

        try {
          map.container.fitToViewport();
        } catch (_) {}

      },
      100
    );

  }
}


/* =========================================================
   ЭКРАН ЗАДАНИЙ
   ========================================================= */

async function jobs() {

  setNav('njobs');

  const sheet = $('sheet');

  if (!sheet) {
    return;
  }

  sheet.classList.remove(
    'hidden'
  );

  currentSearchQuery = '';
  currentJobFilter = 'all';

  sheet.innerHTML =
    `
      <div class="jobs-modern">

        <div class="jobs-header">

          <div>
            <h2>Задания рядом</h2>
            <p>
              Найди подработку и заработай сегодня
            </p>
          </div>

          <div
            class="jobs-count"
            id="jobsCount"
          >
            0
          </div>

        </div>


        <div class="jobs-search">

          <span>⌕</span>

          <input
            id="jobsSearch"
            type="search"
            placeholder="Поиск по заданиям..."
            autocomplete="off"
          >

          <button
            onclick="performJobsSearch()"
          >
            Найти
          </button>

        </div>


        <div
          class="job-filters"
          id="jobFilters"
        ></div>


        <div
          class="jobs-list"
          id="jobList"
        >
          <div class="jobs-empty">
            Загрузка…
          </div>
        </div>

      </div>
    `;


  setupJobsSearch();

  await loadCacheIfNeeded();

  renderModernJobs();

}


/* =========================================================
   КЭШ
   ========================================================= */

async function loadCacheIfNeeded() {

  if (jobsCache.length) {
    return;
  }

  try {

    jobsCache =
      normalizeJobs(
        await api(
          '/api/jobs?status=active'
        )
      );

    drawJobs();

  } catch (error) {

    toast(
      error.message
    );

  }
}


/* =========================================================
   КАТЕГОРИИ
   ========================================================= */

function getCategories() {

  const categories = [
    'all'
  ];

  jobsCache.forEach(job => {

    const category =
      job.category ||
      'Другое';

    if (
      !categories.includes(
        category
      )
    ) {

      categories.push(
        category
      );

    }

  });

  return categories;
}


function renderFilters() {

  const container =
    $('jobFilters');

  if (!container) {
    return;
  }

  container.innerHTML =
    getCategories()
      .map(category => {

        const active =
          currentJobFilter === category
            ? 'active'
            : '';

        const title =
          category === 'all'
            ? 'Все'
            : category;

        return `
          <button
            class="job-filter ${active}"
            onclick="setJobFilter('${esc(category)}')"
          >
            ${esc(title)}
          </button>
        `;

      })
      .join('');
}


function setJobFilter(category) {

  currentJobFilter =
    category;

  renderFilters();

  renderModernJobs();

}


/* =========================================================
   ПОИСК ЗАДАНИЙ
   ========================================================= */

function setupJobsSearch() {

  const input =
    $('jobsSearch');

  if (!input) {
    return;
  }

  input.addEventListener(
    'input',
    () => {

      currentSearchQuery =
        input.value
          .trim()
          .toLowerCase();

      renderModernJobs();

    }
  );


  input.addEventListener(
    'keydown',
    event => {

      if (
        event.key === 'Enter'
      ) {

        performJobsSearch();

      }

    }
  );

}


function performJobsSearch() {

  const input =
    $('jobsSearch');

  currentSearchQuery =
    input
      ? input.value
          .trim()
          .toLowerCase()
      : '';

  renderModernJobs();

}


/* =========================================================
   ФИЛЬТРАЦИЯ
   ========================================================= */

function getFilteredJobs() {

  return jobsCache.filter(job => {

    const category =
      job.category ||
      'Другое';

    if (
      currentJobFilter !== 'all' &&
      category !== currentJobFilter
    ) {
      return false;
    }

    if (!currentSearchQuery) {
      return true;
    }

    const text =
      [
        job.title,
        job.description,
        job.category,
        job.address,
        job.location
      ]
        .join(' ')
        .toLowerCase();

    return text.includes(
      currentSearchQuery
    );

  });

}


/* =========================================================
   СОВРЕМЕННЫЙ СПИСОК
   ========================================================= */

function renderModernJobs() {

  const container =
    $('jobList');

  if (!container) {
    return;
  }

  renderFilters();

  const list =
    getFilteredJobs();

  const count =
    $('jobsCount');

  if (count) {
    count.textContent =
      list.length;
  }


  if (!list.length) {

    container.innerHTML =
      `
        <div class="jobs-empty">

          <div class="jobs-empty-icon">
            🔎
          </div>

          <b>
            Ничего не нашли
          </b>

          <span>
            Попробуй изменить поиск или категорию.
          </span>

        </div>
      `;

    return;
  }


  container.innerHTML =
    list
      .map(modernJobCard)
      .join('');

}


/* =========================================================
   КАРТОЧКА
   ========================================================= */

function categoryIcon(category) {

  const icons = {

    'Курьер': '🚴',

    'Уборка': '🧹',

    'Ремонт': '🔧',

    'IT': '💻',

    'Помощь по дому': '🏠',

    'Другое': '✦'

  };

  return icons[category] || '✦';
}


function modernJobCard(job) {

  const category =
    job.category ||
    'Другое';

  const description =
    job.description ||
    'Без описания';


  const distance =
    job.distance != null
      ? `
        <span class="modern-job-chip">
          📍 ${Number(job.distance).toFixed(1)} км
        </span>
      `
      : '';


  return `
    <article
      class="modern-job-card"
      onclick="openJob(${Number(job.id)})"
    >

      <div class="modern-job-top">

        <div class="modern-job-icon">
          ${categoryIcon(category)}
        </div>

        <div class="modern-job-main">

          <div class="modern-job-title">
            ${esc(job.title)}
          </div>

          <div class="modern-job-category">
            ${esc(category)}
          </div>

        </div>

      </div>


      <div class="modern-job-price">
        ${money(job.price)}
      </div>


      <div class="modern-job-description">
        ${esc(description)}
      </div>


      <div class="modern-job-meta">

        <span class="modern-job-chip">
          ${categoryIcon(category)}
          ${esc(category)}
        </span>

        ${distance}

        <span class="modern-job-chip">
          📍 ${esc(addressOf(job))}
        </span>

      </div>

    </article>
  `;
}


/* =========================================================
   СТАРЫЙ RENDER LIST
   Оставляем для совместимости
   ========================================================= */

function renderList(list) {

  const container =
    $('jobList');

  if (!container) {
    return;
  }

  if (!list.length) {

    container.innerHTML =
      `
        <div class="jobs-empty">
          <div class="jobs-empty-icon">🔎</div>
          <b>Подходящих заданий пока нет</b>
          <span>Попробуй посмотреть другие категории.</span>
        </div>
      `;

    return;
  }

  container.innerHTML =
    list
      .map(modernJobCard)
      .join('');

}


/* =========================================================
   ГЛОБАЛЬНЫЙ ПОИСК В ШАПКЕ
   ========================================================= */

async function search() {

  const input =
    $('q');

  if (!input) {
    return;
  }

  const query =
    input.value
      .trim()
      .toLowerCase();


  await loadCacheIfNeeded();

  setNav('njobs');

  const sheet =
    $('sheet');

  if (!sheet) {
    return;
  }

  sheet.classList.remove(
    'hidden'
  );


  currentSearchQuery =
    query;

  currentJobFilter =
    'all';


  sheet.innerHTML =
    `
      <div class="jobs-modern">

        <div class="jobs-header">

          <div>
            <h2>
              ${query ? 'Результаты поиска' : 'Задания рядом'}
            </h2>

            <p>
              ${query
                ? `Поиск: «${esc(query)}»`
                : 'Все доступные задания'
              }
            </p>
          </div>

          <div
            class="jobs-count"
            id="jobsCount"
          >
            0
          </div>

        </div>


        <div class="jobs-search">

          <span>⌕</span>

          <input
            id="jobsSearch"
            type="search"
            value="${esc(query)}"
            placeholder="Поиск по заданиям..."
            autocomplete="off"
          >

          <button
            onclick="performJobsSearch()"
          >
            Найти
          </button>

        </div>


        <div
          class="job-filters"
          id="jobFilters"
        ></div>


        <div
          class="jobs-list"
          id="jobList"
        ></div>

      </div>
    `;


  setupJobsSearch();

  renderModernJobs();

}


/* =========================================================
   СОЗДАНИЕ ЗАДАНИЯ
   ========================================================= */

function create() {

  setNav('ncreate');

  if (!currentUser) {

    openAuth();

    return;
  }

  selectedCoords = null;
  selectedAddress = '';

  const address =
    $('addr');

  if (address) {
    address.textContent =
      'Точка не выбрана';
  }

  $('createM')
    ?.classList
    .remove('hidden');

}


/* =========================================================
   PICKER
   ========================================================= */

function pick() {

  closeM('createM');

  const picker =
    $('picker');

  if (!picker) {
    return;
  }

  picker.classList.remove(
    'hidden'
  );

  pickerAddress =
    'Нажмите на карту';

  pickerCoords =
    null;

  const pa =
    $('pa');

  if (pa) {
    pa.textContent =
      'Нажмите на карту';
  }


  setTimeout(
    () => {

      const center =
        map
          ? map.getCenter()
          : [
              55.7558,
              37.6173
            ];


      if (!pickerMap) {

        pickerMap =
          new ymaps.Map(
            'pm',
            {
              center,
              zoom: 15,

              controls: [
                'zoomControl'
              ],

              suppressMapOpenBlock:
                true
            }
          );


        pickerMap.events.add(
          'click',
          event => {

            const coords =
              event.get(
                'coords'
              );

            selectPickerPoint(
              coords
            );

          }
        );


        setTimeout(
          () => {

            try {

              pickerMap
                .container
                .fitToViewport();

            } catch (_) {}

          },
          200
        );

      } else {

        pickerMap
          .container
          .fitToViewport();

        pickerMap.setCenter(
          center,
          15,
          {
            duration: 300
          }
        );

      }

    },
    150
  );

}


/* =========================================================
   ВЫБОР ТОЧКИ
   ========================================================= */

function selectPickerPoint(
  coords
) {

  if (!pickerMap) {
    return;
  }

  pickerCoords = [
    Number(coords[0]),
    Number(coords[1])
  ];


  if (pickerMarker) {

    try {

      pickerMap.geoObjects.remove(
        pickerMarker
      );

    } catch (_) {}

  }


  pickerMarker =
    new ymaps.Placemark(
      pickerCoords,
      {
        hintContent:
          'Выбранное место',

        balloonContent:
          'Выбранное место'
      },
      {
        preset:
          'islands#redDotIcon'
      }
    );


  pickerMap.geoObjects.add(
    pickerMarker
  );


  const pa =
    $('pa');

  if (pa) {
    pa.textContent =
      'Определяем адрес…';
  }


  resolveAddress(
    pickerCoords
  ).then(address => {

    pickerAddress =
      address;

    if (pa) {
      pa.textContent =
        address;
    }

  });

}


/* =========================================================
   ГЕОКОДИРОВАНИЕ
   ========================================================= */

async function resolveAddress(
  coords
) {

  try {

    const result =
      await ymaps.geocode(
        coords
      );

    const object =
      result.geoObjects.get(
        0
      );

    if (object) {

      return object
        .getAddressLine();

    }

    return `
      Точка
      ${coords[0].toFixed(5)},
      ${coords[1].toFixed(5)}
    `;

  } catch (_) {

    return `
      Точка
      ${coords[0].toFixed(5)},
      ${coords[1].toFixed(5)}
    `;

  }

}


/* =========================================================
   ПОДТВЕРЖДЕНИЕ МЕСТА
   ========================================================= */

function confirmPick() {

  if (!pickerCoords) {

    toast(
      'Сначала нажмите на карту'
    );

    return;
  }

  selectedCoords = [
    Number(pickerCoords[0]),
    Number(pickerCoords[1])
  ];

  selectedAddress =
    pickerAddress ||
    'Точка на карте';

  const address =
    $('addr');

  if (address) {
    address.textContent =
      selectedAddress;
  }

  closePick();

  $('createM')
    ?.classList
    .remove('hidden');

  toast(
    'Место выбрано'
  );

}


/* =========================================================
   ЗАКРЫТЬ PICKER
   ========================================================= */

function closePick() {

  const picker =
    $('picker');

  if (picker) {

    picker.classList.add(
      'hidden'
    );

  }

}


/* =========================================================
   СОХРАНЕНИЕ ЗАДАНИЯ
   ========================================================= */

async function saveJob() {

  if (!currentUser) {

    openAuth();

    return;
  }


  if (!selectedCoords) {

    toast(
      'Сначала выберите место на карте'
    );

    return;
  }


  const title =
    $('jt')
      ?.value
      .trim();


  const price =
    Number(
      $('jp')?.value
    );


  if (!title) {

    toast(
      'Введите название задания'
    );

    return;
  }


  if (
    !price ||
    price < 1
  ) {

    toast(
      'Введите корректную оплату'
    );

    return;
  }


  try {

    await api(
      '/api/jobs',
      {
        method: 'POST',

        body:
          JSON.stringify(
            {
              title,

              description:
                $('jd')
                  ?.value
                  .trim() ||
                '',

              price,

              category:
                $('jc')
                  ?.value ||
                'Другое',

              lat:
                selectedCoords[0],

              lng:
                selectedCoords[1],

              address:
                selectedAddress
            }
          )
      }
    );


    if ($('jt')) {
      $('jt').value = '';
    }

    if ($('jd')) {
      $('jd').value = '';
    }

    if ($('jp')) {
      $('jp').value = '';
    }


    selectedCoords =
      null;

    selectedAddress =
      '';


    const address =
      $('addr');

    if (address) {
      address.textContent =
        'Точка не выбрана';
    }


    closeM('createM');

    jobsCache = [];

    await loadJobs();

    goMap();

    toast(
      'Задание опубликовано'
    );


  } catch (error) {

    toast(
      error.message
    );

  }

}


/* =========================================================
   ОТКРЫТИЕ ЗАДАНИЯ
   ========================================================= */

async function openJob(id) {

  try {

    const job =
      await api(
        '/api/jobs/' +
        id
      );


    const title =
      $('dt');

    if (title) {

      title.textContent =
        job.title ||
        'Задание';

    }


    const author =
      getAuthor(job);


    let html =
      `
        <div class="modern-detail">

          <div class="profile-hero">

            ${
              author.avatar_url
                ? `
                  <img
                    class="avatar"
                    src="${esc(
                      author.avatar_url
                    )}"
                    onerror="
                      this.style.display='none'
                    "
                  >
                `
                : ''
            }

            <div>

              <b>
                ${esc(
                  author.name ||
                  job.author_name ||
                  'Пользователь'
                )}
              </b>

              <div class="muted">
                ★
                ${Number(
                  author.rating ??
                  job.author_rating ??
                  0
                ).toFixed(1)}
              </div>

            </div>

          </div>


          <div class="detail-price-box">

            <div>
              <span>Оплата</span>
              <div>
                <b>
                  ${money(job.price)}
                </b>
              </div>
            </div>

            <div>
              <span>Категория</span>
              <div>
                <b style="
                  font-size:14px;
                  color:inherit
                ">
                  ${esc(
                    job.category ||
                    'Другое'
                  )}
                </b>
              </div>
            </div>

          </div>


          <div class="detail-section">

            <div class="detail-section-title">
              Описание
            </div>

            <div class="detail-description">
              ${esc(
                job.description ||
                'Заказчик не добавил описание.'
              )}
            </div>

          </div>


          <div class="detail-section">

            <div class="detail-section-title">
              Место
            </div>

            <div>
              📍 ${esc(
                addressOf(job)
              )}
            </div>

          </div>

      `;


    if (
      job.lat != null &&
      job.lng != null
    ) {

      html +=
        `
          <div class="detail-actions">

            <button
              class="secondary"
              onclick="
                focusJob(
                  ${Number(job.lat)},
                  ${Number(job.lng)}
                )
              "
            >
              📍 Показать на карте
            </button>

          </div>
        `;

    }


    if (
      currentUser &&
      Number(currentUser.id) !==
        Number(job.user_id) &&
      job.status === 'active'
    ) {

      html +=
        `
          <div class="detail-actions">

            <button
              class="primary"
              onclick="
                respondTo(
                  ${Number(job.id)}
                )
              "
            >
              Откликнуться
            </button>

            <button
              class="ghost"
              onclick="
                toggleFavorite(
                  ${Number(job.id)}
                )
              "
            >
              ♡ Добавить в избранное
            </button>

          </div>
        `;

    }


    if (
      currentUser &&
      Number(currentUser.id) ===
        Number(job.user_id)
    ) {

      html +=
        `
          <div class="detail-actions">

            <button
              class="ghost"
              onclick="
                deleteJob(
                  ${Number(job.id)}
                )
              "
            >
              Удалить задание
            </button>

          </div>
        `;

    }


    html += `</div>`;


    const content =
      $('dc');

    if (content) {
      content.innerHTML =
        html;
    }


    $('detail')
      ?.classList
      .remove('hidden');


  } catch (error) {

    toast(
      error.message
    );

  }

}


/* =========================================================
   ПОКАЗАТЬ ЗАДАНИЕ НА КАРТЕ
   ========================================================= */

function focusJob(
  lat,
  lng
) {

  closeM('detail');

  goMap();

  if (map) {

    map.setCenter(
      [
        lat,
        lng
      ],
      16,
      {
        duration: 500
      }
    );

  }

}


/* =========================================================
   ОТКЛИК
   ========================================================= */

async function respondTo(id) {

  if (!currentUser) {

    openAuth();

    return;
  }


  const message =
    prompt(
      'Сообщение заказчику (необязательно):'
    ) || '';


  try {

    await api(
      '/api/jobs/' +
      id +
      '/respond',
      {
        method: 'POST',

        body:
          JSON.stringify(
            {
              message
            }
          )
      }
    );


    toast(
      'Отклик отправлен'
    );


  } catch (error) {

    toast(
      error.message
    );

  }

}


/* =========================================================
   ИЗБРАННОЕ
   ========================================================= */

async function toggleFavorite(id) {

  if (!currentUser) {

    openAuth();

    return;
  }


  try {

    const result =
      await api(
        '/api/favorites/' +
        id,
        {
          method: 'POST'
        }
      );


    toast(
      result.action === 'added'
        ? 'Добавлено в избранное'
        : 'Удалено из избранного'
    );


  } catch (error) {

    toast(
      error.message
    );

  }

}


/* =========================================================
   ИЗБРАННОЕ — ЭКРАН
   ========================================================= */

async function favoritesView() {

  if (!currentUser) {

    openAuth();

    return;
  }


  setNav('nfav');

  const sheet =
    $('sheet');

  if (!sheet) {
    return;
  }


  sheet.classList.remove(
    'hidden'
  );


  sheet.innerHTML =
    `
      <div class="jobs-modern">

        <div class="jobs-header">

          <div>
            <h2>Избранное</h2>
            <p>
              Задания, которые ты сохранил
            </p>
          </div>

          <div
            class="jobs-count"
            id="jobsCount"
          >
            0
          </div>

        </div>


        <div
          class="jobs-list"
          id="jobList"
        >
          Загрузка…
        </div>

      </div>
    `;


  try {

    const data =
      await api(
        '/api/favorites'
      );

    const list =
      normalizeJobs(data);


    const count =
      $('jobsCount');

    if (count) {
      count.textContent =
        list.length;
    }


    renderList(
      list
    );


  } catch (error) {

    const list =
      $('jobList');

    if (list) {
      list.innerHTML =
        `
          <div class="jobs-empty">
            <b>Не удалось загрузить избранное</b>
            <span>${esc(error.message)}</span>
          </div>
        `;
    }

  }

}


/* =========================================================
   УДАЛЕНИЕ ЗАДАНИЯ
   ========================================================= */

async function deleteJob(id) {

  if (
    !confirm(
      'Удалить это задание?'
    )
  ) {
    return;
  }


  try {

    await api(
      '/api/jobs/' +
      id,
      {
        method: 'DELETE'
      }
    );


    closeM('detail');

    jobsCache = [];

    await loadJobs();

    toast(
      'Задание удалено'
    );


  } catch (error) {

    toast(
      error.message
    );

  }

}


/* =========================================================
   АВТОРИЗАЦИЯ
   ========================================================= */

function openAuth() {

  authMode =
    'login';


  $('auth')
    ?.classList
    .remove('hidden');


  $('login')
    ?.classList
    .remove('hidden');


  $('reg')
    ?.classList
    .add('hidden');


  const title =
    $('at');

  if (title) {
    title.textContent =
      'Вход';
  }


  const switchButton =
    $('authSwitch');

  if (switchButton) {

    switchButton.textContent =
      'Нет аккаунта? Зарегистрироваться';

  }

}


/* =========================================================
   ВХОД / РЕГИСТРАЦИЯ
   ========================================================= */

function toggleAuth() {

  authMode =
    authMode === 'login'
      ? 'register'
      : 'login';


  $('login')
    ?.classList
    .toggle(
      'hidden',
      authMode !== 'login'
    );


  $('reg')
    ?.classList
    .toggle(
      'hidden',
      authMode !== 'register'
    );


  const title =
    $('at');

  if (title) {

    title.textContent =
      authMode === 'login'
        ? 'Вход'
        : 'Регистрация';

  }


  const switchButton =
    $('authSwitch');

  if (switchButton) {

    switchButton.textContent =
      authMode === 'login'
        ? 'Нет аккаунта? Зарегистрироваться'
        : 'Уже есть аккаунт? Войти';

  }


  if (
    authMode === 'register'
  ) {

    const fields =
      $('rf');

    if (
      fields &&
      !fields.innerHTML
    ) {

      fields.innerHTML =
        `
          <label>
            Имя и фамилия

            <input
              id="regName"
              class="field"
              placeholder="Иван Иванов"
              autocomplete="name"
            >
          </label>


          <label>
            Телефон

            <input
              id="regPhone"
              class="field"
              type="tel"
              placeholder="+49 ..."
              autocomplete="tel"
            >
          </label>


          <label>
            Дата рождения

            <input
              id="regBirth"
              class="field"
              type="date"
            >
          </label>


          <label>
            Род деятельности

            <input
              id="regOccupation"
              class="field"
              placeholder="Например: студент, водитель"
            >
          </label>


          <label>
            Роль

            <select
              id="regRole"
              class="field"
            >
              <option value="executor">
                Исполнитель
              </option>

              <option value="customer">
                Заказчик
              </option>

            </select>
          </label>


          <label>
            Email

            <input
              id="regEmail"
              class="field"
              type="email"
              placeholder="you@example.com"
              autocomplete="email"
            >
          </label>


          <label>
            Пароль

            <input
              id="regPassword"
              class="field"
              type="password"
              placeholder="Минимум 6 символов"
              autocomplete="new-password"
            >
          </label>


          <div class="location-box">

            <b>
              Данные паспорта
            </b>

            <div
              class="muted"
              style="
                font-size:12px;
                margin:4px 0 10px
              "
            >
              Данные передаются серверу
              для защищённого хранения.
            </div>


            <label>
              Серия

              <input
                id="regPassportSeries"
                class="field"
                placeholder="0000"
              >
            </label>


            <label>
              Номер

              <input
                id="regPassportNumber"
                class="field"
                placeholder="000000"
              >
            </label>


            <label>
              Кем выдан

              <input
                id="regPassportIssuedBy"
                class="field"
                placeholder="Орган выдачи"
              >
            </label>


            <label>
              Дата выдачи

              <input
                id="regPassportIssueDate"
                class="field"
                type="date"
              >
            </label>

          </div>
        `;

    }

  }

}


/* =========================================================
   ВХОД
   ========================================================= */

async function doLogin() {

  try {

    const email =
      $('le')
        ?.value
        .trim();


    const password =
      $('lp')
        ?.value;


    if (!email) {

      toast(
        'Введите email'
      );

      return;
    }


    if (!password) {

      toast(
        'Введите пароль'
      );

      return;
    }


    const result =
      await api(
        '/api/login',
        {
          method: 'POST',

          body:
            JSON.stringify(
              {
                email,
                password
              }
            )
        }
      );


    token =
      result.token;

    currentUser =
      result.user ||
      result;


    localStorage.setItem(
      'near_token',
      token
    );


    closeM('auth');


    toast(
      'С возвращением, ' +
      (
        currentUser.name ||
        'пользователь'
      )
    );


  } catch (error) {

    toast(
      error.message
    );

  }

}


/* =========================================================
   РЕГИСТРАЦИЯ
   ========================================================= */

async function doReg() {

  const data = {

    name:
      $('regName')
        ?.value
        .trim() ||
      '',

    phone:
      $('regPhone')
        ?.value
        .trim() ||
      '',

    birth_date:
      $('regBirth')
        ?.value ||
      '',

    occupation:
      $('regOccupation')
        ?.value
        .trim() ||
      '',

    role:
      $('regRole')
        ?.value ||
      'executor',

    email:
      $('regEmail')
        ?.value
        .trim() ||
      '',

    password:
      $('regPassword')
        ?.value ||
      '',

    passport_series:
      $('regPassportSeries')
        ?.value
        .trim() ||
      '',

    passport_number:
      $('regPassportNumber')
        ?.value
        .trim() ||
      '',

    passport_issued_by:
      $('regPassportIssuedBy')
        ?.value
        .trim() ||
      '',

    passport_issue_date:
      $('regPassportIssueDate')
        ?.value ||
      ''

  };


  if (!data.name) {

    toast(
      'Введите имя и фамилию'
    );

    return;
  }


  if (!data.email) {

    toast(
      'Введите email'
    );

    return;
  }


  if (
    !data.password ||
    data.password.length < 6
  ) {

    toast(
      'Пароль должен содержать минимум 6 символов'
    );

    return;
  }


  try {

    const result =
      await api(
        '/api/register',
        {
          method: 'POST',

          body:
            JSON.stringify(data)
        }
      );


    token =
      result.token;

    currentUser =
      result.user ||
      result;


    localStorage.setItem(
      'near_token',
      token
    );


    closeM('auth');


    toast(
      'Аккаунт создан'
    );


  } catch (error) {

    toast(
      error.message
    );

  }

}


/* =========================================================
   ВОССТАНОВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ
   ========================================================= */

async function restoreUser() {

  if (!token) {
    return;
  }

  try {

    currentUser =
      await api(
        '/api/me'
      );

  } catch (_) {

    token = '';

    currentUser = null;

    localStorage.removeItem(
      'near_token'
    );

  }

}


/* =========================================================
   ПРОФИЛЬ
   ========================================================= */

async function profile() {

  if (!currentUser) {

    openAuth();

    return;
  }


  setNav('nprof');


  const content =
    $('pc');

  if (!content) {
    return;
  }


  content.innerHTML =
    `
      <div class="profile-hero">

        ${
          currentUser.avatar_url
            ? `
              <img
                class="avatar"
                src="${esc(
                  currentUser.avatar_url
                )}"
                onerror="
                  this.style.display='none'
                "
              >
            `
            : ''
        }


        <div>

          <b>
            ${esc(
              currentUser.name ||
              'Пользователь'
            )}
          </b>

          <div class="muted">
            ${esc(
              currentUser.email ||
              ''
            )}
          </div>

        </div>

      </div>


      <div class="stats">

        <div class="stat">
          <b>
            ${Number(
              currentUser.rating ||
              0
            ).toFixed(1)}
          </b>
          <span>рейтинг</span>
        </div>


        <div class="stat">
          <b>
            ${
              currentUser.reviews_count ||
              0
            }
          </b>
          <span>отзывов</span>
        </div>


        <div class="stat">
          <b>
            ${
              currentUser.completed_jobs ||
              0
            }
          </b>
          <span>выполнено</span>
        </div>

      </div>


      <div class="profile-info">

        <p>
          📱
          ${esc(
            currentUser.phone ||
            'Телефон не указан'
          )}
        </p>


        <p>
          🎂
          ${esc(
            currentUser.birth_date ||
            'Дата рождения не указана'
          )}
        </p>


        <p>
          💼
          ${esc(
            currentUser.occupation ||
            'Род деятельности не указан'
          )}
        </p>


        <p>
          🪪
          Паспорт:
          защищённые данные
        </p>

      </div>


      <div class="setting">

        <div>

          <b>
            Тёмная тема
          </b>

          <div class="muted">
            Спокойная схема для вечера
          </div>

        </div>


        <button
          class="switch ${
            dark ? 'on' : ''
          }"
          onclick="toggleTheme(this)"
        ></button>

      </div>


      <button
        class="secondary"
        style="margin-top:12px"
        onclick="myJobs()"
      >
        Мои задания
      </button>


      <button
        class="ghost"
        onclick="logout()"
      >
        Выйти из аккаунта
      </button>
    `;


  $('prof')
    ?.classList
    .remove('hidden');

}


/* =========================================================
   МОИ ЗАДАНИЯ
   ========================================================= */

async function myJobs() {

  closeM('prof');

  const sheet =
    $('sheet');

  if (!sheet) {
    return;
  }

  sheet.classList.remove(
    'hidden'
  );


  setNav('njobs');


  sheet.innerHTML =
    `
      <div class="jobs-modern">

        <div class="jobs-header">

          <div>
            <h2>Мои задания</h2>
            <p>
              Опубликованные тобой задания
            </p>
          </div>

          <div
            class="jobs-count"
            id="jobsCount"
          >
            0
          </div>

        </div>


        <div
          class="jobs-list"
          id="jobList"
        >
          Загрузка…
        </div>

      </div>
    `;


  try {

    const data =
      await api(
        '/api/jobs?user_id=' +
        encodeURIComponent(
          currentUser.id
        )
      );


    const list =
      normalizeJobs(data);


    const count =
      $('jobsCount');

    if (count) {
      count.textContent =
        list.length;
    }


    renderList(
      list
    );


  } catch (error) {

    const list =
      $('jobList');

    if (list) {

      list.innerHTML =
        `
          <div class="jobs-empty">
            <b>Ошибка загрузки</b>
            <span>${esc(error.message)}</span>
          </div>
        `;

    }

  }

}


/* =========================================================
   ВЫХОД
   ========================================================= */

async function logout() {

  try {

    await api(
      '/api/logout',
      {
        method: 'POST'
      }
    );

  } catch (_) {}


  token = '';

  currentUser = null;

  localStorage.removeItem(
    'near_token'
  );

  closeM('prof');

  setNav('nmap');

  toast(
    'Вы вышли из аккаунта'
  );

}


/* =========================================================
   ESCAPE
   ========================================================= */

document.addEventListener(
  'keydown',
  event => {

    if (
      event.key !== 'Escape'
    ) {
      return;
    }

    [
      'auth',
      'createM',
      'detail',
      'prof'
    ]
      .forEach(closeM);

    closePick();

  }
);


/* =========================================================
   ЗАПУСК
   ========================================================= */

setupSearch();

init();
