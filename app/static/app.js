/* Israel Building Plans Finder - Frontend JS */

const form = document.getElementById('search-form');
const input = document.getElementById('address-input');
const searchBtn = document.getElementById('search-btn');
const loading = document.getElementById('loading');
const errorSection = document.getElementById('error-section');
const errorMessage = document.getElementById('error-message');
const results = document.getElementById('results');

let currentImages = [];
let lightboxIndex = 0;

// Source badge colour mapping
const SOURCE_BADGES = {
  'ארכיון הנדסה ת"א': 'badge-teal',
  'XPLAN (תכניות ארציות)': 'badge-indigo',
  'מבא"ת (מידע תכנוני)': 'badge-purple',
  'Mapillary': 'badge-green',
  'Google Street View': 'badge-orange',
};

// Plan type styling
const TYPE_CLASSES = {
  'היתר': 'type-permit',
  'תב"ע': 'type-plan',
  'תעודת גמר': 'type-completion',
  'אחר': 'type-other',
};

// ─── URL deep-linking ───
function getQueryParam() {
  const params = new URLSearchParams(window.location.search);
  return params.get('q') || '';
}

function setQueryParam(q) {
  const url = new URL(window.location);
  url.searchParams.set('q', q);
  history.pushState({}, '', url);
}

// ─── Search ───
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q) return;
  setQueryParam(q);
  await doSearch(q);
});

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

  // Address info
  const geo = data.geocode;
  document.getElementById('result-address').textContent = geo.display_name;
  document.getElementById('result-coords').textContent = `נ.צ: ${geo.lat.toFixed(5)}, ${geo.lon.toFixed(5)}`;

  // Cache badge
  const cacheBadge = document.getElementById('cache-badge');
  if (data.from_cache) {
    cacheBadge.classList.remove('hidden');
  } else {
    cacheBadge.classList.add('hidden');
  }

  // Copy link
  document.getElementById('copy-link').onclick = () => {
    navigator.clipboard.writeText(window.location.href);
    document.getElementById('copy-link').textContent = '✓ הועתק!';
    setTimeout(() => {
      document.getElementById('copy-link').textContent = '🔗 העתק קישור';
    }, 2000);
  };

  // Images
  renderImages(data.images);

  // Plans
  renderPlans(data.plans);

  // Map
  const mapFrame = document.getElementById('map-iframe');
  mapFrame.src = `https://www.openstreetmap.org/export/embed.html?bbox=${geo.lon - 0.003},${geo.lat - 0.002},${geo.lon + 0.003},${geo.lat + 0.002}&layer=mapnik&marker=${geo.lat},${geo.lon}`;

  // Sources
  document.getElementById('sources-tried').textContent = data.sources_tried.join(', ');
}

function renderImages(images) {
  const grid = document.getElementById('images-grid');
  const noImages = document.getElementById('no-images');
  const count = document.getElementById('images-count');
  grid.innerHTML = '';
  currentImages = images;

  if (!images.length) {
    grid.classList.add('hidden');
    noImages.classList.remove('hidden');
    count.textContent = '';
    return;
  }

  grid.classList.remove('hidden');
  noImages.classList.add('hidden');
  count.textContent = `(${images.length})`;

  images.forEach((img, i) => {
    const card = document.createElement('div');
    card.className = 'image-card';
    card.onclick = () => openLightbox(i);

    const imgEl = document.createElement('img');
    imgEl.src = img.thumbnail_url || img.url;
    imgEl.alt = `Street view - ${img.source}`;
    imgEl.loading = 'lazy';
    card.appendChild(imgEl);

    const badge = document.createElement('div');
    badge.className = 'image-badge';
    badge.textContent = `${img.source}${img.date ? ' · ' + img.date : ''}`;
    card.appendChild(badge);

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

  plans.forEach((plan) => {
    const card = document.createElement('div');
    card.className = 'plan-card';

    const badgeClass = SOURCE_BADGES[plan.source] || 'badge-gray';
    const typeClass = TYPE_CLASSES[plan.plan_type] || 'type-other';

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
        <div style="margin-top:0.5rem;display:flex;gap:0.75rem">
          ${plan.document_url ? `<a href="${esc(plan.document_url)}" target="_blank" class="text-blue-600 hover:underline text-sm">📄 צפייה בתוכנית</a>` : ''}
          ${plan.source_url ? `<a href="${esc(plan.source_url)}" target="_blank" class="text-blue-600 hover:underline text-sm">🔗 קישור למקור</a>` : ''}
        </div>
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

// ─── Lightbox ───
function openLightbox(index) {
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
  lightboxIndex = (lightboxIndex + delta + currentImages.length) % currentImages.length;
  updateLightbox();
}

function updateLightbox() {
  const img = currentImages[lightboxIndex];
  document.getElementById('lb-image').src = img.thumbnail_url || img.url;
  document.getElementById('lb-info').textContent =
    `${img.source} | ${img.date || ''} | ${lightboxIndex + 1}/${currentImages.length}`;
}

// Keyboard navigation
document.addEventListener('keydown', (e) => {
  if (document.getElementById('lightbox').classList.contains('hidden')) return;
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowLeft') lbNav(1);
  if (e.key === 'ArrowRight') lbNav(-1);
});

// ─── Deep link on load ───
window.addEventListener('load', () => {
  const q = getQueryParam();
  if (q) {
    input.value = q;
    doSearch(q);
  }
});
