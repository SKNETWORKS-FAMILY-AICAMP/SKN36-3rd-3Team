"""Convert browser GPS coordinates to province + municipality using Kakao Local REST API.

Frontend contract: POST /api/location/region with latitude/longitude.
No coordinate persistence, analytics or request logging is implemented here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/location", tags=["Location"])
KAKAO_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90, description="위도(WGS84)")
    longitude: float = Field(ge=-180, le=180, description="경도(WGS84)")


class LocatedRegion(BaseModel):
    sido_name: str
    sigungu_name: str | None = None
    region_code: str | None = None


def _error(status_code: int, code: str, message: str, retryable: bool) -> JSONResponse:
    # Matches the frontend/src/api/location.ts error adapter.
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "retryable": retryable},
    )


def _extract_region(documents: object) -> LocatedRegion | None:
    """Prefer administrative-area (H) record; return only city/province + municipality."""
    if not isinstance(documents, list):
        return None
    found = [d for d in documents if isinstance(d, dict)]
    if not found:
        return None

    region = next((d for d in found if d.get("region_type") == "H"), found[0])
    sido = str(region.get("region_1depth_name") or "").strip()
    sigungu = str(region.get("region_2depth_name") or "").strip()
    code = str(region.get("code") or "").strip()

    # Standardise Kakao administrative labels to the values used by RegionSheet.
    sido_aliases = {
        "서울": "서울특별시", "경기": "경기도", "전남": "전라남도",
        "서울특별시": "서울특별시", "경기도": "경기도", "전라남도": "전라남도",
    }
    sido = sido_aliases.get(sido, sido)

    # Kakao can return '성남시 분당구' / '수원시 영통구'. This app selects
    # Gyeonggi region at city level (e.g. 성남시, 수원시).
    if sido == "경기도" and " " in sigungu:
        first = sigungu.split()[0]
        if first.endswith(("시", "군")):
            sigungu = first

    if not sido:
        return None
    return LocatedRegion(
        sido_name=sido,
        sigungu_name=sigungu or None,
        region_code=code or None,
    )


def _kakao_key() -> str | None:
    # In normal runs, dotenv is already installed. Load the repository root
    # .env if present without overriding real process environment variables.
    try:
        from dotenv import load_dotenv
        repo_root = Path(__file__).resolve().parents[3]
        load_dotenv(repo_root / ".env", override=False)
    except ImportError:
        pass
    return os.getenv("KAKAO_REST_API_KEY") or os.getenv("KAKAO_REST_API_KEY_LOCAL")


@router.post("/region", response_model=LocatedRegion)
def reverse_geocode(coords: Coordinates):
    key = _kakao_key()
    if not key:
        return _error(
            503, "location_not_configured",
            "카카오 REST API 키가 설정되지 않았어요. 서버 .env를 확인해 주세요.", False,
        )

    query = urlencode({
        "x": coords.longitude,  # WGS84 longitude
        "y": coords.latitude,   # WGS84 latitude
        "input_coord": "WGS84",
    })
    request = Request(
        f"{KAKAO_URL}?{query}",
        headers={"Authorization": f"KakaoAK {key}", "Accept": "application/json"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except HTTPError as exc:
        # Do not return API keys or raw upstream response to clients.
        if exc.code in (401, 403):
            return _error(503, "kakao_authorization_error",
                          "카카오 API 인증이 실패했어요. REST API 키와 사용 설정을 확인해 주세요.", False)
        if exc.code == 429:
            return _error(503, "kakao_rate_limit",
                          "위치 확인 요청이 많아요. 잠시 후 다시 시도해 주세요.", True)
        return _error(502, "kakao_upstream_error",
                      "카카오 위치 조회에 실패했어요. 잠시 후 다시 시도해 주세요.", True)
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return _error(502, "kakao_network_error",
                      "현재 위치 정보를 변환하지 못했어요. 잠시 후 다시 시도해 주세요.", True)

    found = _extract_region(payload.get("documents") if isinstance(payload, dict) else None)
    if found is None:
        return _error(404, "region_not_found",
                      "현재 좌표의 행정구역을 찾지 못했어요. 지역을 직접 선택해 주세요.", False)
    return found
