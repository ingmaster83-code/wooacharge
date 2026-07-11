"""
fetch_stations.py - 한국환경공단 전기차 충전소 정보 API 전체 수집
결과를 _rawdata/stations.json으로 저장

API: https://www.data.go.kr/data/15076352/openapi.do (한국환경공단_전기자동차 충전소 정보)
  - getChargerInfo   : 충전소/충전기 기본 정보
  - getChargerStatus : 충전기 실시간 상태

사용법:
  set EV_API_KEY=발급받은서비스키
  python scripts/fetch_stations.py
  python scripts/fetch_stations.py --limit 100   # 테스트용
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
BASE_URL = "http://apis.data.go.kr/B552584/EvCharger"
INFO_URL = f"{BASE_URL}/getChargerInfo"
STATUS_URL = f"{BASE_URL}/getChargerStatus"

OUT_DIR  = Path(__file__).parent.parent / "_rawdata"
OUT_FILE = OUT_DIR / "stations.json"

BATCH = 100
DELAY = 0.3


def fetch_all(url: str, extra_params: dict = None) -> list:
    """페이지네이션으로 전체 데이터 수집"""
    items = []
    page = 1
    while True:
        params = {
            "serviceKey": API_KEY,
            "pageNo": page,
            "numOfRows": BATCH,
            "dataType": "JSON",
        }
        if extra_params:
            params.update(extra_params)

        retry = 0
        data = None
        while retry < 5:
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                retry += 1
                wait = DELAY * (3 ** retry)
                print(f"  [재시도 {retry}/5] page={page}: {e} → {wait:.0f}초 대기")
                time.sleep(wait)

        if data is None:
            print(f"  [포기] page={page}")
            break

        body = data.get("items", {})
        page_items = body.get("item", []) if isinstance(body, dict) else []
        if isinstance(page_items, dict):
            page_items = [page_items]

        if not page_items:
            break

        items.extend(page_items)
        print(f"  page {page:3d} | 수집 {len(items):5d}건")

        if len(page_items) < BATCH:
            break
        page += 1
        time.sleep(DELAY)

    return items


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s가-힣]", "", str(text))
    text = re.sub(r"\s+", "-", text.strip())
    return text[:40].strip("-").lower()


def parse_sido_sigungu(addr: str):
    """주소 문자열에서 시도/시군구 추출 (간단 파싱, 필요시 정교화)"""
    if not addr:
        return "", ""
    tokens = addr.split()
    sido = tokens[0] if tokens else ""
    sigungu = tokens[1] if len(tokens) > 1 else ""
    return sido, sigungu


def build_stations(info_items: list, status_items: list) -> list:
    """충전소 ID 기준으로 충전기 정보 + 실시간 상태를 합쳐 station 레코드 생성"""
    status_by_charger = {
        f"{s.get('statId')}_{s.get('chgerId')}": s for s in status_items
    }

    stations = {}
    for it in info_items:
        stat_id = it.get("statId")
        if not stat_id:
            continue
        if stat_id not in stations:
            sido, sigungu = parse_sido_sigungu(it.get("addr", ""))
            stations[stat_id] = {
                "id": stat_id,
                "slug": f"{slugify(it.get('statNm',''))}-{stat_id}",
                "name": it.get("statNm", ""),
                "sido": sido,
                "sigungu": sigungu,
                "address": it.get("addr", ""),
                "floor": it.get("floor", "") or "",
                "operator": it.get("bnm", ""),
                "tel": it.get("busiCall", ""),
                "hours": it.get("useTime", "") or "24시간",
                "parking_free": it.get("parkingFree") == "Y",
                "restricted": it.get("limitYn") == "Y",
                "lat": it.get("lat"),
                "lon": it.get("lng"),
                "chargers": [],
                "last_updated": "",
            }

        status_key = f"{stat_id}_{it.get('chgerId')}"
        status = status_by_charger.get(status_key, {})
        stat_code = status.get("stat", "9")
        status_map = {
            "2": ("충전가능", "avail"),
            "3": ("충전중", "busy"),
            "4": ("운영중지", "unknown"),
            "5": ("점검중", "unknown"),
        }
        status_text, status_class = status_map.get(str(stat_code), ("상태미확인", "unknown"))

        speed = "급속" if str(it.get("chgerType", "")) in ("01", "02", "06", "07") else "완속"

        stations[stat_id]["chargers"].append({
            "charger_id": it.get("chgerId"),
            "speed": speed,
            "capacity": it.get("output", ""),
            "status_text": status_text,
            "status_class": status_class,
        })
        if status.get("statUpdDt"):
            stations[stat_id]["last_updated"] = status["statUpdDt"]

    return list(stations.values())


def main():
    parser = argparse.ArgumentParser(description="전기차 충전소 API 전체 수집")
    parser.add_argument("--limit", type=int, default=0, help="테스트용 건수 제한 (0=전체)")
    args = parser.parse_args()

    if not API_KEY:
        raise SystemExit(
            "EV_API_KEY 환경변수가 설정되지 않았습니다. "
            "공공데이터포털에서 '한국환경공단_전기자동차 충전소 정보' 활용신청 후 발급받은 서비스키를 설정하세요."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[Step 1] 충전소 기본정보 수집 중...")
    info_items = fetch_all(INFO_URL)
    if args.limit:
        info_items = info_items[: args.limit]
    print(f"  → 총 {len(info_items)}건 수집 완료\n")

    print("[Step 2] 실시간 충전기 상태 수집 중...")
    status_items = fetch_all(STATUS_URL)
    print(f"  → 총 {len(status_items)}건 수집 완료\n")

    print("[Step 3] 데이터 병합 중...")
    stations = build_stations(info_items, status_items)
    print(f"  → 충전소 {len(stations)}개로 병합 완료")

    # 안전장치: 기존 데이터의 절반 미만이면 저장 중단 (API 오류로 인한 데이터 유실 방지)
    if OUT_FILE.exists():
        existing = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        if len(stations) < len(existing) * 0.5:
            raise SystemExit(
                f"수집 건수({len(stations)}건)가 기존 데이터({len(existing)}건)의 절반 미만입니다. "
                "API 오류로 판단하여 저장을 중단합니다."
            )

    OUT_FILE.write_text(
        json.dumps(stations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[완료] {OUT_FILE}")
    print(f"  총 {len(stations)}개 충전소 저장")


if __name__ == "__main__":
    main()
