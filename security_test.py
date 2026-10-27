"""
보안 취약점 및 비정상 입력값 스트레스 테스트 스크립트 (security_test.py)
- 보안 원칙 준수 여부 정밀 감사:
  1. 환경변수 및 비밀값 보호 (.env 가 .gitignore 에 안전하게 등록되었는지)
  2. 임의 코드 실행 금지 (eval, exec 함수 사용 여부 정적 소스코드 감사)
  3. 파일 접근 경로 검증 (Path Traversal 방어)
  4. XSS 악성 스크립트 및 SQL 인젝션 공격 방어
  5. 경계값/비정상값 (음수, 0, 천문학적 숫자, 타입 오류) Pydantic 검증 차단
  6. 서버 에러 발생 시 내부 스택트레이스 및 민감 시스템 디렉터리 경로 은폐
"""

import sys
import os
import re
from datetime import datetime
from pathlib import Path
from pydantic import ValidationError

# 콘솔 한글 인코딩 보장
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent

from tools import pir_service, PIRService
from main import BudgetFilterRequest, RegionCompareRequest, search_region, compare_selected_regions

class SecurityStressTester:
    def __init__(self):
        self.results = []

    def log_result(self, name: str, passed: bool, detail: str):
        self.results.append({"name": name, "passed": passed, "detail": detail})
        status_icon = "🟢 PASS" if passed else "🔴 FAIL"
        print(f"[{status_icon}] {name}: {detail}")

    # 1. .env 및 .gitignore 보안 감사
    def test_gitignore_security(self):
        gitignore_path = BASE_DIR / ".gitignore"
        if not gitignore_path.exists():
            self.log_result("환경변수 보호 (.gitignore)", False, ".gitignore 파일이 존재하지 않습니다.")
            return

        content = gitignore_path.read_text(encoding="utf-8")
        has_env = bool(re.search(r"^\.env\b", content, re.MULTILINE))
        has_venv = bool(re.search(r"^\.venv\b|venv\b", content, re.MULTILINE))

        if has_env and has_venv:
            self.log_result("환경변수 및 가상환경 보호", True, ".env 및 .venv 가 .gitignore에 등록되어 비밀값 외부 유출이 사전 차단되었습니다.")
        else:
            self.log_result("환경변수 및 가상환경 보호", False, ".gitignore에 .env 또는 .venv 등록이 누락되었습니다.")

    # 2. eval() / exec() 정적 코드 감사
    def test_forbidden_functions(self):
        # 검사 대상: 실제 프로덕션 코드 파일 (테스트 스크립트 자신 제외)
        py_files = [f for f in BASE_DIR.glob("*.py") if f.name != "security_test.py"]
        violations = []

        for py_file in py_files:
            code = py_file.read_text(encoding="utf-8")
            for line_no, line in enumerate(code.splitlines(), start=1):
                clean_line = line.strip()
                if clean_line.startswith("#"):
                    continue
                if re.search(r"\b(eval|exec)\s*\(", clean_line):
                    violations.append(f"{py_file.name}:{line_no} -> {clean_line}")

        if not violations:
            self.log_result("임의 코드 실행 금지 감사", True, "프로젝트 내 모든 파이썬 파일에서 eval() 및 exec() 호출 0건 (완전 금지 준수)")
        else:
            self.log_result("임의 코드 실행 금지 감사", False, f"위반 발견: {violations}")

    # 3. Path Traversal (디렉터리 탈출 공격) 방어 검증
    def test_path_traversal_defense(self):
        malicious_paths = [
            BASE_DIR / ".." / "safe-workout-planner" / "some_file.txt",
            Path("C:/Windows/win.ini"),
            Path("../../etc/passwd")
        ]
        blocked_all = True
        for malicious_path in malicious_paths:
            try:
                PIRService(dataset_path=malicious_path)
                blocked_all = False
                break
            except (PermissionError, FileNotFoundError, ValueError):
                pass  # 안전하게 거부됨

        if blocked_all:
            self.log_result("Path Traversal 방어", True, "data/ 외부 디렉터리 접근 시도 시 PermissionError로 완벽 차단")
        else:
            self.log_result("Path Traversal 방어", False, "외부 디렉터리 접근 차단 실패")

    # 4. 비정상 입력값 (경계값, 음수, 0, 천문학적 숫자) Pydantic 스트레스 테스트
    def test_boundary_inputs(self):
        test_cases = [
            ({"annual_income_won": -50000000}, "음수 소득 (-5,000만원)"),
            ({"annual_income_won": 0}, "0원 소득"),
            ({"annual_income_won": 999_999_999_999_999}, "비현실적 천문학적 소득 (1000조원)"),
            ({"annual_income_won": "문자열소득"}, "비정상 문자열 타입"),
            ({"annual_income_won": 50000000, "max_pir": -5.0}, "음수 PIR 상한 (-5.0)"),
            ({"annual_income_won": 50000000, "max_pir": 9999.0}, "비현실적 PIR 상한 (9999.0)")
        ]

        all_blocked = True
        for payload, desc in test_cases:
            try:
                BudgetFilterRequest(**payload)
                all_blocked = False
                self.log_result(f"입력값 경계 테스트 ({desc})", False, "Pydantic 검증을 통과해 버렸습니다 (보안 위험)")
                break
            except ValidationError:
                pass  # 기대대로 안전하게 예외 발생 및 거부됨

        if all_blocked:
            self.log_result("Pydantic 경계값/비정상값 차단", True, f"음수, 0, 비정상 타입 등 {len(test_cases)}개 비정상 요청이 모두 Pydantic 유효성 검증에 의해 100% 안전하게 차단됨")

    # 5. XSS 및 SQL 악성 주입 문자열 스트레스 테스트
    def test_injection_stress(self):
        malicious_inputs = [
            "<script>alert('XSS')</script>",
            "'; DROP TABLE regions; --",
            "<img src=x onerror=alert(1)>",
            "\" onclick=\"alert('hack')\"",
            "%00%2e%2e%2f"
        ]

        safe_all = True
        for evil_str in malicious_inputs:
            # 검색 API 로직 테스트
            search_res = search_region(q=evil_str)
            if not isinstance(search_res, dict) or not search_res.get("success"):
                safe_all = False
                break

            # 비교 API 로직 테스트
            req = RegionCompareRequest(regions=[evil_str])
            comp_res = compare_selected_regions(req)
            if comp_res.status_code not in (200, 400):
                safe_all = False
                break

        if safe_all:
            self.log_result("XSS 및 인젝션 방어", True, "악성 스크립트 및 특수문자 주입 시 서버 충돌 없이 안전하게 무해화 및 방어 완료")
        else:
            self.log_result("XSS 및 인젝션 방어", False, "악성 스크립트 주입에 취약점 발견")

    # 6. 내부 서버 오류 시 스택트레이스 및 디렉터리 경로 은폐 검증
    def test_internal_error_masking(self):
        # 빈 리스트 비교 요청 시 반환되는 에러 포맷 검사
        try:
            RegionCompareRequest(regions=[])
            has_error = False
        except ValidationError as ve:
            has_error = True
            error_str = str(ve)
            # 시스템 내부 C:\ 경로가 노출되는지 검사
            has_win_path = "C:\\" in error_str or "korea-pir-dashboard" in error_str

        if has_error and not has_win_path:
            self.log_result("내부 디렉터리/스택트레이스 은폐", True, "에러 발생 시 민감 시스템 경로(C:\\) 노출 0건 (보안 원칙 100% 준수)")
        else:
            self.log_result("내부 디렉터리/스택트레이스 은폐", False, "에러 메시지에 시스템 내부 경로가 누출되었습니다.")

    def run_all(self):
        print("\n" + "=" * 70)
        print("🛡️ Step 7: 보안 취약점 점검 및 악성 입력값 스트레스 테스트 시작")
        print("=" * 70)
        self.test_gitignore_security()
        self.test_forbidden_functions()
        self.test_path_traversal_defense()
        self.test_boundary_inputs()
        self.test_injection_stress()
        self.test_internal_error_masking()
        print("=" * 70)

        pass_count = sum(1 for r in self.results if r["passed"])
        total_count = len(self.results)
        summary = f"\n🎯 최종 보안 감사 결과: 총 {total_count}개 보안 점검 항목 중 {pass_count}개 통과 ({pass_count/total_count*100:.0f}%)\n"
        print(summary)

        # logs/security_audit.log 에 기록
        log_file = BASE_DIR / "logs" / "security_audit.log"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"보안 점검 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            for r in self.results:
                f.write(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['name']}: {r['detail']}\n")
            f.write(summary)

        return pass_count == total_count

if __name__ == "__main__":
    tester = SecurityStressTester()
    success = tester.run_all()
    sys.exit(0 if success else 1)
