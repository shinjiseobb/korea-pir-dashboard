"""
PIR 대시보드 핵심 비즈니스 로직 모듈 (tools.py)
- 보안 원칙 준수: Path Traversal 방지(data/ 고정 경로), eval/exec 전면 금지, 입력값 타입 검증
- 4대 핵심 도구 구현:
  1. calculate_pir: 시·도 및 권역별 PIR 산출, 랭킹 및 전국 대비 배수 조회
  2. match_region_codes: 지역명 검색 및 표준 명칭 매핑
  3. filter_by_budget: 사용자 입력 소득/예산/희망 PIR 기반 진입 가능 지역 필터링
  4. compare_regions: 선택 지역 간 다중 비교 지표 산출
"""

import sys
import csv
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

# 콘솔 한글 인코딩 보장
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 로깅 설정
logger = logging.getLogger("PIRTools")
logger.setLevel(logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
DATA_PROCESSED_FILE = BASE_DIR / "data" / "processed" / "cleaned_pir_dataset.csv"

class PIRService:
    """안전한 데이터 격리 로더 및 비즈니스 로직 서비스"""

    def __init__(self, dataset_path: Path = DATA_PROCESSED_FILE):
        # Path Traversal 방지: 사전에 지정된 로컬 격리 파일만 사용
        self.dataset_path = dataset_path.resolve()
        if not str(self.dataset_path).startswith(str(BASE_DIR / "data")):
            raise PermissionError("보안 위반: data/ 폴더 외부 경로는 접근이 엄격히 금지됩니다.")
        
        self._data: List[Dict[str, Any]] = []
        self._national_info: Optional[Dict[str, Any]] = None
        self._load_data()

    def _load_data(self):
        """정제된 CSV 데이터셋 안전 로드 및 메모리 캐싱"""
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"정제된 데이터 파일이 존재하지 않습니다: {self.dataset_path}")

        records = []
        with open(self.dataset_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cleaned_row = {
                    "rank": int(row["rank"]),
                    "region_name": str(row["region_name"]).strip(),
                    "level": str(row["level"]).strip(),
                    "housing_price_won": int(row["housing_price_won"]),
                    "housing_price_manwon": float(row["housing_price_manwon"]),
                    "annual_income_won": int(row["annual_income_won"]),
                    "annual_income_manwon": float(row["annual_income_manwon"]),
                    "pir": float(row["pir"]),
                    "pir_vs_national": float(row["pir_vs_national"]),
                    "income_year": str(row["income_year"]),
                    "price_month": str(row["price_month"])
                }
                records.append(cleaned_row)
                if cleaned_row["region_name"] == "전국":
                    self._national_info = cleaned_row

        self._data = records
        logger.info("PIRService: %d개 지역 데이터 로드 완료 (전국 평균 PIR: %.2f)", len(self._data), self._national_info["pir"] if self._national_info else 0)

    # 1. calculate_pir
    def calculate_pir(
        self,
        region_name: Optional[str] = None,
        sort_by: str = "pir",
        ascending: bool = False
    ) -> List[Dict[str, Any]]:
        """
        지역별 PIR 및 전국 대비 배수 조회 및 정렬
        - region_name 지정 시 해당 지역만 반환
        - sort_by: 'pir', 'housing_price_won', 'annual_income_won', 'rank'
        """
        # 정렬 기준 화이트리스트 검증 (SQL/동적 실행 방지)
        allowed_sort_fields = {"pir", "housing_price_won", "annual_income_won", "rank", "pir_vs_national"}
        if sort_by not in allowed_sort_fields:
            sort_by = "pir"

        if region_name:
            matched = [r for r in self._data if r["region_name"] == region_name.strip()]
            return matched

        # 정렬 수행
        return sorted(self._data, key=lambda x: x[sort_by], reverse=not ascending)

    # 2. match_region_codes
    def match_region_codes(self, query: str) -> List[Dict[str, Any]]:
        """
        지역명 키워드 검색 및 표준 명칭 매칭
        - query: 사용자가 입력한 검색어 (예: '서울', '경기', '동남')
        """
        if not query or not isinstance(query, str):
            return []

        clean_query = query.strip()
        matched = []
        for r in self._data:
            if clean_query in r["region_name"]:
                matched.append({
                    "region_name": r["region_name"],
                    "level": r["level"],
                    "pir": r["pir"],
                    "rank": r["rank"]
                })
        return matched

    # 3. filter_by_budget
    def filter_by_budget(
        self,
        user_annual_income_won: int,
        max_pir: Optional[float] = None,
        min_pir: Optional[float] = None,
        max_budget_won: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        사용자 입력 소득 기준 진입 가능한 지역 필터링
        - user_annual_income_won: 사용자의 실제 연소득 (원 단위)
        - max_pir: 감당 가능한 최대 PIR 상한선 (예: 10배 이하)
        - max_budget_won: 최대 주택 구매 예산 (원 단위)
        """
        # 보안 검증: 입력값 타입 및 양수 여부 검증
        if not isinstance(user_annual_income_won, (int, float)) or user_annual_income_won <= 0:
            raise ValueError("연소득은 0보다 큰 숫자여야 합니다.")

        results = []
        for r in self._data:
            # 전국 통계 행은 필터링 추천 목록에서 제외 (개별 지역만 추천)
            if r["region_name"] == "전국":
                continue

            price = r["housing_price_won"]
            # 사용자의 실제 소득 기준 해당 지역의 맞춤 PIR 계산
            user_custom_pir = round(price / user_annual_income_won, 2)

            # PIR 상한/하한 조건 검사
            if max_pir is not None and user_custom_pir > max_pir:
                continue
            if min_pir is not None and user_custom_pir < min_pir:
                continue

            # 최대 예산 한도 검사
            if max_budget_won is not None and price > max_budget_won:
                continue

            item = dict(r)
            item["user_custom_pir"] = user_custom_pir
            item["affordability"] = "진입 용이" if user_custom_pir <= 7.0 else ("적정 수준" if user_custom_pir <= 12.0 else "부담 큼")
            results.append(item)

        # 사용자의 맞춤 PIR이 낮은 순(구매 부담이 적은 순)으로 정렬
        return sorted(results, key=lambda x: x["user_custom_pir"])

    # 4. compare_regions
    def compare_regions(self, region_names: List[str]) -> Dict[str, Any]:
        """
        선택된 여러 지역 간 PIR, 집값, 소득 지표를 다각도로 비교 분석
        """
        if not isinstance(region_names, list) or not region_names:
            return {"error": "비교할 지역 목록을 1개 이상 지정해야 합니다.", "regions": []}

        # 화이트리스트 안전 필터링
        sanitized_names = [str(name).strip() for name in region_names if isinstance(name, str)]
        matched_regions = [r for r in self._data if r["region_name"] in sanitized_names]

        if not matched_regions:
            return {"error": "일치하는 지역을 찾을 수 없습니다.", "regions": []}

        # 비교 분석 메타 통계
        pir_values = [r["pir"] for r in matched_regions]
        prices = [r["housing_price_won"] for r in matched_regions]
        incomes = [r["annual_income_won"] for r in matched_regions]

        comparison_summary = {
            "count": len(matched_regions),
            "highest_pir_region": max(matched_regions, key=lambda x: x["pir"])["region_name"],
            "lowest_pir_region": min(matched_regions, key=lambda x: x["pir"])["region_name"],
            "avg_pir": round(sum(pir_values) / len(pir_values), 2),
            "national_pir": self._national_info["pir"] if self._national_info else None,
            "regions": matched_regions
        }
        return comparison_summary

# 전역 싱글톤 인스턴스 (필요 시 즉시 import 사용 가능)
pir_service = PIRService()

# 편의 래퍼 함수 (도구 명세서 규격)
def calculate_pir(region_name: Optional[str] = None, sort_by: str = "pir", ascending: bool = False):
    return pir_service.calculate_pir(region_name=region_name, sort_by=sort_by, ascending=ascending)

def match_region_codes(query: str):
    return pir_service.match_region_codes(query=query)

def filter_by_budget(annual_income_won: int, max_pir: Optional[float] = None, min_pir: Optional[float] = None, max_budget_won: Optional[int] = None):
    return pir_service.filter_by_budget(annual_income_won, max_pir=max_pir, min_pir=min_pir, max_budget_won=max_budget_won)

def compare_regions(region_names: List[str]):
    return pir_service.compare_regions(region_names=region_names)

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print(">>> Step 4: PIR 핵심 도구 (tools.py) 단위 테스트 실행")
    print("=" * 70)

    # 1. calculate_pir 테스트
    top3 = calculate_pir()[:3]
    print("\n[도구 1. calculate_pir] 상위 3개 지역:")
    for r in top3:
        print(f" - #{r['rank']} {r['region_name']}: PIR {r['pir']}배 (집값 {r['housing_price_manwon']:,}만원 / 소득 {r['annual_income_manwon']:,}만원)")

    # 2. match_region_codes 테스트
    query = "서울"
    matched = match_region_codes(query)
    print(f"\n[도구 2. match_region_codes] '{query}' 검색 결과 ({len(matched)}건):")
    for m in matched:
        print(f" - {m['region_name']} (PIR {m['pir']}배, 전국 {m['rank']}위)")

    # 3. filter_by_budget 테스트 (내 연봉 5,000만원, 희망 PIR 10배 이하)
    user_income = 50_000_000
    affordable = filter_by_budget(annual_income_won=user_income, max_pir=10.0)
    print(f"\n[도구 3. filter_by_budget] 연소득 5,000만원 기준 PIR 10배 이하 진입 가능 지역 ({len(affordable)}건):")
    for a in affordable[:5]:
        print(f" - {a['region_name']}: 집값 {a['housing_price_manwon']:,}만원 -> 내 소득 기준 {a['user_custom_pir']}년 소요 ({a['affordability']})")

    # 4. compare_regions 테스트
    comp_targets = ["서울특별시", "경기도", "부산광역시", "제주특별자치도"]
    comp_result = compare_regions(comp_targets)
    print(f"\n[도구 4. compare_regions] 선택 지역 비교 요약:")
    print(f" - 비교 대상: {comp_targets}")
    print(f" - PIR 최고 지역: {comp_result['highest_pir_region']}")
    print(f" - PIR 최저 지역: {comp_result['lowest_pir_region']}")
    print(f" - 비교군 평균 PIR: {comp_result['avg_pir']}배 (전국 평균: {comp_result['national_pir']}배)")
    print("=" * 70 + "\n")
