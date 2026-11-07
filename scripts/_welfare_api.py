"""중앙부처 복지서비스 OpenAPI 공통 유틸리티.

- 프로젝트 루트 .env 자동 읽기 (DATA_API_KEY)
- HTTPS, 디코딩된 서비스 키 사용
- 오류 출력 시 API 키/요청 URL 노출 방지
- 스크립트 실행 디렉터리에 관계없는 데이터 경로
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote
import xml.etree.ElementTree as ET

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw" / "welfare"
LIST_URL = (
    "https://apis.data.go.kr/B554287/"
    "NationalWelfareInformationsV001/NationalWelfarelistV001"
)
DETAIL_URL = (
    "https://apis.data.go.kr/B554287/"
    "NationalWelfareInformationsV001/NationalWelfaredetailedV001"
)


class WelfareAPIError(Exception):
    """요청 URL이나 인증키가 포함되지 않는 안전한 API 오류."""


def load_api_key() -> str:
    """프로젝트 루트 .env를 우선 사용하고 없으면 환경변수로 대체."""
    env_file = PROJECT_ROOT / ".env"
    if env_file.is_file():
        raw_key = None
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            name, value = text.split("=", 1)
            if name.strip() == "DATA_API_KEY":
                raw_key = value.strip()
                break
        if raw_key is None:
            raise WelfareAPIError(".env에 DATA_API_KEY 항목이 없습니다. DATA_API_KEY=인증키 형식으로 입력하세요.")
    else:
        raw_key = os.environ.get("DATA_API_KEY", "").strip()

    # .env에서 키 전체가 따옴표로 감싸졌을 때도 안전하게 제거.
    key = raw_key.strip().strip('"').strip("'").strip()
    # 인코딩 인증키를 붙여넣어도 requests가 이중 인코딩하지 않도록 디코딩.
    # '+'는 인증키의 실제 문자일 수 있으므로 unquote_plus를 사용하지 않음.
    if re.search(r"%[0-9A-Fa-f]{2}", key):
        key = unquote(key)
    if not key or key in {"실제키", "발급받은_디코딩_인증키", "YOUR_API_KEY"}:
        raise WelfareAPIError("API 키가 비어 있습니다. 프로젝트 최상위 .env에 DATA_API_KEY=발급키를 입력하세요.")
    if "\n" in key or "\r" in key or " " in key:
        raise WelfareAPIError("API 키에 공백 또는 줄바꿈이 있습니다. 인증키 입력을 확인하세요.")
    return key


def safe_get_xml(session: requests.Session, url: str, params: dict) -> tuple[bytes, ET.Element]:
    """한 번 호출하고 XML로 파싱. 오류 시 원본 URL(키 포함)을 절대 출력하지 않음."""
    try:
        response = session.get(url, params=params, timeout=30, allow_redirects=False)
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise WelfareAPIError(f"네트워크 연결 오류: {type(exc).__name__}") from None
    except requests.RequestException as exc:
        raise WelfareAPIError(f"HTTP 요청 오류: {type(exc).__name__}") from None

    status = response.status_code
    if status in (401, 403):
        raise WelfareAPIError(
            f"HTTP {status}: 인증키 형식, 해당 API 활용신청 승인/활성화 여부를 확인하세요."
        )
    if status == 429:
        raise WelfareAPIError("HTTP 429: 호출량 제한입니다. 사용량과 초기화 시간을 확인하세요.")
    if 300 <= status < 400:
        raise WelfareAPIError(f"HTTP {status}: API가 리다이렉트를 반환했습니다. 공식 요청 주소를 확인하세요.")
    if status != 200:
        raise WelfareAPIError(f"HTTP {status}: API 서버 응답 오류")

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        raise WelfareAPIError("API 응답을 XML로 해석할 수 없습니다. 응답 형식/서비스 상태를 확인하세요.") from None

    code = (root.findtext(".//resultCode") or "").strip()
    if code != "0":
        # API가 반환하는 메시지나 URL은 인증키를 포함할 수 있어 출력하지 않음.
        shown = code if re.fullmatch(r"[0-9A-Za-z_-]{1,30}", code) else "없음"
        raise WelfareAPIError(f"API 결과 오류(resultCode={shown}). 인증/호출 한도/파라미터 확인 필요")
    return response.content, root


def load_services() -> list[dict]:
    """목록을 읽고 기본 형식 및 ID 고유성 확인; 원본 수정 없음."""
    import json

    file = DATA_DIR / "welfare_list.json"
    if not file.is_file():
        raise WelfareAPIError(
            f"목록 JSON이 없습니다: {file}\n"
            "원본 Data-Extraction 브랜치라면 'git restore -- data/raw/welfare/welfare_list.json' 실행 후 다시 시도하세요."
        )
    try:
        rows = json.loads(file.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError):
        raise WelfareAPIError("welfare_list.json이 올바른 UTF-8 JSON이 아닙니다.") from None
    if not isinstance(rows, list) or not rows or not all(isinstance(x, dict) for x in rows):
        raise WelfareAPIError("목록 JSON은 하나 이상의 서비스 객체를 담은 배열이어야 합니다.")
    ids = [str(x.get("servId") or "").strip() for x in rows]
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", sid) for sid in ids):
        raise WelfareAPIError("목록 JSON에서 서비스 ID가 누락되었거나 형식이 잘못되었습니다.")
    if len(ids) != len(set(ids)):
        raise WelfareAPIError("목록 JSON에서 중복 servId가 발견되었습니다. 수집 데이터부터 검증하세요.")
    return rows


def validate_detail_xml(raw: bytes, expected_id: str) -> None:
    """저장된 기존 XML까지 포함해 결과코드·ID·서비스명 검사."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("XML 파싱 오류") from None
    if (root.findtext(".//resultCode") or "").strip() != "0":
        raise ValueError("API resultCode 비정상")
    if (root.findtext("servId") or "").strip() != expected_id:
        raise ValueError("서비스 ID 불일치")
    if not (root.findtext("servNm") or "").strip():
        raise ValueError("서비스명 누락")
