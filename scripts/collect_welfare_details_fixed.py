"""중앙부처 복지서비스 상세정보 수집기 (기존 파일 보존/이어받기).

위치: <프로젝트>/scripts/collect_welfare_details.py
데이터: <프로젝트>/data/raw/welfare/
실행: py scripts/collect_welfare_details.py
사전 점검(호출 없음): py scripts/collect_welfare_details.py --check
필수 라이브러리: requests
"""

import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

# 스크립트 위치를 기준으로 계산하므로 현재 터미널 위치와 무관합니다.
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "raw" / "welfare"
LIST_FILE = DATA_DIR / "welfare_list.json"
DETAIL_DIR = DATA_DIR / "details"
LOG_FILE = DATA_DIR / "detail_failures.json"

API_URL = (
    "http://apis.data.go.kr/B554287/"
    "NationalWelfareInformationsV001/NationalWelfaredetailedV001"
)
MAX_CALLS_PER_RUN = 100  # 상세조회: 활용 신청 화면 기준 일일 100회 (재시도 포함)
WAIT_SECONDS = 2.0
RETRY_COUNT = 2  # 일시적 네트워크/서버 오류에만 최대 2회 추가 시도


class StopCollection(Exception):
    """재시도하지 않고 수집을 멈춰야 하는 상황."""


def load_api_key():
    """환경변수 우선, 없으면 프로젝트 루트의 .env에서 인증키를 읽습니다."""
    key = os.environ.get("DATA_API_KEY", "").strip()
    if not key or "발급받은" in key or "여기에" in key:
        env_file = ROOT / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                name, sep, value = line.strip().partition("=")
                if sep and name.strip() == "DATA_API_KEY":
                    key = value.strip().strip('"').strip("'")
                    break
    if not key or "발급받은" in key or "여기에" in key:
        raise SystemExit(
            "API 인증키가 없습니다. 최상위 .env에 DATA_API_KEY=실제키 를 "
            "설정하거나 PowerShell 환경변수에 설정하세요."
        )
    return key


def validate_xml(raw, expected_id):
    """서비스 ID, 결과 코드, 필수 필드를 확인합니다."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("올바른 XML 응답이 아닙니다") from None

    code = (root.findtext("resultCode") or "").strip()
    if code != "0":
        api_error = (
            root.findtext(".//errMsg")
            or root.findtext(".//returnAuthMsg")
            or root.findtext("resultMessage")
            or "상세 오류 메시지 없음"
        )
        raise ValueError(f"API 오류 (resultCode={code or '없음'}): {api_error[:150]}")

    if (root.findtext("servId") or "").strip() != expected_id:
        raise ValueError("서비스 ID 불일치")
    if not (root.findtext("servNm") or "").strip():
        raise ValueError("서비스명 누락")


def fetch_detail(session, api_key, serv_id, usage):
    """API 요청. HTTP 429/인증 오류/비정상 XML이면 즉시 중단합니다."""
    for attempt in range(RETRY_COUNT + 1):
        if usage["calls"] >= MAX_CALLS_PER_RUN:
            raise StopCollection("이번 실행의 API 요청 100회에 도달했습니다")
        usage["calls"] += 1

        try:
            response = session.get(
                API_URL,
                params={"serviceKey": api_key, "callTp": "D", "servId": serv_id},
                timeout=30,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == RETRY_COUNT:
                raise StopCollection(f"네트워크 오류 반복: {type(exc).__name__}") from None
            time.sleep(3 * (attempt + 1))
            continue
        except requests.RequestException as exc:
            # 요청 URL에는 인증키가 포함될 수 있어 예외 전문을 출력하지 않습니다.
            raise StopCollection(f"요청 오류: {type(exc).__name__}") from None

        if response.status_code == 429:
            raise StopCollection("HTTP 429: 일일 호출 한도 초과 (초기화 후 재실행)")
        if response.status_code in (401, 403):
            raise StopCollection(f"HTTP {response.status_code}: 인증키 또는 사용 권한 확인 필요")
        if response.status_code in (500, 502, 503, 504):
            if attempt == RETRY_COUNT:
                raise StopCollection(f"서버 오류 반복: HTTP {response.status_code}")
            time.sleep(3 * (attempt + 1))
            continue
        if response.status_code != 200:
            raise StopCollection(f"HTTP {response.status_code}: 응답 확인 필요")

        try:
            validate_xml(response.content, serv_id)
        except ValueError as exc:
            raise StopCollection(str(exc).replace(api_key, "[REDACTED]")) from None
        return response.content

    raise StopCollection("요청 재시도 횟수를 초과했습니다")


def main():
    parser = argparse.ArgumentParser(description="복지서비스 상세 XML 이어받기 수집")
    parser.add_argument("--check", action="store_true", help="기존 파일만 검사 (API 호출 0회)")
    args = parser.parse_args()

    if not LIST_FILE.is_file():
        raise SystemExit(f"목록 JSON을 찾을 수 없습니다: {LIST_FILE}")
    services = json.loads(LIST_FILE.read_text(encoding="utf-8"))
    if not isinstance(services, list):
        raise SystemExit("목록 JSON은 서비스 객체의 배열이어야 합니다")
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)

    # 첫 실행 시 경로·기존 파일 정상 여부만 확인하는 모드
    if args.check:
        valid = invalid = 0
        for service in services:
            serv_id = str(service.get("servId") or "").strip()
            file = DETAIL_DIR / f"{serv_id}.xml"
            if not serv_id or not file.is_file():
                continue
            try:
                validate_xml(file.read_bytes(), serv_id)
                valid += 1
            except ValueError:
                invalid += 1
        print(f"전체 목록: {len(services)}건")
        print(f"정상 기존 상세 파일: {valid}건 / 비정상 기존 파일: {invalid}건")
        print(f"미수집 또는 재수집 필요: {len(services) - valid}건")
        print("--check 모드: API 호출 없이 종료했습니다.")
        return

    api_key = load_api_key()
    usage = {"calls": 0}
    previous = new = 0
    failures = []
    print(f"목록 {len(services)}건 / 회당 최대 {MAX_CALLS_PER_RUN}회 요청")
    print(f"저장 위치: {DETAIL_DIR}")

    with requests.Session() as session:
        try:
            for index, service in enumerate(services, 1):
                serv_id = str(service.get("servId") or "").strip()
                if not re.fullmatch(r"[A-Za-z0-9_-]+", serv_id):
                    failures.append({"index": index, "error": "서비스 ID 누락/형식 오류"})
                    continue

                output = DETAIL_DIR / f"{serv_id}.xml"
                if output.is_file():
                    try:
                        validate_xml(output.read_bytes(), serv_id)
                        previous += 1
                        continue
                    except ValueError:
                        print(f"[{index}/{len(services)}] 기존 XML 검증 실패 → 재수집: {serv_id}")

                if usage["calls"] >= MAX_CALLS_PER_RUN:
                    print("실행당 API 요청 제한에 도달하여 중단합니다.")
                    break

                try:
                    xml_data = fetch_detail(session, api_key, serv_id, usage)
                    temp = output.with_suffix(".xml.tmp")
                    temp.write_bytes(xml_data)
                    os.replace(temp, output)  # 정상 응답 검증 후 파일 저장
                    new += 1
                    print(f"[{index}/{len(services)}] 저장 성공: {serv_id} (요청 {usage['calls']}회)")
                    time.sleep(WAIT_SECONDS)
                except StopCollection as exc:
                    print(f"[{index}/{len(services)}] 수집 중단: {serv_id} / {exc}")
                    failures.append({"servId": serv_id, "error": str(exc)})
                    break
        except KeyboardInterrupt:
            print("\nCtrl+C 중단: 기존에 저장한 XML은 유지됩니다.")
        finally:
            LOG_FILE.write_text(
                json.dumps(
                    {"time_utc": datetime.now(timezone.utc).isoformat(),
                     "requests_this_run": usage["calls"], "failures": failures},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            print("\n===== 수집 결과 =====")
            print(f"기존 정상 파일(이번 순회에서 확인): {previous}건")
            print(f"신규 저장 파일: {new}건")
            print(f"이번 실행 API 요청 횟수(재시도 포함): {usage['calls']}회")
            print(f"실패/중단 기록: {LOG_FILE}")
            print("다시 실행하면 정상 저장된 파일은 자동으로 건너뜁니다.")


if __name__ == "__main__":
    main()
