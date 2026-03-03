/* Israel Building Plans Finder - Frontend JS */

// ─── DOM refs ───
const smartForm = document.getElementById('search-form');
const freeForm = document.getElementById('free-text-form');
const freeInput = document.getElementById('address-input');
const searchBtn = document.getElementById('search-btn');
const loading = document.getElementById('loading');
const errorSection = document.getElementById('error-section');
const errorMessage = document.getElementById('error-message');
const results = document.getElementById('results');

const cityInput = document.getElementById('city-input');
const cityCodeEl = document.getElementById('city-code');
const cityDropdown = document.getElementById('city-dropdown');
const streetInput = document.getElementById('street-input');
const streetDropdown = document.getElementById('street-dropdown');
const houseInput = document.getElementById('house-input');

let currentImages = [];
let lightboxIndex = 0;

const SOURCE_BADGES = {
  'ארכיון הנדסה ת"א': 'badge-teal',
  'XPLAN (תכניות ארציות)': 'badge-indigo',
  'מבא"ת (מידע תכנוני)': 'badge-purple',
  'Mapillary': 'badge-green',
  'Wikimedia Commons': 'badge-amber',
  'Google Maps Street View': 'badge-orange',
};

const TYPE_CLASSES = {
  'היתר': 'type-permit',
  'תב"ע': 'type-plan',
  'תעודת גמר': 'type-completion',
  'אחר': 'type-other',
};

// ─── Autocomplete state ───
let citiesCache = null;
let streetsCache = {};
let cityActiveIdx = -1;
let streetActiveIdx = -1;

// ─── Utilities ───
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function highlightMatch(text, query) {
  if (!query) return esc(text);
  const idx = text.indexOf(query);
  if (idx === -1) return esc(text);
  return esc(text.slice(0, idx)) + '<mark>' + esc(text.slice(idx, idx + query.length)) + '</mark>' + esc(text.slice(idx + query.length));
}

// ─── City autocomplete ───
async function fetchCities(query) {
  if (citiesCache) {
    const q = query.trim();
    if (!q) return citiesCache;
    return citiesCache.filter(c =>
      c.name.includes(q) || c.name_en.toLowerCase().includes(q.toLowerCase())
    );
  }
  try {
    const resp = await fetch(`/api/address/cities?q=`);
    if (!resp.ok) return [];
    citiesCache = await resp.json();
    return query ? citiesCache.filter(c =>
      c.name.includes(query) || c.name_en.toLowerCase().includes(query.toLowerCase())
    ) : citiesCache;
  } catch { return []; }
}

function renderCityDropdown(cities, query) {
  cityDropdown.innerHTML = '';
  cityActiveIdx = -1;
  if (!cities.length) {
    cityDropdown.innerHTML = '<div class="ac-empty">לא נמצאו ערים</div>';
    cityDropdown.classList.remove('hidden');
    return;
  }
  const shown = cities.slice(0, 15);
  shown.forEach((c, i) => {
    const div = document.createElement('div');
    div.className = 'ac-option';
    div.dataset.index = i;
    div.innerHTML = `<span>${highlightMatch(c.name, query)}</span><span class="ac-secondary">${esc(c.name_en)}</span>`;
    div.addEventListener('mousedown', (e) => {
      e.preventDefault();
      selectCity(c);
    });
    cityDropdown.appendChild(div);
  });
  cityDropdown.classList.remove('hidden');
}

function selectCity(city) {
  cityInput.value = city.name;
  cityCodeEl.value = city.code;
  cityInput.classList.add('ac-selected');
  cityDropdown.classList.add('hidden');

  streetInput.disabled = false;
  streetInput.value = '';
  streetInput.classList.remove('ac-selected');
  streetDropdown.classList.add('hidden');
  streetsCache[city.code] = null;
  streetInput.focus();
}

function clearCity() {
  cityInput.value = '';
  cityCodeEl.value = '';
  cityInput.classList.remove('ac-selected');
  streetInput.disabled = true;
  streetInput.value = '';
  streetInput.classList.remove('ac-selected');
  streetDropdown.classList.add('hidden');
}

const debouncedCitySearch = debounce(async () => {
  const q = cityInput.value.trim();
  if (cityCodeEl.value && cityInput.classList.contains('ac-selected')) {
    clearCity();
  }
  if (q.length < 1) {
    cityDropdown.classList.add('hidden');
    return;
  }
  const cities = await fetchCities(q);
  renderCityDropdown(cities, q);
}, 200);

cityInput.addEventListener('input', debouncedCitySearch);
cityInput.addEventListener('focus', async () => {
  const q = cityInput.value.trim();
  if (q.length >= 1 && !cityInput.classList.contains('ac-selected')) {
    const cities = await fetchCities(q);
    renderCityDropdown(cities, q);
  }
});
cityInput.addEventListener('blur', () => {
  setTimeout(() => cityDropdown.classList.add('hidden'), 150);
});
cityInput.addEventListener('keydown', (e) => {
  if (cityDropdown.classList.contains('hidden')) return;
  const opts = cityDropdown.querySelectorAll('.ac-option');
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    cityActiveIdx = Math.min(cityActiveIdx + 1, opts.length - 1);
    updateActive(opts, cityActiveIdx);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    cityActiveIdx = Math.max(cityActiveIdx - 1, 0);
    updateActive(opts, cityActiveIdx);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (cityActiveIdx >= 0 && opts[cityActiveIdx]) {
      opts[cityActiveIdx].dispatchEvent(new MouseEvent('mousedown'));
    }
  } else if (e.key === 'Escape') {
    cityDropdown.classList.add('hidden');
  }
});

// ─── Street autocomplete ───
async function fetchStreets(cityCode, query) {
  if (streetsCache[cityCode]) {
    const q = query.trim();
    if (!q) return streetsCache[cityCode];
    return streetsCache[cityCode].filter(s => s.name.includes(q));
  }
  try {
    const resp = await fetch(`/api/address/streets?city_code=${cityCode}&q=`);
    if (!resp.ok) return [];
    streetsCache[cityCode] = await resp.json();
    return query ? streetsCache[cityCode].filter(s => s.name.includes(query)) : streetsCache[cityCode];
  } catch { return []; }
}

function renderStreetDropdown(streets, query) {
  streetDropdown.innerHTML = '';
  streetActiveIdx = -1;
  if (!streets.length) {
    streetDropdown.innerHTML = '<div class="ac-empty">לא נמצאו רחובות</div>';
    streetDropdown.classList.remove('hidden');
    return;
  }
  const shown = streets.slice(0, 15);
  shown.forEach((s, i) => {
    const div = document.createElement('div');
    div.className = 'ac-option';
    div.dataset.index = i;
    div.innerHTML = `<span>${highlightMatch(s.name, query)}</span>`;
    div.addEventListener('mousedown', (e) => {
      e.preventDefault();
      selectStreet(s);
    });
    streetDropdown.appendChild(div);
  });
  streetDropdown.classList.remove('hidden');
}

function selectStreet(street) {
  streetInput.value = street.name;
  streetInput.classList.add('ac-selected');
  streetDropdown.classList.add('hidden');
  houseInput.focus();
}

const debouncedStreetSearch = debounce(async () => {
  const code = cityCodeEl.value;
  if (!code) return;
  const q = streetInput.value.trim();
  if (streetInput.classList.contains('ac-selected')) {
    streetInput.classList.remove('ac-selected');
  }
  if (q.length < 1) {
    streetDropdown.classList.add('hidden');
    return;
  }
  const streets = await fetchStreets(parseInt(code), q);
  renderStreetDropdown(streets, q);
}, 200);

streetInput.addEventListener('input', debouncedStreetSearch);
streetInput.addEventListener('focus', async () => {
  const code = cityCodeEl.value;
  const q = streetInput.value.trim();
  if (code && q.length >= 1 && !streetInput.classList.contains('ac-selected')) {
    const streets = await fetchStreets(parseInt(code), q);
    renderStreetDropdown(streets, q);
  }
});
streetInput.addEventListener('blur', () => {
  setTimeout(() => streetDropdown.classList.add('hidden'), 150);
});
streetInput.addEventListener('keydown', (e) => {
  if (streetDropdown.classList.contains('hidden')) return;
  const opts = streetDropdown.querySelectorAll('.ac-option');
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    streetActiveIdx = Math.min(streetActiveIdx + 1, opts.length - 1);
    updateActive(opts, streetActiveIdx);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    streetActiveIdx = Math.max(streetActiveIdx - 1, 0);
    updateActive(opts, streetActiveIdx);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (streetActiveIdx >= 0 && opts[streetActiveIdx]) {
      opts[streetActiveIdx].dispatchEvent(new MouseEvent('mousedown'));
    }
  } else if (e.key === 'Escape') {
    streetDropdown.classList.add('hidden');
  }
});

function updateActive(opts, idx) {
  opts.forEach((o, i) => o.classList.toggle('ac-active', i === idx));
  if (opts[idx]) opts[idx].scrollIntoView({ block: 'nearest' });
}

// ─── Form toggle (smart <-> free-text) ───
document.getElementById('toggle-free-text').addEventListener('click', (e) => {
  e.preventDefault();
  smartForm.classList.add('hidden');
  freeForm.classList.remove('hidden');
  freeInput.focus();
});
document.getElementById('toggle-smart').addEventListener('click', (e) => {
  e.preventDefault();
  freeForm.classList.add('hidden');
  smartForm.classList.remove('hidden');
  cityInput.focus();
});

// ─── Smart form submit ───
smartForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const city = cityInput.value.trim();
  const street = streetInput.value.trim();
  const house = houseInput.value.trim();
  if (!city) { cityInput.focus(); return; }

  let q = '';
  if (street) {
    q = house ? `${street} ${house}, ${city}` : `${street}, ${city}`;
  } else {
    q = city;
  }
  setQueryParam(q);
  await doSearch(q);
});

// ─── Free-text form submit ───
freeForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = freeInput.value.trim();
  if (!q) return;
  setQueryParam(q);
  await doSearch(q);
});

// ─── Load supported cities on startup ───
async function loadSupportedCities() {
  try {
    const resp = await fetch('/api/sources');
    if (!resp.ok) return;
    const data = await resp.json();
    const cities = Object.keys(data).filter(c => c !== '_default');
    const el = document.getElementById('supported-cities');
    if (el && cities.length) {
      const tags = cities.slice(0, 10).map(c => `<span class="tag">${esc(c)}</span>`).join(' ');
      const more = cities.length > 10 ? ` <span class="tag">+ ${cities.length - 10} ערים נוספות</span>` : '';
      el.innerHTML = `ערים עם מקורות ייעודיים: ${tags}${more} <span class="tag">+ כל ישראל via XPLAN</span>`;
    }
  } catch (_) { /* ignore */ }
}

// ─── URL deep-linking ───
function getQueryParam() {
  return new URLSearchParams(window.location.search).get('q') || '';
}

function setQueryParam(q) {
  const url = new URL(window.location);
  url.searchParams.set('q', q);
  history.pushState({}, '', url);
}

// ─── Search ───
async function doSearch(q) {
  showLoading();
  try {
    const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || 'שגיאה בחיפוש');
    }
    const data = await resp.json();
    renderResults(data);
  } catch (err) {
    showError(err.message);
  }
}

function showLoading() {
  loading.classList.remove('hidden');
  errorSection.classList.add('hidden');
  results.classList.add('hidden');
  searchBtn.disabled = true;
}

function showError(msg) {
  loading.classList.add('hidden');
  results.classList.add('hidden');
  errorSection.classList.remove('hidden');
  errorMessage.textContent = msg;
  searchBtn.disabled = false;
}

function showResults() {
  loading.classList.add('hidden');
  errorSection.classList.add('hidden');
  results.classList.remove('hidden');
  searchBtn.disabled = false;
}

// ─── Render ───
function renderResults(data) {
  showResults();

  const geo = data.geocode;
  document.getElementById('result-address').textContent = geo.display_name;
  document.getElementById('result-coords').textContent = `נ.צ: ${geo.lat.toFixed(5)}, ${geo.lon.toFixed(5)}`;

  const cacheBadge = document.getElementById('cache-badge');
  cacheBadge.classList.toggle('hidden', !data.from_cache);

  document.getElementById('copy-link').onclick = () => {
    navigator.clipboard.writeText(window.location.href);
    const btn = document.getElementById('copy-link');
    btn.textContent = '✓ הועתק!';
    setTimeout(() => { btn.textContent = 'העתק קישור'; }, 2000);
  };

  renderImages(data.images);
  renderPlans(data.plans);

  const mapFrame = document.getElementById('map-iframe');
  mapFrame.src = `https://www.openstreetmap.org/export/embed.html?bbox=${geo.lon - 0.003},${geo.lat - 0.002},${geo.lon + 0.003},${geo.lat + 0.002}&layer=mapnik&marker=${geo.lat},${geo.lon}`;

  document.getElementById('sources-tried').textContent = data.sources_tried.join(', ');
}

function renderImages(images) {
  const grid = document.getElementById('images-grid');
  const noImages = document.getElementById('no-images');
  const count = document.getElementById('images-count');
  grid.innerHTML = '';

  const photoImages = images.filter(img => img.thumbnail_url);
  const linkImages = images.filter(img => !img.thumbnail_url && img.url);

  currentImages = photoImages;

  if (!photoImages.length && !linkImages.length) {
    grid.classList.add('hidden');
    noImages.classList.remove('hidden');
    count.textContent = '';
    return;
  }

  grid.classList.remove('hidden');
  noImages.classList.add('hidden');
  count.textContent = `(${photoImages.length} תמונות)`;

  photoImages.forEach((img, i) => {
    const card = document.createElement('div');
    card.className = 'image-card';
    card.onclick = () => openLightbox(i);

    const imgEl = document.createElement('img');
    imgEl.src = img.thumbnail_url;
    imgEl.alt = `Street view - ${img.source}`;
    imgEl.loading = 'lazy';
    imgEl.onerror = function() {
      this.parentElement.style.display = 'none';
    };
    card.appendChild(imgEl);

    const badge = document.createElement('div');
    badge.className = 'image-badge';
    badge.textContent = `${img.source}${img.date ? ' · ' + img.date : ''}`;
    card.appendChild(badge);

    grid.appendChild(card);
  });

  linkImages.forEach((img) => {
    const card = document.createElement('a');
    card.className = 'gsv-link-card';
    card.href = img.url;
    card.target = '_blank';
    card.rel = 'noopener';

    card.innerHTML = `
      <div class="gsv-icon">🗺️</div>
      <div class="gsv-label">${esc(img.source)}<br><span style="font-weight:400;font-size:0.7rem">לחצו לפתיחה</span></div>
    `;
    grid.appendChild(card);
  });
}

function renderPlans(plans) {
  const list = document.getElementById('plans-list');
  const noPlans = document.getElementById('no-plans');
  const count = document.getElementById('plans-count');
  list.innerHTML = '';

  if (!plans.length) {
    list.classList.add('hidden');
    noPlans.classList.remove('hidden');
    count.textContent = '';
    return;
  }

  list.classList.remove('hidden');
  noPlans.classList.add('hidden');
  count.textContent = `(${plans.length})`;

  plans.forEach((plan, idx) => {
    const card = document.createElement('div');
    card.className = 'plan-card';
    card.id = `plan-${idx}`;

    const badgeClass = SOURCE_BADGES[plan.source] || 'badge-gray';
    const typeClass = TYPE_CLASSES[plan.plan_type] || 'type-other';

    let actionsHtml = '<div class="plan-actions">';

    if (plan.document_url) {
      if (plan.embed_type === 'pdf') {
        actionsHtml += `<button onclick="event.stopPropagation(); openDocViewer('${escAttr(plan.document_url)}', '${escAttr(plan.name)}', 'pdf')" class="plan-action-btn primary">📄 צפייה בתוכנית</button>`;
      } else if (plan.embed_type === 'image') {
        actionsHtml += `<button onclick="event.stopPropagation(); openDocViewer('${escAttr(plan.document_url)}', '${escAttr(plan.name)}', 'image')" class="plan-action-btn primary">🖼️ צפייה בתוכנית</button>`;
      } else if (plan.embed_type === 'iframe') {
        actionsHtml += `<button onclick="event.stopPropagation(); openDocViewer('${escAttr(plan.document_url)}', '${escAttr(plan.name)}', 'iframe')" class="plan-action-btn primary">📋 צפייה בתוכנית</button>`;
      } else {
        actionsHtml += `<a href="${esc(plan.document_url)}" target="_blank" class="plan-action-btn primary" onclick="event.stopPropagation()">📄 צפייה בתוכנית</a>`;
      }
    }

    if (plan.source_url && plan.source_url !== plan.document_url) {
      actionsHtml += `<a href="${esc(plan.source_url)}" target="_blank" class="plan-action-btn secondary" onclick="event.stopPropagation()">🔗 קישור למקור</a>`;
    }

    if (plan.document_url) {
      actionsHtml += `<a href="${esc(plan.document_url)}" target="_blank" class="plan-action-btn secondary" onclick="event.stopPropagation()">↗ פתח בחלון חדש</a>`;
    }

    actionsHtml += '</div>';

    let previewHtml = '';
    if (plan.embed_type === 'image' && plan.thumbnail_url) {
      previewHtml = `<div class="plan-preview"><img src="${esc(plan.thumbnail_url)}" alt="${esc(plan.name)}" onclick="event.stopPropagation(); openDocViewer('${escAttr(plan.document_url)}', '${escAttr(plan.name)}', 'image')"></div>`;
    }

    card.innerHTML = `
      <div class="plan-header" onclick="this.parentElement.classList.toggle('expanded')">
        <span class="plan-arrow">◀</span>
        <span class="plan-name">${esc(plan.name)}</span>
        <span class="badge ${badgeClass}">${esc(plan.source)}</span>
        <span class="${typeClass}" style="font-size:0.75rem;font-weight:600">${esc(plan.plan_type)}</span>
      </div>
      <div class="plan-details">
        <p><strong>סטטוס:</strong> ${esc(plan.status)}</p>
        ${plan.date ? `<p><strong>תאריך:</strong> ${esc(plan.date)}</p>` : ''}
        ${actionsHtml}
        ${previewHtml}
      </div>
    `;
    list.appendChild(card);
  });
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

function escAttr(str) {
  return (str || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// ─── Document Viewer ───
function openDocViewer(url, title, type) {
  const viewer = document.getElementById('doc-viewer');
  const body = document.getElementById('doc-viewer-body');
  const titleEl = document.getElementById('doc-viewer-title');
  const extLink = document.getElementById('doc-viewer-external');

  titleEl.textContent = title;
  extLink.href = url;

  if (type === 'pdf') {
    body.innerHTML = `<iframe src="${esc(url)}" title="${esc(title)}"></iframe>`;
  } else if (type === 'image') {
    body.innerHTML = `<img src="${esc(url)}" alt="${esc(title)}" style="padding: 1rem;">`;
  } else {
    body.innerHTML = `<iframe src="${esc(url)}" title="${esc(title)}" sandbox="allow-scripts allow-same-origin allow-popups allow-forms"></iframe>`;
  }

  viewer.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeDocViewer() {
  const viewer = document.getElementById('doc-viewer');
  const body = document.getElementById('doc-viewer-body');
  body.innerHTML = '';
  viewer.classList.add('hidden');
  document.body.style.overflow = '';
}

// ─── Lightbox ───
function openLightbox(index) {
  if (!currentImages.length) return;
  lightboxIndex = index;
  updateLightbox();
  document.getElementById('lightbox').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  document.getElementById('lightbox').classList.add('hidden');
  document.body.style.overflow = '';
}

function lbNav(delta) {
  if (!currentImages.length) return;
  lightboxIndex = (lightboxIndex + delta + currentImages.length) % currentImages.length;
  updateLightbox();
}

function updateLightbox() {
  const img = currentImages[lightboxIndex];
  if (!img) return;
  const lbImg = document.getElementById('lb-image');
  lbImg.src = img.url || img.thumbnail_url;
  document.getElementById('lb-info').textContent =
    `${img.source} | ${img.date || ''} | ${lightboxIndex + 1}/${currentImages.length}`;
}

// Keyboard navigation
document.addEventListener('keydown', (e) => {
  if (!document.getElementById('doc-viewer').classList.contains('hidden')) {
    if (e.key === 'Escape') closeDocViewer();
    return;
  }
  if (!document.getElementById('lightbox').classList.contains('hidden')) {
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') lbNav(1);
    if (e.key === 'ArrowRight') lbNav(-1);
  }
});

// ─── Init on load ───
window.addEventListener('load', async () => {
  loadSupportedCities();

  // Pre-warm city cache
  fetchCities('');

  const q = getQueryParam();
  if (q) {
    freeForm.classList.remove('hidden');
    smartForm.classList.add('hidden');
    freeInput.value = q;
    doSearch(q);
  }
});
