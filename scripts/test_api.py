"""중앙부처 복지서비스 목록 API 연결 검사 (1회 요청).

사용: uv run python scripts/test_api.py
설정: 프로젝트 최상위 .env 에 DATA_API_KEY=새_디코딩_인증키
실패하더라도 요청 URL/인증키를 출력하지 않습니다.
"""

import requests
from _welfare_api import LIST_URL, WelfareAPIError, load_api_key, safe_get_xml


def main() -> None:
    key = load_api_key()
    with requests.Session() as session:
        _, root = safe_get_xml(
            session,
            LIST_URL,
            {
                "serviceKey": key,
                "callTp": "L",
                "pageNo": 1,
                "numOfRows": 5,
                "srchKeyCode": "001",
            },
        )

    count = root.findtext("totalCount")
    items = root.findall(".//servList")
    print("HTTP 상태: 200")
    print("API 결과 코드: 0")
    print("전체 서비스 수:", count or "정보 없음")
    print("첫 페이지 정책:")
    for service in items:
        print(" -", service.findtext("servId", ""), service.findtext("servNm", ""))
    print("API 연결 확인 완료 (인증키 비공개)")


if __name__ == "__main__":
    try:
        main()
    except WelfareAPIError as exc:
        raise SystemExit(str(exc)) from None
