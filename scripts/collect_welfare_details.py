
import os
import json
import time
import random
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

# =====================================
# 1. 기본 설정
# =====================================

API_KEY = os.environ["DATA_API_KEY"]

API_URL = (
    "http://apis.data.go.kr/B554287/"
    "NationalWelfareInformationsV001/"
    "NationalWelfaredetailedV001"
)

DATA_DIR = Path("welfare_data")
DETAIL_DIR = DATA_DIR / "details"

DETAIL_DIR.mkdir(parents=True, exist_ok=True)

LIST_PATH = DATA_DIR / "welfare_list.json"
FAIL_PATH = DATA_DIR / "detail_failures.json"

# API 요청 사이 대기 시간
REQUEST_DELAY = 2

# 일시적 오류 재시도 횟수
MAX_RETRIES = 3

# =====================================
# 2. 기존 목록 불러오기
# =====================================

with open(LIST_PATH, "r", encoding="utf-8") as f:
    services = json.load(f)

print("=" * 50)
print("중앙부처 복지서비스 상세정보 수집 시작")
print(f"전체 서비스: {len(services)}건")
print("=" * 50)

# =====================================
# 3. XML 응답 검사
# =====================================

def validate_xml(content, expected_id):
    root = ET.fromstring(content)

    result_code = root.findtext("resultCode")
    result_message = root.findtext("resultMessage")

    if result_code != "0":
        raise ValueError(
            f"API 응답 오류: {result_code} / {result_message}"
        )

    returned_id = root.findtext("servId")

    if returned_id != expected_id:
        raise ValueError(
            f"서비스 ID 불일치: {returned_id}"
        )

    if not root.findtext("servNm"):
        raise ValueError("서비스명이 없습니다.")

    return root

# =====================================
# 4. API 요청 함수
# =====================================

def fetch_detail(serv_id):

    params = {
        "serviceKey": API_KEY,
        "servId": serv_id
    }

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = requests.get(
                API_URL,
                params=params,
                timeout=30
            )

            # 호출 제한 또는 인증 문제
            if response.status_code in [401, 403, 429]:
                raise RuntimeError(
                    f"HTTP {response.status_code}: "
                    f"{response.text[:300]}"
                )

            response.raise_for_status()

            validate_xml(response.content, serv_id)

            return response.content

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ) as e:

            print(f"  일시적 네트워크 오류: {e}")

            if attempt == MAX_RETRIES:
                raise

            wait = min(30, 2 ** attempt + random.random())
            print(f"  {wait:.1f}초 후 재시도")
            time.sleep(wait)

        except requests.exceptions.HTTPError as e:

            status = e.response.status_code

            if status not in [500, 502, 503, 504]:
                raise

            if attempt == MAX_RETRIES:
                raise

            wait = min(30, 2 ** attempt + random.random())
            print(f"  서버 오류 {status}, {wait:.1f}초 대기")
            time.sleep(wait)

    raise RuntimeError("최대 재시도 횟수 초과")

# =====================================
# 5. 기존 파일 검증 및 수집
# =====================================

success = 0
skipped = 0
failed = []

try:
    for index, service in enumerate(services, 1):

        serv_id = service.get("servId")

        if not serv_id:
            failed.append({
                "index": index,
                "error": "servId 없음"
            })
            continue

        output_path = DETAIL_DIR / f"{serv_id}.xml"

        # 기존 파일이 있으면 내용까지 검증
        if output_path.exists():

            try:
                validate_xml(
                    output_path.read_bytes(),
                    serv_id
                )

                skipped += 1
                print(
                    f"[{index}/{len(services)}] "
                    f"기존 파일 확인: {serv_id}"
                )
                continue

            except Exception as e:
                print(
                    f"기존 파일 검증 실패: {serv_id} / {e}"
                )
                print("해당 파일을 다시 수집합니다.")

        try:
            content = fetch_detail(serv_id)

            # 저장 도중 중단되어도 기존 파일 보호
            temp_path = output_path.with_suffix(".xml.tmp")
            temp_path.write_bytes(content)
            os.replace(temp_path, output_path)

            success += 1

            print(
                f"[{index}/{len(services)}] "
                f"수집 성공: {serv_id}"
            )

        except Exception as e:

            error_message = str(e)

            failed.append({
                "servId": serv_id,
                "error_type": type(e).__name__,
                "error": error_message
            })

            print("\n" + "=" * 50)
            print("API 수집 오류 발생")
            print(f"서비스 ID: {serv_id}")
            print(f"오류 유형: {type(e).__name__}")
            print(f"오류 내용: {error_message}")
            print("=" * 50)

            # 연속 오류 방지를 위해 즉시 중단
            print("추가 API 호출을 중단합니다.")
            break

        time.sleep(REQUEST_DELAY)

except KeyboardInterrupt:
    print("\n사용자가 수집을 중단했습니다.")

finally:
    with open(FAIL_PATH, "w", encoding="utf-8") as f:
        json.dump(
            failed,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("\n" + "=" * 50)
    print("수집 작업 종료")
    print(f"이번 실행 신규 수집: {success}건")
    print(f"기존 정상 파일: {skipped}건")
    print(f"이번 실행 실패: {len(failed)}건")
    print(f"확인된 정상 파일: {success + skipped}건")
    print("=" * 50)
