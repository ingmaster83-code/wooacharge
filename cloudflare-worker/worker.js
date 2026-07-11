/**
 * Cloudflare Worker - 공공데이터포털 CORS 프록시
 * 배포 후 URL: https://wooacharge-proxy.ingmaster83.workers.dev
 *
 * 허용 오리진: wooacharge.wooahouse.com
 * 충전소 상세페이지에서 "지금 보고 있는 충전소"의 실시간 상태만 조회할 때 사용
 * (전국 데이터를 주기적으로 통째로 갱신하지 않고, 조회 시점에만 필요한 만큼만 호출)
 *
 * serviceKey는 클라이언트에서 절대 보내지 않는다 — 이 Worker의 환경변수(Secret)
 * EV_SERVICE_KEY에서 서버 쪽에서만 읽어서 붙인다.
 * 배포 시: wrangler secret put EV_SERVICE_KEY
 * (또는 Cloudflare 대시보드 > Workers > 이 Worker > Settings > Variables에서
 *  "EV_SERVICE_KEY"를 Encrypted 로 추가)
 */

const ALLOWED_ORIGIN = 'https://wooacharge.wooahouse.com';
const TARGET_BASE    = 'https://apis.data.go.kr';

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: corsHeaders(origin),
      });
    }

    const url = new URL(request.url);

    // /B552584/EvCharger/** 경로만 허용
    if (!url.pathname.startsWith('/B552584/EvCharger/')) {
      return new Response('Not allowed', { status: 403 });
    }

    if (!env.EV_SERVICE_KEY) {
      return new Response(JSON.stringify({ error: 'EV_SERVICE_KEY not configured' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
      });
    }

    // 클라이언트가 실수로/의도적으로 serviceKey를 보내도 무시하고 서버 키로 덮어씀
    const targetParams = new URLSearchParams(url.search);
    targetParams.set('serviceKey', env.EV_SERVICE_KEY);
    const target = `${TARGET_BASE}${url.pathname}?${targetParams.toString()}`;

    try {
      const res = await fetch(target, {
        headers: { 'Accept': 'application/json' },
      });
      const body = await res.text();
      return new Response(body, {
        status: res.status,
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          ...corsHeaders(origin),
        },
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 502,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
      });
    }
  },
};

function corsHeaders(origin) {
  const allowed = origin === ALLOWED_ORIGIN || origin === 'http://localhost:4002';
  return {
    'Access-Control-Allow-Origin':  allowed ? origin : ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}
