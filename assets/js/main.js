/* ===== 우아차저 — main.js (검색 + 내 위치 근처) ===== */

let stations = [];
let fuse = null;

function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371000, toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1), dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function fmtDist(m) {
  return m < 1000 ? `${Math.round(m)}m` : `${(m / 1000).toFixed(1)}km`;
}

function stationCard(s, distMeters) {
  return `<a href="/charger/${s.slug}/" class="charger-card">
    <div class="charger-card-header">
      <span class="charger-card-name">${s.name}</span>
      ${distMeters != null ? `<span class="tag tag-dist">${fmtDist(distMeters)}</span>` : ''}
    </div>
    <p class="charger-card-addr">📍 ${s.address}</p>
    <div class="charger-card-types">
      ${s.fast_count ? `<span class="tag tag-fast">급속 ${s.fast_count}대</span>` : ''}
      ${s.slow_count ? `<span class="tag tag-slow">완속 ${s.slow_count}대</span>` : ''}
      <span class="tag tag-avail">사용가능 ${s.available_count}</span>
    </div>
  </a>`;
}

async function init() {
  try {
    const res = await fetch('/search_index.json');
    stations = await res.json();
  } catch (e) { return; }

  fuse = new Fuse(stations, {
    keys: ['name', 'sido', 'sigungu', 'address'],
    threshold: 0.35,
    minMatchCharLength: 1,
  });

  const searchBox = document.getElementById('searchBox');
  const searchResults = document.getElementById('searchResults');

  searchBox.addEventListener('input', function () {
    const q = this.value.trim();
    if (!q) { searchResults.classList.remove('active'); return; }
    const results = fuse.search(q).slice(0, 12);
    searchResults.innerHTML = results.length === 0
      ? '<div class="no-result">검색 결과가 없습니다.</div>'
      : results.map(r => stationCard(r.item)).join('');
    searchResults.classList.add('active');
  });

  document.getElementById('nearMeBtn').addEventListener('click', () => {
    if (!navigator.geolocation) { alert('이 브라우저는 위치 정보를 지원하지 않습니다.'); return; }
    navigator.geolocation.getCurrentPosition(
      pos => showNearby(pos.coords.latitude, pos.coords.longitude),
      () => alert('위치 정보를 가져올 수 없습니다. 브라우저 위치 권한을 확인해주세요.')
    );
  });

  renderRecentChargers();
}

function renderRecentChargers() {
  const el = document.getElementById('recentChargers');
  if (!el) return;
  const sample = stations.slice(0, 8);
  el.innerHTML = sample.length
    ? sample.map(s => stationCard(s)).join('')
    : '<p class="loading-text">등록된 충전소가 없습니다.</p>';
}

function showNearby(lat, lon) {
  const withDist = stations
    .filter(s => s.lat && s.lon)
    .map(s => ({ ...s, dist: haversine(lat, lon, s.lat, s.lon) }))
    .sort((a, b) => a.dist - b.dist)
    .slice(0, 10);

  const wrap = document.getElementById('nearMeResults');
  wrap.style.display = 'block';
  wrap.innerHTML = `<h2>📍 내 위치 근처 충전소</h2>` +
    (withDist.length === 0
      ? '<p>주변에 등록된 충전소가 없습니다.</p>'
      : `<div class="charger-list">${withDist.map(s => stationCard(s, s.dist)).join('')}</div>`);
  wrap.scrollIntoView({ behavior: 'smooth' });
}

document.addEventListener('DOMContentLoaded', init);
