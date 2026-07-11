/* ===== 우아차저 — charger-status.js =====
 * 충전소 상세페이지 전용: 지금 보고 있는 충전소 하나의 실시간 상태만 조회.
 * 전국 데이터를 주기적으로 갱신하지 않고, 페이지를 열 때마다 그 순간의 상태를 받아온다.
 * 서버 페이지(SSR)에 있는 값은 마지막 수집 시점 기준이라 다소 오래됐을 수 있고,
 * 이 스크립트가 로드되면 즉시 최신 값으로 교체한다.
 */

const PROXY_BASE = 'https://wooacharge-proxy.ingmaster83.workers.dev/B552584/EvCharger';
// serviceKey는 여기 없음 — Worker가 서버 쪽 Secret에서 읽어서 붙인다 (cloudflare-worker/worker.js 참고)

const STATUS_MAP = {
  '0': ['상태미확인', 'unknown'],
  '1': ['통신이상', 'unknown'],
  '2': ['충전가능', 'avail'],
  '3': ['충전중', 'busy'],
  '4': ['운영중지', 'unknown'],
  '5': ['점검중', 'unknown'],
  '6': ['예약중', 'busy'],
  '9': ['상태미확인', 'unknown'],
};

function fmtUpdatedAt(raw) {
  // YYYYMMDDHHMMSS -> YYYY-MM-DD HH:MM
  if (!raw || raw.length < 12) return raw || '정보 없음';
  return `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6,8)} ${raw.slice(8,10)}:${raw.slice(10,12)}`;
}

async function loadLiveStatus() {
  if (!STATION_ID) return;

  const url = `${PROXY_BASE}/getChargerStatus?statId=${encodeURIComponent(STATION_ID)}&pageNo=1&numOfRows=50&dataType=JSON`;

  let items;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('bad response');
    const data = await res.json();
    items = data.items && data.items.item ? data.items.item : [];
    if (!Array.isArray(items)) items = [items];
  } catch (e) {
    return; // 실패하면 SSR에 있던 값(마지막 수집 시점 기준)을 그대로 둔다
  }

  if (!items.length) return;

  let latestUpdate = '';
  items.forEach(it => {
    const unit = document.querySelector(`.charger-unit[data-charger-id="${it.chgerId}"]`);
    if (!unit) return;
    const [text, cls] = STATUS_MAP[String(it.stat)] || ['상태미확인', 'unknown'];
    const statusEl = unit.querySelector('.unit-status');
    statusEl.textContent = text;
    statusEl.className = `unit-status status-${cls}`;
    if (it.statUpdDt && it.statUpdDt > latestUpdate) latestUpdate = it.statUpdDt;
  });

  if (latestUpdate) {
    document.getElementById('lastUpdated').textContent = `마지막 갱신: ${fmtUpdatedAt(latestUpdate)}`;
  }
  const badge = document.getElementById('liveBadge');
  if (badge) badge.style.display = 'inline';
}

// 스크립트가 </body> 직전에 위치해 DOM은 이미 준비된 상태이므로 즉시 실행.
// (DOMContentLoaded는 이 시점엔 이미 지나갔을 수 있어 리스너가 안 불릴 수 있음)
loadLiveStatus();
