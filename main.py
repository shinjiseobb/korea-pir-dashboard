"""
PIR 대시보드 경량 백엔드 API 서버 (main.py)
- 프레임워크: FastAPI + Uvicorn
- 보안 원칙 준수:
  1. Pydantic 기반 입력값 타입/범위 엄격 검증
  2. CORS 로컬호스트 엄격 통제 (.env 연동)
  3. 보안 예외 처리기 (내부 스택트레이스 은폐 및 표준화된 에러 응답)
  4. 로그 파일(logs/backend.log) 실시간 기록
  5. 정적 웹 파일(static/) 서빙
"""

import sys
import os
import time
import logging
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status, Query, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# tools.py 의 핵심 로직 import
from tools import pir_service
from gemini_agent import run_gemini_agent

# 콘솔 한글 인코딩 보장
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
STATIC_DIR = BASE_DIR / "static"
DATA_RAW_DIR = BASE_DIR / "data" / "raw"

# Vercel 등 읽기 전용(Read-Only) 서버리스 환경 고려한 안전한 디렉터리 생성
try:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
except (OSError, PermissionError):
    pass

# 1. 환경변수 로드
load_dotenv(BASE_DIR / ".env")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))
ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGINS_RAW.split(",") if origin.strip()]

# 2. 로깅 설정 (콘솔 필수 + 로컬 파일 선택)
logger = logging.getLogger("BackendServer")
logger.setLevel(logging.INFO)
logger.handlers.clear()

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# 콘솔 출력 (Vercel에서는 콘솔 출력이 런타임 로그로 완벽히 자동 캡처됨)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
logger.addHandler(ch)

# 파일 출력 (로컬 환경에서만 안전하게 시도하고, Vercel 읽기전용 환경에서는 조용히 통과)
try:
    fh = logging.FileHandler(LOGS_DIR / "backend.log", encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
except (OSError, PermissionError):
    pass

# 3. FastAPI 인스턴스 생성
app = FastAPI(
    title="전국 시·군·구 PIR 비교 대시보드 API",
    description="행정구역별 주택 매매가격 대비 연소득 배수(PIR) 분석 서비스",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None
)

# 4. CORS 보안 미들웨어 설정 (로컬호스트 엄격 통제)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# 5. 보안 미들웨어: 접근 로깅 및 내부 스택 트레이스 은폐
@app.middleware("http")
async def security_and_logging_middleware(request: Request, call_next):
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    try:
        response = await call_next(request)
        process_time = round((time.time() - start_time) * 1000, 2)
        logger.info(f"{request.method} {request.url.path} - {response.status_code} ({process_time}ms) [from {client_ip}]")
        return response
    except Exception as exc:
        process_time = round((time.time() - start_time) * 1000, 2)
        # 보안 원칙: 상세 서버 에러는 logs/backend.log 에만 기록하고, 사용자에게는 은폐
        logger.error(f"❌ 500 내부 서버 오류 발생 ({request.method} {request.url.path}): {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "서버 내부 처리 중 오류가 발생했습니다. 로그를 확인해 주세요.",
                "status_code": 500
            }
        )

# 6. Pydantic 입력값 유효성 검증 모델 (타입 및 경계값 제한)
class BudgetFilterRequest(BaseModel):
    annual_income_won: int = Field(
        ...,
        gt=0,
        le=10_000_000_000,
        description="사용자 연소득 (원 단위, 0 초과 100억 이하)"
    )
    max_pir: Optional[float] = Field(
        None,
        gt=0,
        le=100.0,
        description="감당 가능한 최대 PIR 상한선 (예: 10.0)"
    )
    min_pir: Optional[float] = Field(
        None,
        ge=0,
        le=100.0,
        description="최소 PIR 하한선"
    )
    max_budget_won: Optional[int] = Field(
        None,
        gt=0,
        le=50_000_000_000,
        description="주택 구매 최대 예산 (원 단위)"
    )

class RegionCompareRequest(BaseModel):
    regions: List[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="비교할 지역명 목록 (1개 이상 10개 이하)"
    )

class GeminiAskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="사용자의 자연어 질문"
    )
    api_key: Optional[str] = Field(
        None,
        description="Gemini API Key (생략 시 .env 의 GEMINI_API_KEY 사용)"
    )
    model: Optional[str] = Field(
        "gemini-3.5-flash-lite",
        description="Gemini 모델명 (기본: gemini-3.5-flash-lite)"
    )

# 7. API 엔드포인트 구현 (Vercel 클라우드 라우팅 호환을 위한 이중 데코레이터 적용)

@app.post("/api/upload", tags=["데이터 업로드"])
@app.post("/upload", tags=["데이터 업로드"])
async def upload_multiple_files(files: List[UploadFile] = File(...)):
    """
    여러 개의 원천 데이터 파일(CSV, Excel)을 안전하게 업로드하여 data/raw/ 에 격리 보관
    - 보안 검증: 확장자 화이트리스트(.csv, .xlsx, .xls) 및 Path Traversal 방어
    """
    ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
    MAX_FILE_SIZE = 25 * 1024 * 1024  # 파일당 최대 25MB

    uploaded_results = []
    errors = []

    for file in files:
        # 1. 파일명 추출 및 Path Traversal 방어
        raw_name = file.filename or "unknown_file"
        safe_name = Path(raw_name).name
        ext = Path(safe_name).suffix.lower()

        # 2. 확장자 화이트리스트 검증
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"'{safe_name}': 지원하지 않는 파일 형식입니다. (CSV 및 Excel 파일만 허용)")
            continue

        # 3. 파일 내용 읽기 및 크기 검증
        content = await file.read()
        file_size = len(content)

        if file_size > MAX_FILE_SIZE:
            errors.append(f"'{safe_name}': 파일 크기 초과 (최대 25MB 이하만 가능)")
            continue

        if file_size == 0:
            errors.append(f"'{safe_name}': 빈 파일(0 Bytes)은 업로드할 수 없습니다.")
            continue

        # 4. 파일 저장 (로컬은 data/raw, Vercel 읽기전용 서버리스는 /tmp 로 안전 저장)
        try:
            DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
            dest_path = DATA_RAW_DIR / safe_name
            dest_path.write_bytes(content)
            saved_label = f"data/raw/{safe_name}"
        except (OSError, PermissionError):
            import tempfile
            dest_path = Path(tempfile.gettempdir()) / safe_name
            dest_path.write_bytes(content)
            saved_label = f"temp/{safe_name}"

        logger.info(f"📁 파일 업로드 성공: {safe_name} ({file_size:,} Bytes) -> {saved_label}")
        uploaded_results.append({
            "filename": safe_name,
            "size_bytes": file_size,
            "size_formatted": f"{round(file_size / 1024, 1):,} KB",
            "saved_path": saved_label
        })

    # 5. 파일 업로드 후 자동 재분석 트리거 (신규 데이터셋 자동 정제 및 갱신)
    pipeline_executed = False
    try:
        from preprocess import build_pir_dataset
        build_pir_dataset()
        pir_service._load_data()  # 메모리 캐시 갱신
        pipeline_executed = True
        logger.info("⚙️ 업로드된 새 파일을 반영하여 PIR 데이터 정제 파이프라인 자동 재실행 완료!")
    except Exception as e:
        logger.warning(f"업로드 후 자동 정제 파이프라인 건너뜀 (기본 데이터셋 유지): {e}")

    return {
        "success": len(uploaded_results) > 0,
        "uploaded_count": len(uploaded_results),
        "uploaded_files": uploaded_results,
        "pipeline_executed": pipeline_executed,
        "errors": errors
    }

@app.get("/api/health", tags=["시스템"])
@app.get("/health", tags=["시스템"])
def health_check():
    """서버 정상 작동 및 헬스체크"""
    return {
        "status": "healthy",
        "service": "korea-pir-dashboard",
        "data_loaded": len(pir_service._data) > 0,
        "region_count": len(pir_service._data)
    }

@app.get("/api/pir", tags=["PIR 지표"])
@app.get("/pir", tags=["PIR 지표"])
def get_all_pir(
    sort_by: str = Query("pir", description="정렬 기준: pir, housing_price_won, annual_income_won, rank"),
    ascending: bool = Query(False, description="오름차순 여부")
):
    """전국 시·도 및 권역별 전체 PIR 랭킹 데이터 조회"""
    data = pir_service.calculate_pir(sort_by=sort_by, ascending=ascending)
    return {
        "success": True,
        "count": len(data),
        "data": data
    }

@app.get("/api/search", tags=["지역 검색"])
@app.get("/search", tags=["지역 검색"])
def search_region(
    q: str = Query(..., min_length=1, max_length=20, description="검색할 지역 키워드")
):
    """지역명 키워드 검색"""
    results = pir_service.match_region_codes(query=q)
    return {
        "success": True,
        "query": q,
        "count": len(results),
        "data": results
    }

@app.post("/api/filter", tags=["맞춤 필터링"])
@app.post("/filter", tags=["맞춤 필터링"])
def filter_by_user_budget(payload: BudgetFilterRequest):
    """사용자 연소득 및 예산 기준 진입 가능 지역 필터링"""
    filtered = pir_service.filter_by_budget(
        user_annual_income_won=payload.annual_income_won,
        max_pir=payload.max_pir,
        min_pir=payload.min_pir,
        max_budget_won=payload.max_budget_won
    )
    return {
        "success": True,
        "user_annual_income_won": payload.annual_income_won,
        "count": len(filtered),
        "data": filtered
    }

@app.post("/api/compare", tags=["지역 비교"])
@app.post("/compare", tags=["지역 비교"])
def compare_selected_regions(payload: RegionCompareRequest):
    """선택 지역 간 다각도 비교 분석"""
    comparison = pir_service.compare_regions(region_names=payload.regions)
    if "error" in comparison and not comparison.get("regions"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "message": comparison["error"]}
        )
    return {
        "success": True,
        "data": comparison
    }

@app.post("/api/ai/ask", tags=["AI 분석 비서"])
@app.post("/ai/ask", tags=["AI 분석 비서"])
def ask_gemini_agent(payload: GeminiAskRequest):
    """
    제미나이 3단계 데이터 분석 에이전트
    1단계: 의도 파악 -> 2단계: 파이썬 정밀 연산 -> 3단계: 최종 해설 보고서 생성
    """
    # API 키 확인: 요청 본문의 키 우선, 없으면 .env의 GEMINI_API_KEY 사용
    api_key = payload.api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "message": "Gemini API Key가 제공되지 않았습니다. 화면의 API Key 입력란에 키를 입력하거나 .env 파일에 GEMINI_API_KEY를 등록해 주세요."
            }
        )

    try:
        agent_result = run_gemini_agent(
            user_question=payload.question,
            api_key=api_key,
            model=payload.model or "gemini-3.5-flash-lite"
        )
        return agent_result
    except Exception as e:
        logger.error(f"AI 에이전트 실행 실패: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": f"AI 분석 처리 중 오류가 발생했습니다: {str(e)}"
            }
        )

# 8. 정적 웹 파일 서빙 (Front-end)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
def get_favicon():
    """브라우저 탭 아이콘 (404 방지용 인라인 SVG 파비콘 제공)"""
    svg_icon = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <text y=".9em" font-size="90">🏠</text>
    </svg>"""
    from fastapi.responses import Response
    return Response(content=svg_icon, media_type="image/svg+xml")

@app.get("/", tags=["화면"])
def serve_index():
    """웹 앱 홈 화면 (static/index.html) 제공"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return {
        "message": "PIR 대시보드 API 서버가 정상 실행 중입니다. 프론트엔드 파일(static/index.html)이 생성되면 화면이 표시됩니다.",
        "api_docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    logger.info(f"🚀 PIR 백엔드 서버 시작: http://{HOST}:{PORT}")
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
