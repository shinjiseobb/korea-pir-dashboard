"""
Gemini 지능형 데이터 분석 에이전트 모듈 (gemini_agent.py)
- 아키텍처: 3단계 파이프라인
  1단계: 제미나이가 자연어 질문의 의도를 분석하여 실행할 도구(Tool) 및 파라미터 추출
  2단계: 파이썬(tools.py)에서 정확한 팩트 수치 및 PIR 계산 (환각 원천 차단)
  3단계: 파이썬 계산 결과를 바탕으로 제미나이가 친절하고 전문적인 자연어 보고서 작성
- Vercel 서버리스 호환: 외부 무거운 SDK 없이 표준 HTTP 통신으로 초경량 구동
"""

import os
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

from tools import pir_service

logger = logging.getLogger("GeminiAgent")

# 도구 명세 정의 (제미나이 의도 파악용)
TOOL_DEFINITIONS = [
    {
        "name": "calculate_pir",
        "description": "지역별 주택가격 대비 소득 배수(PIR) 랭킹 및 전국 대비 배수를 조회합니다.",
        "parameters": {
            "region_name": "특정 지역명 (예: 서울특별시, 경기도, 서울 동남권 등, 없으면 전체)",
            "sort_by": "정렬 기준 ('pir', 'housing_price_won', 'annual_income_won', 'rank')",
            "ascending": "오름차순 여부 (True 또는 False)"
        }
    },
    {
        "name": "filter_by_budget",
        "description": "사용자의 연소득이나 예산 기준 진입 가능한 지역과 소요 연수를 필터링합니다.",
        "parameters": {
            "annual_income_won": "사용자 연소득 (원 단위 정수, 예: 5천만원 -> 50000000)",
            "max_pir": "감당 가능한 최대 PIR 상한선 (예: 10.0)"
        }
    },
    {
        "name": "compare_regions",
        "description": "2개 이상의 선택된 지역 간 집값, 연소득, PIR을 직접 비교 분석합니다.",
        "parameters": {
            "regions": "비교할 지역명 배열 (예: ['서울특별시', '경기도', '부산광역시'])"
        }
    },
    {
        "name": "match_region_codes",
        "description": "사용자가 언급한 지역 키워드로 등록된 행정구역을 검색합니다.",
        "parameters": {
            "query": "검색 키워드 (예: '서울', '경기', '동남')"
        }
    }
]

def call_gemini_api(api_key: str, model: str, prompt: str, system_instruction: Optional[str] = None) -> str:
    """Google Gemini REST API 호출 (표준 라이브러리 기반 경량 호출)"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048
        }
    }

    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            candidates = res_json.get("candidates", [])
            if not candidates:
                raise ValueError("제미나이로부터 응답 후보를 받지 못했습니다.")
            return candidates[0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        logger.error(f"Gemini API HTTP Error {e.code}: {err_msg}")
        raise RuntimeError(f"Gemini API 오류 ({e.code}): {err_msg}")
    except Exception as e:
        logger.error(f"Gemini API 호출 실패: {e}")
        raise RuntimeError(f"Gemini 연결 실패: {e}")

def run_gemini_agent(user_question: str, api_key: str, model: str = "gemini-1.5-flash") -> Dict[str, Any]:
    """
    3단계 파이프라인 실행:
    1단계: 의도 분석 및 도구 선택
    2단계: 파이썬 tools.py 정밀 연산
    3단계: 제미나이 최종 보고서 작성
    """
    if not api_key or not api_key.strip():
        raise ValueError("Gemini API Key가 제공되지 않았습니다.")
    
    clean_key = api_key.strip()
    clean_model = model.strip() if model else "gemini-1.5-flash"

    # [1단계: 의도 파악] 제미나이에게 어떤 도구를 실행할지 JSON으로 요청
    step1_system = f"""당신은 부동산 데이터 분석 에이전트의 '의도 파악 라우터'입니다.
사용자의 자연어 질문을 분석하여, 아래의 가용한 도구들 중 가장 적합한 도구 1개를 선택하고 필요한 인자(parameter)를 추출하세요.

가용한 도구 목록:
{json.dumps(TOOL_DEFINITIONS, ensure_ascii=False, indent=2)}

반드시 아래와 같은 순수한 JSON 형식으로만 응답하세요 (마크다운 백틱 없이):
{{
  "tool_name": "선택한도구이름",
  "parameters": {{ "인자이름": "값" }},
  "user_intent": "사용자의 질문 의도 1줄 요약"
}}
만약 사용자의 질문이 연봉이나 소득에 관련된 것이라면 금액을 원(Won) 단위 정수로 환산하세요 (예: 5천만원 -> 50000000, 6000만원 -> 60000000)."""

    logger.info(f"🤖 [1단계] 제미나이 의도 파악 시작 (질문: {user_question})")
    step1_response = call_gemini_api(
        api_key=clean_key,
        model=clean_model,
        prompt=user_question,
        system_instruction=step1_system
    )

    # JSON 파싱
    clean_json_str = step1_response.strip()
    if clean_json_str.startswith("```"):
        lines = clean_json_str.splitlines()
        clean_json_str = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        tool_call = json.loads(clean_json_str)
        tool_name = tool_call.get("tool_name", "calculate_pir")
        parameters = tool_call.get("parameters", {})
        user_intent = tool_call.get("user_intent", "부동산 데이터 조회")
    except Exception:
        # 파싱 실패 시 기본 calculate_pir 조회로 폴백
        tool_name = "calculate_pir"
        parameters = {}
        user_intent = "전국 PIR 데이터 조회"

    logger.info(f"⚙️ [2단계] 파이썬 계산 실행 -> 도구: {tool_name}, 인자: {parameters}")

    # [2단계: 파이썬 정밀 계산]
    calc_result = None
    try:
        if tool_name == "calculate_pir":
            calc_result = pir_service.calculate_pir(
                region_name=parameters.get("region_name"),
                sort_by=parameters.get("sort_by", "pir"),
                ascending=parameters.get("ascending", False)
            )
        elif tool_name == "filter_by_budget":
            income = int(parameters.get("annual_income_won", 50_000_000))
            max_pir = float(parameters["max_pir"]) if "max_pir" in parameters and parameters["max_pir"] is not None else None
            calc_result = pir_service.filter_by_budget(
                user_annual_income_won=income,
                max_pir=max_pir
            )
        elif tool_name == "compare_regions":
            regs = parameters.get("regions", ["서울특별시", "경기도", "부산광역시"])
            if isinstance(regs, str):
                regs = [regs]
            calc_result = pir_service.compare_regions(region_names=regs)
        elif tool_name == "match_region_codes":
            calc_result = pir_service.match_region_codes(query=parameters.get("query", ""))
        else:
            calc_result = pir_service.calculate_pir()[:5]
    except Exception as e:
        logger.error(f"파이썬 도구 실행 오류: {e}")
        calc_result = pir_service.calculate_pir()[:5]

    # [3단계: 제미나이 최종 해설 작성]
    step3_system = """당신은 대한민국 최고 권위의 부동산/금융 데이터 전문 분석가 'PIR AI 비서'입니다.
제공된 '파이썬 정밀 계산 결과 데이터'만을 팩트로 사용하여, 사용자의 원래 질문에 대해 매우 친절하고 명쾌하며 통찰력 있는 한국어로 보고서를 작성해 주세요.

작성 가이드라인:
1. 팩트 중심: 계산된 수치(집값, 연소득, PIR 배수, 소요 연수)를 정확하게 인용하세요.
2. PIR 해석: PIR 배수가 갖는 현실적 의미(예: 월급을 전액 저축했을 때 걸리는 기간, 대출 부담 수준)를 알기 쉽게 해설하세요.
3. 보기 편한 구성: 핵심 결론 요약 -> 상세 데이터 비교 -> 맞춤 조언 순서로 가독성 있게 정리하세요.
4. 마크다운 형식: 볼드체, 불릿 기호 등을 적극 활용하여 깔끔하게 작성하세요."""

    step3_prompt = f"""[사용자 질문]:
{user_question}

[1단계 파악 의도]:
{user_intent} (실행 도구: {tool_name})

[2단계 파이썬 정밀 계산 팩트 데이터]:
{json.dumps(calc_result, ensure_ascii=False, indent=2)}

위 데이터를 바탕으로 사용자에게 최적의 답변과 전문 해설을 작성해 주세요."""

    logger.info("📝 [3단계] 제미나이 최종 종합 보고서 작성 중...")
    final_answer = call_gemini_api(
        api_key=clean_key,
        model=clean_model,
        prompt=step3_prompt,
        system_instruction=step3_system
    )

    return {
        "success": True,
        "model_used": clean_model,
        "user_intent": user_intent,
        "tool_used": tool_name,
        "tool_parameters": parameters,
        "raw_data": calc_result if isinstance(calc_result, (list, dict)) else [],
        "final_answer": final_answer
    }
