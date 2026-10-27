"""
데이터 무결성 검증 및 예외 데이터 격리 스크립트 (Data Integrity Validation & Quarantine)
- 정제된 PIR 데이터셋(data/processed/cleaned_pir_dataset.csv)의 정밀 유효성 및 보안 무결성 검증
- 결측치, 음수/0값, 수식 불일치, 중복 지역명 등 비정상 데이터 검출 시 data/quarantine/ 격리
- 검증 결과 및 통계 보고서 생성 (logs/validation.log)
"""

import sys
import os
import csv
import logging
from datetime import datetime
from pathlib import Path

# 콘솔 한글 인코딩 보장
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
DATA_PROCESSED = BASE_DIR / "data" / "processed"
DATA_QUARANTINE = BASE_DIR / "data" / "quarantine"
LOGS_DIR = BASE_DIR / "logs"

DATA_QUARANTINE.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# 로깅 설정 (콘솔 + logs/validation.log 파일)
logger = logging.getLogger("DataValidator")
logger.setLevel(logging.INFO)
logger.handlers.clear()

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# 콘솔 핸들러
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
logger.addHandler(ch)

# 파일 핸들러
fh = logging.FileHandler(LOGS_DIR / "validation.log", encoding="utf-8")
fh.setFormatter(formatter)
logger.addHandler(fh)

# 필수 컬럼 정의
REQUIRED_FIELDS = [
    "rank", "region_name", "level",
    "housing_price_won", "housing_price_manwon",
    "annual_income_won", "annual_income_manwon",
    "pir", "pir_vs_national", "income_year", "price_month"
]

def validate_dataset():
    input_file = DATA_PROCESSED / "cleaned_pir_dataset.csv"
    logger.info("=" * 60)
    logger.info(f">>> Step 3. 데이터 무결성 정밀 검증 시작: {input_file.name}")

    if not input_file.exists():
        logger.error(f"❌ 검증 대상 파일이 존재하지 않습니다: {input_file}")
        return False, []

    valid_rows = []
    quarantine_rows = []
    seen_regions = set()

    with open(input_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # 1. 필수 헤더 누락 검사
        missing_headers = [h for h in REQUIRED_FIELDS if h not in headers]
        if missing_headers:
            logger.error(f"❌ 필수 컬럼 누락 발견: {missing_headers}")
            return False, []
        logger.info(f"   [통과 1/5] 필수 헤더 컬럼 100% 일치 확인 ({len(REQUIRED_FIELDS)}개 컬럼)")

        # 전국 기준 PIR 먼저 탐색 (수식 교차 검증용)
        rows_cache = list(reader)
        national_row = next((r for r in rows_cache if r.get("region_name") == "전국"), None)
        national_pir = float(national_row["pir"]) if national_row and national_row.get("pir") else None

        for idx, row in enumerate(rows_cache, start=1):
            region = row.get("region_name", "").strip()
            reasons = []

            # 2. 결측치 (Null / Empty) 검사
            empty_keys = [k for k in REQUIRED_FIELDS if row.get(k) is None or str(row.get(k)).strip() == ""]
            if empty_keys:
                reasons.append(f"필수 필드 결측치: {empty_keys}")

            # 3. 중복 지역명 검사
            if region in seen_regions:
                reasons.append(f"지역명 중복: {region}")
            seen_regions.add(region)

            # 4. 수치 범위 및 유효성 검사 (0 이하, 음수 검사)
            try:
                price = float(row.get("housing_price_won", 0))
                income = float(row.get("annual_income_won", 0))
                pir = float(row.get("pir", 0))
                vs_nat = float(row.get("pir_vs_national", 0))

                if price <= 0:
                    reasons.append(f"주택가격 0 이하 비정상: {price}")
                if income <= 0:
                    reasons.append(f"연소득 0 이하 비정상: {income}")
                if pir <= 0 or pir > 100:
                    reasons.append(f"PIR 이상치 (허용범위 0~100 초과): {pir}")

                # 5. 수식 정합성 교차 검증 (집값 / 연소득 == PIR 인지 오차 0.05 이내 확인)
                if income > 0:
                    calculated_pir = round(price / income, 2)
                    if abs(calculated_pir - pir) > 0.05:
                        reasons.append(f"PIR 계산 수식 불일치 (기록:{pir} vs 실제계산:{calculated_pir})")

                # 전국 대비 배수 수식 교차 검증
                if national_pir and national_pir > 0:
                    expected_vs_nat = round(pir / national_pir, 2)
                    if abs(expected_vs_nat - vs_nat) > 0.05:
                        reasons.append(f"전국대비배수 수식 불일치 (기록:{vs_nat} vs 기대값:{expected_vs_nat})")

            except ValueError as ve:
                reasons.append(f"수치 파싱 실패: {ve}")

            if reasons:
                row_copy = dict(row)
                row_copy["quarantine_reason"] = " | ".join(reasons)
                row_copy["row_number"] = idx
                quarantine_rows.append(row_copy)
                logger.warning(f"   ⚠️ [이상치 탐지] {region} (행 {idx}) -> 격리 사유: {row_copy['quarantine_reason']}")
            else:
                valid_rows.append(row)

    # 검증 결과 통계 로깅
    logger.info("   [통과 2/5] 결측치 검사 완료")
    logger.info(f"   [통과 3/5] 중복 지역명 검사 완료 (유일 지역수: {len(seen_regions)}개)")
    logger.info("   [통과 4/5] 금액 및 PIR 논리 범위 검사 완료")
    logger.info("   [통과 5/5] PIR 및 전국대비배수 산출 수식 교차 검증 완료")

    # 이상치 발생 시 data/quarantine 폴더로 분리 격리
    if quarantine_rows:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        quarantine_file = DATA_QUARANTINE / f"quarantine_pir_dataset_{timestamp}.csv"
        q_fields = ["row_number", "quarantine_reason"] + REQUIRED_FIELDS
        with open(quarantine_file, "w", encoding="utf-8-sig", newline="") as qf:
            writer = csv.DictWriter(qf, fieldnames=q_fields)
            writer.writeheader()
            writer.writerows(quarantine_rows)
        logger.warning(f"🚨 [격리 완료] 이상치 데이터 {len(quarantine_rows)}건이 안전하게 격리되었습니다: {quarantine_file.name}")
    else:
        logger.info("🟢 [무결성 100%] 결측치 또는 수식 오류 0건! 모든 데이터가 완벽하게 검증되었습니다.")

    logger.info(f">>> 최종 검증 요약: 전체 {len(rows_cache)}건 중 정상 {len(valid_rows)}건, 격리 {len(quarantine_rows)}건")
    logger.info("=" * 60)
    return len(quarantine_rows) == 0, valid_rows

if __name__ == "__main__":
    is_success, valid_data = validate_dataset()
    if is_success:
        print("\n🎉 [검증 성공] cleaned_pir_dataset.csv의 모든 행이 무결성 검증을 통과했습니다.")
        print(f"   - 검증 통과 데이터 수: 총 {len(valid_data)}개 지역 (오류 0건)")
    else:
        print("\n⚠️ [검증 주의] 일부 비정상 데이터가 발견되어 data/quarantine/ 폴더로 격리되었습니다.")
