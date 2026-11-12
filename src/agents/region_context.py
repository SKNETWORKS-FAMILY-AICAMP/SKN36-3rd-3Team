"""UI에서 명시적으로 선택한 지역을 LLM 노드에 안전하게 전달한다."""
from __future__ import annotations
from typing import Any


def selected_region(region: dict[str, Any] | None) -> str | None:
    """선택된 시·도/시군구만 반환. nationwide/미선택이면 None."""
    if not isinstance(region, dict) or region.get("kind") != "region":
        return None
    sido = str(region.get("sido_name") or "").strip()
    sigungu = str(region.get("sigungu_name") or "").strip()
    return " ".join(v for v in (sido, sigungu) if v) or None


def region_guidance(region: dict[str, Any] | None) -> str:
    selected = selected_region(region)
    if selected:
        return (
            f"사용자가 UI에서 선택한 거주/검색 지역은 '{selected}'입니다. "
            "이미 확인된 지역이므로 다시 묻지 마세요. "
            "검색 결과가 부족하면 지역을 다시 묻지 말고 필요한 지원 종류나 상황을 질문하세요. "
            "전국 공통 제도와 해당 지역에서 확인된 정책만 구분해 설명하세요. "
            "선택 지역에 대한 검색 후보가 없더라도 정책이 존재하지 않는다고 단정하지 마세요."
        )
    return "UI에서 별도 지역 정보가 제공되지 않았습니다. 필요한 경우 지역을 질문할 수 있습니다."
