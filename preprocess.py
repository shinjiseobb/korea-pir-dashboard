"""
원천 데이터 정제 파이프라인 (Data Preprocessing Pipeline)
- 국세청 근로소득 데이터(raw/income_raw.xlsx)와 한국부동산원 주택종합 매매가격(raw/housing_price_raw.csv)을 분석/정제
- 지역 명칭 및 권역 표준화 매핑
- 순수 표준 라이브러리 기반 안전한 정적 데이터 파이프라인 (보안 및 환경 호환성 극대화)
- 무결성 검증 및 전처리 완료 데이터(processed/cleaned_pir_dataset.csv) 생성
- 투명한 파일 및 콘솔 이중 로깅 (logs/preprocessing.log)
"""

import sys
import os
import csv
import logging
from pathlib import Path
import openpyxl

# 콘솔 한글 인코딩 보장
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
DATA_RAW = BASE_DIR / "data" / "raw"
DATA_PROCESSED = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# 로깅 설정 (콘솔 + 파일 동시 기록)
logger = logging.getLogger("DataPreprocessor")
logger.setLevel(logging.INFO)
logger.handlers.clear()

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# 콘솔 핸들러
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
logger.addHandler(ch)

# 파일 핸들러 (logs/preprocessing.log)
fh = logging.FileHandler(LOGS_DIR / "preprocessing.log", encoding="utf-8")
fh.setFormatter(formatter)
logger.addHandler(fh)

# 1. 시·도 표준 명칭 매핑 사전
SIDO_NAMES = {
    "서울": "서울특별시",
    "부산": "부산광역시",
    "대구": "대구광역시",
    "인천": "인천광역시",
    "광주": "광주광역시",
    "대전": "대전광역시",
    "울산": "울산광역시",
    "세종": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원특별자치도",
    "충북": "충청북도",
    "충남": "충청남도",
    "전북": "전북특별자치도",
    "전남": "전라남도",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주": "제주특별자치도",
    "전국": "전국"
}

# 2. 서울 권역별 구 매핑 (한국부동산원 공시 기준)
SEOUL_SUBREGIONS = {
    "도심권": ["종로구", "중구", "용산구"],
    "동북권": ["성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구", "노원구"],
    "서북권": ["은평구", "서대문구", "마포구"],
    "서남권": ["양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구"],
    "동남권": ["서초구", "강남구", "송파구", "강동구"]
}

def clean_number(val):
    """문자열 숫자의 쉼표, 따옴표 제거 후 실수 변환"""
    if val is None:
        return None
    val_str = str(val).strip().replace(",", "").replace('"', "")
    if not val_str or val_str == "-":
        return None
    try:
        return float(val_str)
    except ValueError:
        return None

def parse_income_data(filepath: Path):
    """국세청 근로소득 데이터 파싱 (인원수, 총급여액, 1인당 평균연소득 계산)"""
    logger.info(">>> 1. 국세청 근로소득 원천 데이터 파싱 시작: %s", filepath.name)
    wb = openpyxl.load_workbook(filepath, data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))

    sido_incomes = {}
    district_incomes = {}
    current_sido = None

    for r in rows[3:]:
        name = str(r[0]).strip() if r[0] is not None else ""
        if not name or name == "None":
            continue

        people = clean_number(r[1])
        total_pay_raw = clean_number(r[2])  # 단위: 백만 원
        if people is None or total_pay_raw is None or people == 0:
            continue

        total_pay_won = int(total_pay_raw * 1_000_000)
        avg_income_won = int(total_pay_won / people)

        if name in SIDO_NAMES:
            current_sido = name
            standard_name = SIDO_NAMES[name]
            sido_incomes[standard_name] = {
                "region_name": standard_name,
                "people_count": int(people),
                "total_pay_won": total_pay_won,
                "annual_income_won": avg_income_won,
                "level": "전국" if name == "전국" else "시도"
            }
        else:
            district_incomes[name] = {
                "sido": current_sido,
                "district_name": name,
                "people_count": int(people),
                "total_pay_won": total_pay_won,
                "annual_income_won": avg_income_won
            }

    logger.info("   - 시·도 소득 집계 완료: %d개 지역", len(sido_incomes))
    logger.info("   - 시·군·구 소득 집계 완료: %d개 지역", len(district_incomes))

    # 서울 5개 권역 소득 합성 계산 (도심권, 동북권, 서북권, 서남권, 동남권)
    seoul_zones = {}
    for zone, dist_list in SEOUL_SUBREGIONS.items():
        total_people = 0
        total_pay = 0
        matched_districts = []
        for dist in dist_list:
            if dist in district_incomes:
                matched_districts.append(dist)
                total_people += district_incomes[dist]["people_count"]
                total_pay += district_incomes[dist]["total_pay_won"]
        if total_people > 0:
            avg_zone_income = int(total_pay / total_people)
            seoul_zones[f"서울 {zone}"] = {
                "region_name": f"서울 {zone}",
                "people_count": total_people,
                "total_pay_won": total_pay,
                "annual_income_won": avg_zone_income,
                "level": "권역"
            }
            logger.info("   - [서울 권역 산출] %s (포함 구 %d개): 평균연소득 %s원", f"서울 {zone}", len(matched_districts), f"{avg_zone_income:,}")

    return sido_incomes, seoul_zones, district_incomes

def parse_housing_price_data(filepath: Path):
    """한국부동산원 평균매매가격 데이터 파싱 (최신 월 가격 추출 및 천 원 -> 원 환산)"""
    logger.info(">>> 2. 한국부동산원 매매가격 원천 데이터 파싱 시작: %s", filepath.name)
    housing_data = {}
    excluded_rows = []

    with open(filepath, "r", encoding="cp949") as f:
        reader = list(csv.reader(f))

    month_headers = reader[0][4:]
    latest_month = month_headers[-1].strip()
    logger.info("   - 가격 데이터 최신 기준 월: %s", latest_month)

    EXCLUDE_KEYWORDS = {
        "수도권": "광역 통계군 (개별 행정구역 아님)",
        "지방권": "광역 통계군 (개별 행정구역 아님)",
        "5대광역시": "집계용 중간 통계군",
        "4대광역시": "집계용 중간 통계군",
        "8개도": "집계용 중간 통계군",
        "7개도": "집계용 중간 통계군",
        "강북지역": "서울 강북 상위 집계군 (세부 권역과 중복)",
        "강남지역": "서울 강남 상위 집계군 (세부 권역과 중복)",
        "전남광주": "광주/전남 묶음 광역 집계군 (개별 광주, 전남과 중복)"
    }

    for row in reader[2:]:
        no = row[0].strip()
        reg1 = row[1].strip()
        reg2 = row[2].strip()
        reg3 = row[3].strip()
        latest_price_str = row[-1].strip()

        price_thousand_won = clean_number(latest_price_str)
        if price_thousand_won is None:
            excluded_rows.append((f"{reg1} {reg2} {reg3}".strip(), "가격 결측치 또는 미집계"))
            continue

        price_won = int(price_thousand_won * 1_000)

        # 1) 전국
        if reg1 == "전국" and reg2 == "전국":
            housing_data["전국"] = {
                "region_name": "전국",
                "housing_price_won": price_won,
                "latest_month": latest_month,
                "level": "전국"
            }
            continue

        # 2) 전남광주 하위 개별 광주 / 전남 처리
        if reg1 == "전남광주":
            if reg2 == "광주":
                housing_data["광주광역시"] = {
                    "region_name": "광주광역시",
                    "housing_price_won": price_won,
                    "latest_month": latest_month,
                    "level": "시도"
                }
                continue
            elif reg2 == "전남":
                housing_data["전라남도"] = {
                    "region_name": "전라남도",
                    "housing_price_won": price_won,
                    "latest_month": latest_month,
                    "level": "시도"
                }
                continue
            else:
                excluded_rows.append((f"{reg1} {reg2}", EXCLUDE_KEYWORDS.get(reg1, "중복 집계군")))
                continue

        # 3) 제외 대상 검사
        if reg1 in EXCLUDE_KEYWORDS and reg2 == reg1:
            excluded_rows.append((reg1, EXCLUDE_KEYWORDS[reg1]))
            continue
        if reg2 in EXCLUDE_KEYWORDS and reg3 == reg2:
            excluded_rows.append((f"{reg1} {reg2}", EXCLUDE_KEYWORDS[reg2]))
            continue

        # 4) 시·도 단위
        if reg1 in SIDO_NAMES and reg2 == reg1 and reg3 == reg1:
            standard_name = SIDO_NAMES[reg1]
            housing_data[standard_name] = {
                "region_name": standard_name,
                "housing_price_won": price_won,
                "latest_month": latest_month,
                "level": "시도"
            }
            continue

        # 5) 서울 세부 권역 (도심권, 동북권, 서북권, 서남권, 동남권)
        if reg1 == "서울" and reg3 in SEOUL_SUBREGIONS:
            zone_key = f"서울 {reg3}"
            housing_data[zone_key] = {
                "region_name": zone_key,
                "housing_price_won": price_won,
                "latest_month": latest_month,
                "level": "권역"
            }
            continue

        # 그 외 세부 하위 권역
        excluded_rows.append((f"{reg1} {reg2} {reg3}".strip(), "소득 통계 행정구역(시군구)과 경계 불일치 권역"))

    logger.info("   - 가격 데이터 유효 추출 완료: %d개 지역", len(housing_data))
    logger.info("   - 제외/격리된 데이터 행 (%d건):", len(excluded_rows))
    for region_label, reason in excluded_rows:
        logger.info("     * [%s] 제외 사유: %s", region_label, reason)

    return housing_data, latest_month

def build_pir_dataset():
    """소득 데이터와 매매가격 데이터를 안전하게 결합하여 PIR 정제 데이터셋 생성"""
    raw_income_file = DATA_RAW / "income_raw.xlsx"
    raw_housing_file = DATA_RAW / "housing_price_raw.csv"

    if not raw_income_file.exists() or not raw_housing_file.exists():
        raise FileNotFoundError("원천 데이터 파일이 data/raw/ 에 존재하지 않습니다.")

    sido_incomes, seoul_zones, _ = parse_income_data(raw_income_file)
    housing_data, latest_month = parse_housing_price_data(raw_housing_file)

    all_incomes = {**sido_incomes, **seoul_zones}

    records = []
    unmatched = []

    for reg_key, house_info in housing_data.items():
        if reg_key in all_incomes:
            inc_info = all_incomes[reg_key]
            price = house_info["housing_price_won"]
            income = inc_info["annual_income_won"]
            pir = round(price / income, 2)

            records.append({
                "region_name": reg_key,
                "level": house_info["level"],
                "housing_price_won": price,
                "housing_price_manwon": round(price / 10_000, 1),
                "annual_income_won": income,
                "annual_income_manwon": round(income / 10_000, 1),
                "pir": pir,
                "income_year": "2022",
                "price_month": latest_month
            })
        else:
            unmatched.append(reg_key)

    if unmatched:
        logger.warning("   ! 소득 데이터와 매핑되지 않은 지역 (%d건): %s", len(unmatched), unmatched)

    # 전국 PIR 기준으로 전국 대비 배수 산출
    national_pir = next((r["pir"] for r in records if r["region_name"] == "전국"), 1.0)
    for r in records:
        r["pir_vs_national"] = round(r["pir"] / national_pir, 2)

    # PIR 내림차순 정렬 (높은 순)
    records.sort(key=lambda x: x["pir"], reverse=True)

    # 랭킹 부여 (전국은 0, 나머지는 1부터)
    rank = 1
    for r in records:
        if r["region_name"] == "전국":
            r["rank"] = 0
        else:
            r["rank"] = rank
            rank += 1

    # 결과 저장 (CSV)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    output_path = DATA_PROCESSED / "cleaned_pir_dataset.csv"

    fieldnames = [
        "rank", "region_name", "level",
        "housing_price_won", "housing_price_manwon",
        "annual_income_won", "annual_income_manwon",
        "pir", "pir_vs_national", "income_year", "price_month"
    ]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    logger.info(">>> 3. 정제 완료된 PIR 데이터셋 저장 성공: %s", output_path)
    logger.info("   - 총 정제된 지역 수: %d개", len(records))
    logger.info("   - 전국 평균 PIR: %.2f배", national_pir)
    logger.info("   - PIR 최고 지역: %s (%.2f배)", records[0]["region_name"], records[0]["pir"])

    return output_path, records

if __name__ == "__main__":
    output_file, rows = build_pir_dataset()
    print("\n[정제 결과 상위 10개 지역 샘플]")
    header_fmt = "{:<5} {:<15} {:<8} {:>15} {:>15} {:>10} {:>12}"
    row_fmt = "{:<5} {:<15} {:<8} {:>13}만 {:>13}만 {:>10.2f}배 {:>10.2f}배"
    print(header_fmt.format("순위", "지역명", "구분", "주택가격(만원)", "평균연소득(만원)", "PIR", "전국대비"))
    print("-" * 85)
    for r in rows[:10]:
        print(row_fmt.format(
            r["rank"], r["region_name"], r["level"],
            f"{r['housing_price_manwon']:,}",
            f"{r['annual_income_manwon']:,}",
            r["pir"], r["pir_vs_national"]
        ))
