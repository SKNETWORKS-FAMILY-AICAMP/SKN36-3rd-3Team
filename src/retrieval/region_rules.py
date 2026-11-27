"""지역 공통 규칙 (B1). 채팅 검색과 정책 목록이 같은 규칙을 쓰게 하려고 한곳에 모았다.
아직 기존 검색 코드에 연결하지 않았다.

- 시도 이름: 화면·위치 API·옛 데이터에서 오는 여러 이름을 4차(v3) 데이터의 이름으로 맞춘다.
- 지역 키: "시도|시군구". 4차 Qdrant payload 의 metadata.applies_to_keys 와 같은 모양이다.
- 적용 범위 판정: 고른 지역에 대해 자료 하나가 지역 정책 / 전국 자료 / 지역 미상 / 해당 없음 중 무엇인지.

지역 미상(시도에 등록됐지만 적용 시군구가 확정되지 않은 자료)은 답변 근거가 아니라 별도 목록으로만 쓴다.
시도 이름만으로 "시도 전체에 적용된다"고 보지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

# 4차 데이터(nationwide_2026_11_26)에 나오는 시도 16곳.
# 세종특별자치시는 시군구가 없어서 적용 지역이 확정된 정책이 없고, 지역 미상 자료(20건)만 있다.
SIDO_NAMES = (
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "충청북도", "충청남도", "전북특별자치도", "전남광주통합특별시", "경상북도", "경상남도", "제주특별자치도",
)
_ALIASES = {
    "서울": "서울특별시", "서울시": "서울특별시",
    "부산": "부산광역시", "부산시": "부산광역시",
    "대구": "대구광역시", "대구시": "대구광역시",
    "인천": "인천광역시", "인천시": "인천광역시",
    "대전": "대전광역시", "대전시": "대전광역시",
    "울산": "울산광역시", "울산시": "울산광역시",
    "세종": "세종특별자치시", "세종시": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원특별자치도", "강원도": "강원특별자치도",
    "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전라북도": "전북특별자치도",
    # 전라남도와 광주광역시는 4차 데이터에서 하나의 통합시로 묶여 있다.
    "전남": "전남광주통합특별시", "전라남도": "전남광주통합특별시", "광주광역시": "전남광주통합특별시",
    "경북": "경상북도", "경남": "경상남도",
    "제주": "제주특별자치도", "제주도": "제주특별자치도",
}
# "광주"만으로는 옛 광주광역시인지 경기도 광주시인지 알 수 없다. 추측하지 않고 되묻게 한다.
_AMBIGUOUS_SIDO = {"광주", "광주시"}
NATIONAL_KEY = "national"


class RegionError(ValueError):
    """지역 이름을 규칙에 맞게 풀 수 없을 때."""


class AmbiguousRegionError(RegionError):
    """이름 하나가 두 지역을 가리킬 수 있어 사용자에게 다시 물어야 할 때."""


class UnknownRegionError(RegionError):
    """현재 데이터에 없는 시도일 때."""


def normalize_sido(name: str | None) -> str | None:
    """시도 이름을 4차 데이터의 이름으로 바꾼다. 비어 있으면 None."""
    text = " ".join(str(name or "").split())
    if not text:
        return None
    if text in _AMBIGUOUS_SIDO:
        raise AmbiguousRegionError(f"{text!r}는 광주광역시(전남광주통합특별시)인지 경기도 광주시인지 알 수 없습니다.")
    text = _ALIASES.get(text, text)
    if text not in SIDO_NAMES:
        raise UnknownRegionError(f"현재 데이터에 없는 시도입니다: {text!r}")
    return text


def region_key(sido: str, sigungu: str) -> str:
    return f"{sido}|{sigungu}"


SELECTION_KINDS = ("none", "nationwide", "sido_only", "region")


@dataclass(frozen=True)
class RegionSelection:
    """사용자가 고른 지역.

    kind: none(고르지 않음) / nationwide(전국을 직접 고름) / sido_only(시도까지만) / region(시군구까지).
    "고르지 않음"과 "전국을 고름"은 다른 상태다. 전국을 고르면 지역 정책을 지역별 참고 후보로 보여 줄 수 있다.
    """
    kind: str
    sido: str | None = None
    sigungu: str | None = None

    def __post_init__(self) -> None:
        want = {"none": (False, False), "nationwide": (False, False), "sido_only": (True, False), "region": (True, True)}
        if self.kind not in want or (bool(self.sido), bool(self.sigungu)) != want[self.kind]:
            raise RegionError(f"선택 지역의 모양이 맞지 않습니다: kind={self.kind!r}, sido={self.sido!r}, sigungu={self.sigungu!r}")

    @property
    def key(self) -> str | None:
        return region_key(self.sido, self.sigungu) if self.kind == "region" else None


NO_REGION = RegionSelection("none")
NATIONWIDE = RegionSelection("nationwide")


def select_region(sido: str | None, sigungu: str | None = None) -> RegionSelection:
    """시도·시군구 이름으로 선택 지역을 만든다. 시군구 이름은 바꾸지 않는다(경기도 광주시는 그대로 광주시)."""
    sido_norm = normalize_sido(sido)
    sigungu_text = " ".join(str(sigungu or "").split())
    if not sido_norm:
        if sigungu_text:
            raise RegionError("시도 없이 시군구만 고를 수 없습니다.")
        return NO_REGION
    if not sigungu_text:
        return RegionSelection("sido_only", sido_norm)
    return RegionSelection("region", sido_norm, sigungu_text)


def selection_from_request(region: Mapping[str, Any] | None) -> RegionSelection:
    """채팅 요청의 region({kind, sido_name, sigungu_name})을 선택 지역으로 바꾼다.

    region 이 없으면 고르지 않은 것, kind 가 nationwide 면 전국을 직접 고른 것이다. 모르는 kind 는 오류.
    """
    if not region:
        return NO_REGION
    kind = region.get("kind")
    if kind == "nationwide":
        if region.get("sido_name") or region.get("sigungu_name"):
            raise RegionError("전국 선택에는 시도·시군구를 함께 줄 수 없습니다.")
        return NATIONWIDE
    if kind != "region":
        raise RegionError(f"모르는 지역 선택 종류입니다: {kind!r}")
    selection = select_region(region.get("sido_name"), region.get("sigungu_name"))
    if selection.kind == "none":
        raise RegionError("지역 선택인데 시도가 없습니다.")
    return selection


def keys_from_applies_to(applies_to: Iterable[Mapping[str, Any]] | None) -> list[str]:
    """청크 원본의 applies_to([{sido, sigungu}, ...])를 지역 키 목록으로. 적재 스크립트와 같은 규칙."""
    keys: list[str] = []
    for item in applies_to or []:
        sido, sigungu = str(item.get("sido") or "").strip(), str(item.get("sigungu") or "").strip()
        if not sido or not sigungu:
            raise RegionError(f"applies_to 항목에 시도 또는 시군구가 없습니다: {dict(item)!r}")
        key = region_key(sido, sigungu)
        if key not in keys:
            keys.append(key)
    return keys


# 적용 범위 판정 결과
LOCAL = "local"            # 고른 지역에 적용되는 지역 정책 (답변 근거). 시도만 골랐으면 "그 시도 안의 지역 정책 후보"
NATIONAL = "national"      # 전국 자료 (답변 근거)
REFERENCE = "regional_reference"   # 전국을 골랐을 때의 지역 정책: 어느 지역 것인지 밝힌 참고 후보
UNVERIFIED = "unverified"  # 고른 시도에 등록됐지만 적용 지역 미상 (별도 목록. 답변 근거 아님)
OTHER = "other"            # 다른 지역 자료 등 (쓰지 않음)


def classify_scope(metadata: Mapping[str, Any], selection: RegionSelection) -> str:
    """4차 payload 의 metadata 하나가 고른 지역에 대해 어떤 자료인지 판정한다.

    metadata 에는 record_type, applies_to_keys, sido_name 이 있어야 한다(4차 적재 스크립트가 넣는 값).
    - 전국 자료는 applies_to_keys 에 "national" 이 명시된 것만이다. PDF(guideline)라는 이유만으로 전국 자료로 보지 않는다.
    - 시군구까지 골랐으면 그 지역 키가 applies_to_keys 에 있을 때만 지역 정책.
    - 시도까지만 골랐으면 그 시도의 시군구에 적용되는 정책이 지역 정책 후보다. 시도 전체에 적용된다는 뜻이 아니므로
      어느 시군구 것인지는 따로 보여 줘야 한다.
    - 전국을 직접 골랐으면 지역 정책은 지역별 참고 후보다.
    - 지역을 고르지 않았으면 지역 정책을 쓰지 않는다.
    """
    keys = metadata.get("applies_to_keys")
    if not isinstance(keys, (list, tuple)):
        raise RegionError("metadata.applies_to_keys 가 없습니다. 4차 방식으로 적재한 자료가 아닙니다.")
    for k in keys:   # 키는 "national" 이거나 "시도|시군구"(둘 다 비어 있지 않음)여야 한다.
        parts = str(k).split("|")
        if k != NATIONAL_KEY and not (isinstance(k, str) and len(parts) == 2 and all(x.strip() for x in parts)):
            raise RegionError(f"지역 키의 모양이 잘못됐습니다: {k!r}")
    if NATIONAL_KEY in keys:
        return NATIONAL
    if metadata.get("record_type") != "policy":
        return OTHER   # 전국 표시가 없는 PDF 등은 근거로 쓰지 않는다.
    if selection.kind == "none":
        return OTHER
    if selection.kind == "nationwide":
        return REFERENCE if keys else OTHER
    if not keys:
        return UNVERIFIED if metadata.get("sido_name") == selection.sido else OTHER
    if selection.kind == "region":
        return LOCAL if selection.key in keys else OTHER
    prefix = f"{selection.sido}|"
    return LOCAL if any(str(k).startswith(prefix) for k in keys) else OTHER
