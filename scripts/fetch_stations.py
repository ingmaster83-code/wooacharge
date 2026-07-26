"""
fetch_stations.py - 한국환경공단 전기차 충전소 정보 API 수집 (여러 날에 걸쳐 이어받기)
결과를 _rawdata/stations.json으로 저장

API: https://www.data.go.kr/data/15076352/openapi.do (한국환경공단_전기자동차 충전소 정보)
  OpenAPI 활용가이드 v1.23 기준 필드명 반영
  - getChargerInfo : 충전소/충전기 기본 정보 (충전기 단위 레코드, statId+chgerId로 station 그룹핑)

  실시간 상태(getChargerStatus)는 여기서 전국 단위로 긁지 않는다 — 상세페이지 방문 시
  Cloudflare Worker가 "지금 보는 충전소" 하나만 그때그때 조회한다 (assets/js/charger-status.js).
  여기서는 상태를 "상태미확인"으로 기본값 채워두고, 페이지 방문 시 실시간 값으로 교체된다.

  하루 호출 한도(quota)가 전국 전체를 한 번에 받기엔 부족해서(과거 페이지 1000에서 429 발생),
  체크포인트(_rawdata/_fetch_progress.json)에 진행 상황을 저장하고 다음 실행에 이어받는다.
  끝까지 다 받으면 그때 stations.json을 교체하고 체크포인트를 지운다.

사용법:
  set EV_API_KEY=발급받은서비스키
  python scripts/fetch_stations.py
  python scripts/fetch_stations.py --limit 100   # 테스트용 (체크포인트 무시하고 소량만)
"""
import json
import os
import re
import sys
import time
import argparse
from pathlib import Path
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.stdout.reconfigure(encoding="utf-8")

API_KEY  = os.environ.get("EV_API_KEY", "")
BASE_URL = "https://apis.data.go.kr/B552584/EvCharger"
INFO_URL = f"{BASE_URL}/getChargerInfo"

SCRIPT_DIR = Path(__file__).parent
OUT_DIR  = SCRIPT_DIR.parent / "_rawdata"
OUT_FILE = OUT_DIR / "stations.json"
PROGRESS_FILE = OUT_DIR / "_fetch_progress.json"

BATCH = 100
DELAY = 0.5
# 하루 호출 한도를 넘기지 않도록, 한 번 실행에서 가져올 페이지 수를 안전하게 제한
# (과거 로그상 페이지 1000 부근에서 429가 났으므로 여유를 크게 둔다)
MAX_PAGES_PER_RUN = 600

ZCODE_MAP  = json.loads((SCRIPT_DIR / "zcode.json").read_text(encoding="utf-8"))
ZSCODE_MAP = json.loads((SCRIPT_DIR / "zscode.json").read_text(encoding="utf-8"))

# chgerType(충전기 타입) 코드 중 "완속"이 명시된 코드만 완속, 나머지는 급속
# 02: AC완속, 08: DC콤보(완속) — OpenAPI 활용가이드 v1.23 공통코드 기준
SLOW_CHARGER_TYPES = {"02", "08"}

# stat(충전기 상태) 공통코드 — 실시간 상태는 상세페이지에서 그때그때 받아오므로
# 여기서는 항상 기본값만 채운다.
DEFAULT_STATUS = ("상태미확인", "unknown")


def fetch_page(url: str, page: int, extra_params: dict = None):
    """한 페이지 요청. 실패하면 재시도 후 그래도 안 되면 None 반환(예외 아님)."""
    params = {
        "serviceKey": API_KEY,
        "pageNo": page,
        "numOfRows": BATCH,
        "dataType": "JSON",
    }
    if extra_params:
        params.update(extra_params)

    retry = 0
    max_retry = 5
    while retry < max_retry:
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            page_items = data.get("items", {})
            if isinstance(page_items, dict):
                page_items = page_items.get("item", [])
            if isinstance(page_items, dict):
                page_items = [page_items]
            return page_items
        except Exception as e:
            retry += 1
            wait = min(DELAY * (3 ** retry), 60)
            print(f"  [재시도 {retry}/{max_retry}] page={page}: {e} → {wait:.0f}초 대기")
            time.sleep(wait)

    return None


def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"next_page": 1, "items": []}


def save_progress(next_page: int, items: list):
    PROGRESS_FILE.write_text(
        json.dumps({"next_page": next_page, "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )


def clear_progress():
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()


def fetch_incremental(url: str, limit: int = 0, use_checkpoint: bool = True):
    """체크포인트부터 이어서 수집 (use_checkpoint=False면 매번 1페이지부터, 저장도 안 함 — 테스트용).
    반환값: (items, finished) — finished=True면 마지막 페이지까지 다 받은 것.
    할당량 소진 등으로 막히면 지금까지 모은 것 + finished=False 로 조용히 멈춘다."""
    if use_checkpoint:
        progress = load_progress()
        items = progress["items"]
        page = progress["next_page"]
    else:
        items = []
        page = 1
    start_page = page
    pages_this_run = 0

    while True:
        if limit and len(items) >= limit:
            return items[:limit], True

        page_items = fetch_page(url, page)
        if page_items is None:
            print(f"  [중단] page={page} 에서 반복 실패 — 지금까지 {len(items)}건, 다음 실행에 이어받음")
            if use_checkpoint:
                save_progress(page, items)
            return items, False

        if not page_items:
            print(f"  → page {page}에서 데이터 끝. 이번 구간 총 {len(items)}건 수집 완료")
            return items, True

        items.extend(page_items)
        pages_this_run += 1
        print(f"  page {page:4d} | 누적 {len(items):6d}건")

        if len(page_items) < BATCH:
            print(f"  → 마지막 페이지 도달. 총 {len(items)}건 수집 완료")
            return items, True

        page += 1

        if pages_this_run >= MAX_PAGES_PER_RUN:
            print(f"  [일시중지] 이번 실행 한도({MAX_PAGES_PER_RUN}페이지) 도달 — "
                  f"{start_page}~{page - 1}페이지 완료, 다음 실행에 {page}페이지부터 이어받음")
            if use_checkpoint:
                save_progress(page, items)
            return items, False

        time.sleep(DELAY)


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s가-힣]", "", str(text))
    text = re.sub(r"\s+", "-", text.strip())
    return text[:40].strip("-").lower()


def build_stations(info_items: list) -> list:
    """충전소 ID 기준으로 충전기 정보를 묶어 station 레코드 생성.
    실시간 상태는 상세페이지 방문 시 별도로 받아오므로 여기서는 기본값만 채운다.
    삭제된 충전기(delYn=Y)는 제외한다."""
    stations = {}
    for it in info_items:
        if it.get("delYn") == "Y":
            continue

        stat_id = it.get("statId")
        if not stat_id:
            continue

        if stat_id not in stations:
            zcode = str(it.get("zcode", ""))
            zscode = str(it.get("zscode", ""))
            sido = ZCODE_MAP.get(zcode, "")
            sigungu = ZSCODE_MAP.get(zscode, "")
            if not sido:
                # 코드표에 없는 zcode (신규 행정구역 등) — 주소 텍스트에서 최대한 복구
                tokens = (it.get("addr") or "").split()
                sido = tokens[0] if tokens else ""
                if not sigungu and len(tokens) > 1:
                    sigungu = tokens[1]

            floor_type = it.get("floorType", "")
            floor_num = it.get("floorNum", "")
            floor_label = ""
            if floor_num:
                floor_label = f"{'지하' if floor_type == 'B' else '지상'} {floor_num}층"

            addr = it.get("addr", "")
            addr_detail = it.get("addrDetail", "") or ""
            if addr_detail.strip().lower() == "null":
                addr_detail = ""
            full_addr = f"{addr} {addr_detail}".strip() if addr_detail else addr

            stations[stat_id] = {
                "id": stat_id,
                "slug": f"{slugify(it.get('statNm',''))}-{stat_id}",
                "name": it.get("statNm", ""),
                "sido": sido,
                "sigungu": sigungu,
                "address": full_addr,
                "floor": floor_label,
                "operator": it.get("busiNm") or it.get("bnm", ""),
                "tel": it.get("busiCall", ""),
                "hours": it.get("useTime", "") or "24시간",
                "parking_free": it.get("parkingFree") == "Y",
                "restricted": it.get("limitYn") == "Y",
                "restrict_detail": it.get("limitDetail", ""),
                "note": it.get("note", ""),
                "install_year": it.get("year", ""),
                "lat": it.get("lat"),
                "lon": it.get("lng"),
                "chargers": [],
                "last_updated": "",
            }

        chger_type = str(it.get("chgerType", ""))
        speed = "완속" if chger_type in SLOW_CHARGER_TYPES else "급속"
        status_text, status_class = DEFAULT_STATUS

        stations[stat_id]["chargers"].append({
            "charger_id": it.get("chgerId"),
            "speed": speed,
            "capacity": it.get("output", ""),
            "status_text": status_text,
            "status_class": status_class,
        })

    return list(stations.values())


def main():
    parser = argparse.ArgumentParser(description="전기차 충전소 API 수집 (이어받기)")
    parser.add_argument("--limit", type=int, default=0, help="테스트용 건수 제한 (0=전체, 체크포인트 무시)")
    args = parser.parse_args()

    if not API_KEY:
        raise SystemExit(
            "EV_API_KEY 환경변수가 설정되지 않았습니다. "
            "공공데이터포털에서 '한국환경공단_전기자동차 충전소 정보' 활용신청 후 발급받은 서비스키를 설정하세요."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.limit:
        # 테스트 모드: 체크포인트 없이 소량만 받고 끝낸다
        info_items, finished = fetch_incremental(INFO_URL, limit=args.limit, use_checkpoint=False)
    else:
        print("[정보 수집] (체크포인트에서 이어받기)")
        info_items, finished = fetch_incremental(INFO_URL)

    if not finished:
        print(f"\n[일시중지] 이번 실행에서 {len(info_items)}건까지 모았고, 아직 끝까지 못 받았습니다.")
        print("  체크포인트에 저장해뒀으니 다음 실행(내일 새벽)에 이어서 받습니다. 기존 stations.json은 그대로 둡니다.")
        return

    print(f"\n[완주] 전체 수집 완료: {len(info_items)}건")
    print("[병합] 데이터 병합 중...")
    stations = build_stations(info_items)
    print(f"  → 충전소 {len(stations)}개로 병합 완료")

    # 안전장치: 기존 데이터의 절반 미만이면 저장 중단 (API 오류로 인한 데이터 유실 방지)
    if OUT_FILE.exists():
        existing = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        if len(stations) < len(existing) * 0.5:
            raise SystemExit(
                f"수집 건수({len(stations)}건)가 기존 데이터({len(existing)}건)의 절반 미만입니다. "
                "API 오류로 판단하여 저장을 중단합니다. (체크포인트는 초기화하지 않음 — 다음에 재시도)"
            )

    OUT_FILE.write_text(
        json.dumps(stations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    clear_progress()
    print(f"\n[완료] {OUT_FILE}")
    print(f"  총 {len(stations)}개 충전소 저장 (다음 실행부터 새 수집 사이클 시작)")


if __name__ == "__main__":
    main()
