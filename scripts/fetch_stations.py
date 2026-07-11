"""
fetch_stations.py - 한국환경공단 전기차 충전소 정보 API 전체 수집
결과를 _rawdata/stations.json으로 저장

API: https://www.data.go.kr/data/15076352/openapi.do (한국환경공단_전기자동차 충전소 정보)
  OpenAPI 활용가이드 v1.23 기준 필드명 반영
  - getChargerInfo   : 충전소/충전기 기본 정보 (충전기 단위 레코드, statId+chgerId로 station 그룹핑)
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
BASE_URL = "https://apis.data.go.kr/B552584/EvCharger"
INFO_URL = f"{BASE_URL}/getChargerInfo"
STATUS_URL = f"{BASE_URL}/getChargerStatus"

SCRIPT_DIR = Path(__file__).parent
OUT_DIR  = SCRIPT_DIR.parent / "_rawdata"
OUT_FILE = OUT_DIR / "stations.json"

BATCH = 100
DELAY = 0.3

ZCODE_MAP  = json.loads((SCRIPT_DIR / "zcode.json").read_text(encoding="utf-8"))
ZSCODE_MAP = json.loads((SCRIPT_DIR / "zscode.json").read_text(encoding="utf-8"))

# chgerType(충전기 타입) 코드 중 "완속"이 명시된 코드만 완속, 나머지는 급속
# 02: AC완속, 08: DC콤보(완속) — OpenAPI 활용가이드 v1.23 공통코드 기준
SLOW_CHARGER_TYPES = {"02", "08"}

# stat(충전기 상태) 공통코드 (활용가이드 v1.23 기준)
STATUS_MAP = {
    "0": ("상태미확인", "unknown"),   # 알수없음
    "1": ("통신이상", "unknown"),
    "2": ("충전가능", "avail"),       # 충전대기
    "3": ("충전중", "busy"),
    "4": ("운영중지", "unknown"),
    "5": ("점검중", "unknown"),
    "6": ("예약중", "busy"),
    "9": ("상태미확인", "unknown"),
}


def fetch_all(url: str, extra_params: dict = None, limit: int = 0) -> list:
    """페이지네이션으로 전체 데이터 수집. limit>0이면 해당 건수 도달 시 조기 종료(테스트용)."""
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
        max_retry = 8
        while retry < max_retry:
            try:
                resp = requests.get(url, params=params, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                retry += 1
                wait = min(DELAY * (3 ** retry), 60)
                print(f"  [재시도 {retry}/{max_retry}] page={page}: {e} → {wait:.0f}초 대기")
                time.sleep(wait)

        if data is None:
            # 재시도를 다 소진하고도 실패 — 부분 데이터를 완료로 착각하지 않도록 예외로 처리
            raise RuntimeError(f"{url} page={page} 에서 {max_retry}회 재시도 후에도 실패했습니다. (지금까지 수집: {len(items)}건)")

        # 활용가이드 JSON 예제 기준: response/header/body 래핑 없이 최상위에 items 존재
        page_items = data.get("items", {})
        if isinstance(page_items, dict):
            page_items = page_items.get("item", [])
        if isinstance(page_items, dict):
            page_items = [page_items]
        if not page_items:
            break

        items.extend(page_items)
        print(f"  page {page:3d} | 수집 {len(items):5d}건")

        if limit and len(items) >= limit:
            items = items[:limit]
            break
        if len(page_items) < BATCH:
            break
        page += 1
        time.sleep(DELAY)

    return items


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s가-힣]", "", str(text))
    text = re.sub(r"\s+", "-", text.strip())
    return text[:40].strip("-").lower()


def build_stations(info_items: list, status_items: list) -> list:
    """충전소 ID 기준으로 충전기 정보 + 실시간 상태를 합쳐 station 레코드 생성.
    삭제된 충전기(delYn=Y)는 제외한다."""
    status_by_charger = {
        f"{s.get('statId')}_{s.get('chgerId')}": s for s in status_items
    }

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

        status_key = f"{stat_id}_{it.get('chgerId')}"
        status = status_by_charger.get(status_key, {})
        stat_code = str(status.get("stat", "9"))
        status_text, status_class = STATUS_MAP.get(stat_code, ("상태미확인", "unknown"))

        chger_type = str(it.get("chgerType", ""))
        speed = "완속" if chger_type in SLOW_CHARGER_TYPES else "급속"

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

    max_attempts = 3
    info_items = status_items = None
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"\n[Step 1] 충전기 기본정보 수집 중... (시도 {attempt}/{max_attempts})")
            info_items = fetch_all(INFO_URL, limit=args.limit)
            print(f"  → 총 {len(info_items)}건 수집 완료\n")

            print(f"[Step 2] 실시간 충전기 상태 수집 중... (시도 {attempt}/{max_attempts})")
            status_items = fetch_all(STATUS_URL, limit=args.limit)
            print(f"  → 총 {len(status_items)}건 수집 완료\n")
            break
        except RuntimeError as e:
            print(f"  [중단] {e}")
            if attempt == max_attempts:
                raise SystemExit(
                    f"{max_attempts}회 시도 모두 실패했습니다. 기존 데이터는 그대로 유지합니다."
                )
            print(f"  전체를 처음부터 다시 시도합니다...\n")

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
