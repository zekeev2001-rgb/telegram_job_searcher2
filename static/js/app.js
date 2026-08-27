/* =========================================================
   NEAR GIG — APP.JS
   Версия совместима с текущим templates/index.html
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

const $ = id => document.getElementById(id);

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
  new Intl.NumberFormat('ru-RU').format(Number(value || 0)) + ' ₽';


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
    headers.Authorization = 'Bearer ' + token;
  }

  let response;

  try {
    response = await fetch(url, {
      ...options,
      headers
    });
  } catch (error) {
    console.error('Near Gig API network error:', error);

    throw new Error(
      'Не удалось подключиться к серверу. Проверьте соединение.'
    );
  }

  let data = {};

  try {
    data = await response.json();
  } catch (_) {
    data = {};
  }

  if (!response.ok) {
    console.error('Near Gig API error:', {
      url,
      status: response.status,
      data
    });

    throw new Error(
      data.error ||
      `Ошибка сервера: HTTP ${response.status}`
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
   ДАННЫЕ ЗАДАНИЙ
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

    toast(
      'Ошибка карты: элемент карты не найден.'
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


  /*
     Клик по основной карте.

     Если включён режим выбора места,
     точка ставится именно туда,
     куда нажал пользователь.
  */

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


  /*
     После создания карты немного
     ждём и обновляем размер.
  */

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
   ОТОБРАЖЕНИЕ ЗАДАНИЙ НА КАРТЕ
   ========================================================= */

function drawJobs() {

  if (!map) {
    return;
  }

  /*
     Не удаляем выбранную пользователем
     точку, если она существует.
  */

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
              <div style="padding:8px;min-width:180px">
                <b>${esc(job.title)}</b>
                <br>
                <span>${esc(addressOf(job))}</span>
                <br>
                <strong>${money(job.price)}</strong>
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


  /*
     Возвращаем пользовательскую
     выбранную точку поверх заданий.
  */

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


  /*
     Удаляем старый маркер.
  */

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


  /*
     Создаём красивый маркер.
  */

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


  /*
     Центрируем карту на выбранной
     точке.
  */

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


  /*
     Получаем адрес.
  */

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
   ПЕРЕХОД НА КАРТУ
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
   ЗАДАНИЯ
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


  sheet.innerHTML =
    `
      <h2>Задания рядом</h2>

      <div class="sheet-note">
        Свежие предложения пользователей Near Gig
      </div>

      <div id="jobList">
        Загрузка…
      </div>
    `;


  await loadCacheIfNeeded();

  renderList(
    jobsCache
  );
}


/* =========================================================
   КЭШ ЗАДАНИЙ
   ========================================================= */

async function loadCacheIfNeeded() {

  if (
    jobsCache.length
  ) {
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
   СПИСОК
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
        <div class="muted">
          Подходящих заданий пока нет.
        </div>
      `;

    return;
  }


  container.innerHTML =
    list
      .map(jobCard)
      .join('');
}


/* =========================================================
   КАРТОЧКА ЗАДАНИЯ
   ========================================================= */

function jobCard(job) {

  return `
    <article
      class="job-card"
      onclick="openJob(${Number(job.id)})"
    >

      <div class="job-line">

        <div class="job-title">
          ${esc(job.title)}
        </div>

        <div class="price">
          ${money(job.price)}
        </div>

      </div>


      <div
        class="muted"
        style="margin-top:7px"
      >
        ${esc(
          job.description ||
          'Без описания'
        )}
      </div>


      <div class="chips">

        <span class="chip">
          ${esc(
            job.category ||
            'Другое'
          )}
        </span>

        <span class="chip">
          ⌖ ${esc(
            addressOf(job)
          )}
        </span>

        ${
          job.distance != null
            ? `
              <span class="chip">
                ${Number(
                  job.distance
                ).toFixed(1)}
                км
              </span>
            `
            : ''
        }

      </div>

    </article>
  `;
}


/* =========================================================
   ПОИСК
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


  sheet.innerHTML =
    `
      <h2>Поиск</h2>

      <div class="sheet-note">
        Результаты по названию,
        описанию и категории
      </div>

      <div id="jobList"></div>
    `;


  if (!query) {

    renderList(
      jobsCache
    );

    return;
  }


  const result =
    jobsCache.filter(
      job => {

        const text =
          [
            job.title,
            job.description,
            job.category,
            job.address
          ]
            .join(' ')
            .toLowerCase();

        return text.includes(
          query
        );

      }
    );


  renderList(
    result
  );
}


/* =========================================================
   ENTER В ПОИСКЕ
   ========================================================= */

function setupSearch() {

  const input =
    $('q');

  if (!input) {
    return;
  }


  input.addEventListener(
    'keydown',
    event => {

      if (
        event.key === 'Enter'
      ) {

        search();

      }

    }
  );

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
   ОТКРЫТЬ ВЫБОР МЕСТА
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


  /*
     Создаём карту только один раз.
  */

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


        /*
           САМОЕ ВАЖНОЕ:

           Пользователь нажимает
           пальцем или мышкой
           в конкретную точку.

           Маркер появляется именно
           в этой точке.
        */

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


        /*
           При изменении размера
           обновляем карту.
        */

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
   ВЫБОР ТОЧКИ В PICKER
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


  /*
     Удаляем старый маркер.
  */

  if (pickerMarker) {

    try {

      pickerMap.geoObjects.remove(
        pickerMarker
      );

    } catch (_) {}

  }


  /*
     Создаём новый маркер
     ТОЧНО в месте клика.
  */

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


  /*
     Обновляем текст.
  */

  const pa =
    $('pa');

  if (pa) {

    pa.textContent =
      'Определяем адрес…';

  }


  /*
     Получаем адрес.
  */

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
   ЗАКРЫТИЕ PICKER
   ========================================================= */

function closePick() {

  const picker =
    $('picker');

  if (picker) {

    picker.classList.add(
      'hidden'
    );

  }


  /*
     Важно:

     pickerMap НЕ уничтожаем.

     Это позволяет повторно открыть
     карту намного быстрее.
  */

}


/* =========================================================
   СОХРАНЕНИЕ ЗАДАНИЯ
   ========================================================= */

async function saveJob() {

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

        body: JSON.stringify(
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


    /*
       Очищаем форму.
    */

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


    /*
       Обновляем задания.
    */

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

          <div
            style="margin-left:auto"
            class="price"
          >
            ${money(job.price)}
          </div>

        </div>


        <div
          class="job-card"
          style="cursor:default"
        >

          <div>
            ${esc(
              job.description ||
              'Без описания'
            )}
          </div>


          <div class="chips">

            <span class="chip">
              ${esc(
                job.category ||
                'Другое'
              )}
            </span>

            <span class="chip">
              ⌖
              ${esc(
                addressOf(job)
              )}
            </span>

          </div>

        </div>
      `;


    if (
      job.lat != null &&
      job.lng != null
    ) {

      html +=
        `
          <button
            class="secondary"
            onclick="
              focusJob(
                ${Number(job.lat)},
                ${Number(job.lng)}
              )
            "
          >
            Показать на карте
          </button>
        `;

    }


    /*
       Отклик.
    */

    if (
      currentUser &&
      Number(currentUser.id) !==
        Number(job.user_id) &&
      job.status === 'active'
    ) {

      html +=
        `
          <div style="height:9px"></div>

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
        `;

    }


    /*
       Удаление своего задания.
    */

    if (
      currentUser &&
      Number(currentUser.id) ===
        Number(job.user_id)
    ) {

      html +=
        `
          <div style="height:9px"></div>

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
        `;

    }


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

        body: JSON.stringify(
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

async function toggleFavorite(
  id
) {

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
   ПРОСМОТР ИЗБРАННОГО
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
      <h2>Избранное</h2>

      <div class="sheet-note">
        Сохранённые задания
      </div>

      <div id="jobList">
        Загрузка…
      </div>
    `;


  try {

    const data =
      await api(
        '/api/favorites'
      );


    const list =
      normalizeJobs(data);


    renderList(
      list
    );


  } catch (error) {

    const list =
      $('jobList');

    if (list) {

      list.textContent =
        error.message;

    }

  }

}


/* =========================================================
   УДАЛЕНИЕ ЗАДАНИЯ
   ========================================================= */

async function deleteJob(
  id
) {

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
   ПЕРЕКЛЮЧЕНИЕ ВХОД / РЕГИСТРАЦИЯ
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


  /*
     Поля регистрации создаём
     только один раз.
  */

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

          body: JSON.stringify(
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

          <span>
            рейтинг
          </span>

        </div>


        <div class="stat">

          <b>
            ${
              currentUser.reviews_count ||
              0
            }
          </b>

          <span>
            отзывов
          </span>

        </div>


        <div class="stat">

          <b>
            ${
              currentUser.completed_jobs ||
              0
            }
          </b>

          <span>
            выполнено
          </span>

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


  sheet.innerHTML =
    `
      <h2>
        Мои задания
      </h2>

      <div class="sheet-note">
        Опубликованные тобой задания
      </div>

      <div id="jobList">
        Загрузка…
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


    renderList(
      normalizeJobs(data)
    );


  } catch (error) {

    const list =
      $('jobList');

    if (list) {

      list.textContent =
        error.message;

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
