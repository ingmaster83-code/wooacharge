"""
generate_regions.py - _rawdata/stations.json 기준으로 _data/regions.json 재생성

fetch_stations.py 실행 후 항상 이어서 실행한다 (시도/시군구 목록·개수가 데이터에 맞게 갱신됨).

사용법:
  python scripts/generate_regions.py
"""
import json
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
STATIONS_FILE = ROOT / "_rawdata" / "stations.json"
REGIONS_FILE = ROOT / "_data" / "regions.json"


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s가-힣]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text.strip("-").lower()


def main():
    if not STATIONS_FILE.exists():
        raise SystemExit(f"{STATIONS_FILE} 가 없습니다. 먼저 fetch_stations.py를 실행하세요.")

    stations = json.loads(STATIONS_FILE.read_text(encoding="utf-8"))

    by_sido = defaultdict(lambda: defaultdict(int))
    for s in stations:
        sido = s.get("sido") or "기타"
        sigungu = s.get("sigungu") or "기타"
        by_sido[sido][sigungu] += 1

    regions = []
    for sido, sgs in by_sido.items():
        sido_slug = slugify(sido) or "unknown"
        sigungu_list = []
        for i, (sg, count) in enumerate(sorted(sgs.items()), start=1):
            sigungu_list.append({
                "name": sg,
                "slug": f"{sido_slug}-{i:02d}",
                "count": count,
            })
        regions.append({
            "sido": sido,
            "slug": sido_slug,
            "sigungu": sigungu_list,
        })

    REGIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGIONS_FILE.write_text(
        json.dumps(regions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[완료] {REGIONS_FILE} — {len(regions)}개 시도")


if __name__ == "__main__":
    main()
