"""4차(v3) 검색 노드: 묶음별 검색을 채팅 흐름에 연결한다 (B3).

RAG_RETRIEVAL_MODE=v3 일 때만 그래프에 들어간다. 3차(legacy_v1)·mock 경로는 welfare_retrieval.py 를 그대로 쓴다.

3차와 다른 점
- 화면에서 고른 지역을 검색 전에 Qdrant 필터로 쓴다 (3차는 검색 뒤에 걸렀다).
- 답변 근거(documents)는 지역 정책 + 전국 자료다. 전국을 직접 골랐을 때는 전국 자료 + 지역별 참고 후보다.
- 적용 지역이 확정되지 않은 자료(unverified)는 근거에 넣지 않고, LLM 에도 넘기지 않는다. 화면·API 용 별도 목록으로만 둔다.
- Neo4j 는 같은 데이터 버전을 적재하기 전이라 쓰지 않는다 (벡터 검색만).
- 3차의 식사 질문 전용 재검색(fallback_search_query)은 넣지 않았다. 먼저 측정한 뒤 필요하면 추가한다.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .state import WelfareState
from .welfare_retrieval import build_search_question

V3_RESULT_MODE = "v3_grouped"   # retrieval_result["mode"]. 근거 검사·답변 단계가 이 값으로 같은 요청의 방식을 안다.

REGION_CLARIFY_ANSWERS = {
    "ambiguous": (
        "말씀하신 지역이 광주광역시인지 경기도 광주시인지 알 수 없어요. "
        "지역을 다시 골라 주시겠어요?"
    ),
    "unknown": (
        "고르신 지역은 지금 가진 자료에서 찾을 수 없어요. "
        "시·도와 시·군·구를 다시 골라 주시겠어요?"
    ),
    "invalid": "지역 선택을 확인하지 못했어요. 시·도와 시·군·구를 다시 골라 주시겠어요?",
}


def is_v3_result(result: dict[str, Any] | None) -> bool:
    return isinstance(result, dict) and result.get("mode") == V3_RESULT_MODE


def make_grouped_retrieval_node(
    search: Callable[..., dict[str, Any]] | None = None,
    *,
    settings: Any = None,
    region_keys: Callable[[], list[str]] | None = None,
    local_k: int = 5,
    national_k: int = 3,
    unverified_k: int = 3,
):
    """묶음별 검색 노드를 만든다. search 를 주지 않으면 실제 search_grouped 를 쓴다.

    실제 검색을 쓸 때는 노드를 만드는 시점의 설정(컬렉션·데이터 버전·서버)을 그대로 붙잡아 둔다.
    그래프를 만든 뒤 환경 변수가 바뀌어도 같은 그래프가 다른 컬렉션을 검색하지 않게 하기 위해서다.
    """
    if search is None and settings is None:
        from src.retrieval.config import load_settings
        settings = load_settings()
    if search is None and region_keys is None:
        region_keys = default_region_keys(settings)
    region_index = region_index_loader(region_keys)

    def node(state: WelfareState) -> WelfareState:
        from src.retrieval import region_rules as R

        try:
            selection = R.selection_from_request(state.get("region"))
        except R.RegionError as exc:
            # 지역 이름을 풀 수 없으면 추측해서 검색하지 않는다. 지역 확인 분기로 보낸다.
            kind = ("ambiguous" if isinstance(exc, R.AmbiguousRegionError)
                    else "unknown" if isinstance(exc, R.UnknownRegionError) else "invalid")
            result = _empty_result(state["question"])
            result["region_error"] = {"kind": kind, "message": str(exc)}
            return {"retrieved_docs": [], "graph_results": [], "retrieval_result": result}

        screen = selection
        resolution = None
        original_question = None
        if region_keys is not None:
            resolution, original_question = _resolve_from_text(state, selection, region_index())
            if resolution.kind == "ask":
                # 화면 지역과 질문 속 지역이 다르거나 이름이 여러 곳에 있으면, 추측해서 검색하지 않고 묻는다.
                result = _empty_result(state["question"])
                result["region_error"] = {"kind": "region_conflict", "message": resolution.message,
                                          "choices": list(resolution.choices)}
                return {"retrieved_docs": [], "graph_results": [], "retrieval_result": result}
            selection = resolution.selection

        # 지역을 묻는 말에 답한 차례("횡성군 기준")면 원래 질문으로 검색한다 (답한 말만으로는 무엇을 찾을지 모른다).
        search_question = original_question or state.get("search_query") or build_search_question(state)
        rewritten = False
        if selection != screen:
            # 의도 확인은 화면 지역만 알고 검색어를 만든다. 검색 지역을 바꿨으면 검색어 속 지역 이름도 맞춘다.
            new_question = _align_region_words(search_question, screen, selection, region_index())
            rewritten = new_question != search_question
            search_question = new_question
        if search is None:
            from src.retrieval import grouped_search
            out = grouped_search.search_grouped(search_question, selection, settings=settings,
                                                local_k=local_k, national_k=national_k, unverified_k=unverified_k)
        else:
            out = search(search_question, selection, local_k=local_k, national_k=national_k, unverified_k=unverified_k)

        # 답변 근거: 지역 정책 먼저, 그다음 전국 자료. 전국을 직접 골랐으면 지역 정책 대신 지역별 참고 후보.
        docs = list(out["local"]) + list(out["national"]) + list(out["reference"])
        result = _empty_result(search_question)
        result.update({
            "documents": docs,
            "has_evidence": bool(docs),
            "selection": {
                "kind": selection.kind, "sido": selection.sido, "sigungu": selection.sigungu,
                # screen: 화면에서 고른 지역만 / question: 질문에서 말한 지역으로 정함
                "source": "question" if resolution and resolution.kind in ("use", "confirmed") else "screen",
                "screen": {"kind": screen.kind, "sido": screen.sido, "sigungu": screen.sigungu},
                "compared": [" ".join(x for x in r if x) for r in (resolution.compared if resolution else [])],
            },
            # 근거가 아닌 별도 목록. LLM 프롬프트에 넣지 않는다.
            "unverified_candidates": list(out["unverified"]),
            "grouped_info": out["info"],
            "diagnostics": {"returned": dict(out["info"].get("returned") or {}), "dropped": dict(out["info"].get("dropped") or {}),
                            "short": list(out["info"].get("short") or [])},
        })
        out_state = {"retrieved_docs": docs, "graph_results": [], "retrieval_result": result}
        if original_question or rewritten:
            out_state["search_query"] = search_question   # 근거 판정도 같은 질문·지역 기준으로 보게 한다
        return out_state

    return node


def default_region_keys(settings: Any) -> Callable[[], list[str]]:
    """실제 검색에서 쓸 지역 이름 목록 (데이터의 지역 키). 검색을 주입한 시험에서는 region_keys 를 줄 때만 읽는다."""
    def region_keys() -> list[str]:
        from src.retrieval import grouped_search
        return grouped_search.known_region_keys(settings)
    return region_keys


def region_index_loader(region_keys: Callable[[], list[str]] | None) -> Callable[[], Any]:
    """지역 이름표를 처음 쓸 때 한 번만 만든다."""
    cache: list = []

    def load():
        if not cache:
            from src.retrieval.region_mentions import RegionIndex
            cache.append(RegionIndex.from_keys(region_keys()))
        return cache[0]
    return load


def wrap_intent_for_region_answers(intent_node: Callable, region_keys: Callable[[], list[str]] | None) -> Callable:
    """직전에 우리가 지역을 물었고 사용자가 실제 지역 이름으로 답했으면, 의도 확인 LLM 을 거치지 않고 원래 질문으로 검색한다.

    "경기도 성남시"처럼 지역 이름만 있는 답은 의도 확인이 모호한 말로 보고 되묻기로 보내는 일이 있다(실측).
    지역 이름이 없는 답("모르겠어요")이나 거절("횡성 말고요")은 평소처럼 의도 확인으로 보낸다
    (거절 판단은 region_mentions.resolve 가 한다).
    """
    if region_keys is None:
        return intent_node
    load = region_index_loader(region_keys)

    def node(state: dict) -> dict:
        from src.retrieval import region_rules as R
        from src.retrieval.region_mentions import CLARIFY_MARK, resolve

        history = [h for h in state.get("history") or [] if isinstance(h, dict)]
        last = history[-1] if history else {}
        text_of = lambda t: str(t.get("content") or t.get("text") or "")  # noqa: E731
        if last.get("role") == "assistant" and CLARIFY_MARK in text_of(last):
            try:
                screen = R.selection_from_request(state.get("region"))
            except R.RegionError:
                screen = R.NO_REGION
            res = resolve(screen, state["question"], load(), answering_region_question=True)
            if res.kind != "ask" and res.mentioned:
                before = [text_of(t) for t in history[:-1] if t.get("role") == "user"]
                return {"intent": "search", "search_query": before[-1] if before else state["question"],
                        "clarification_question": ""}
        return intent_node(state)
    return node


def _resolve_from_text(state: WelfareState, selection: Any, index: Any) -> tuple[Any, str | None]:
    """검색 지역을 정한다. 돌려주는 값: (결정, 지역 질문에 답한 차례면 원래 질문).

    1) 앞 대화에서 지역을 물어 사용자가 고른 지역이 있으면 그것을 기준으로 삼는다 (화면 지역보다 앞선다).
    2) 지금 질문 속 지역 이름을 본다. 직전 말이 지역을 묻는 말이면 사용자의 답으로 받는다.
    3) 지금 질문에 지역이 없으면 최근 사용자 말(최근 6개 메시지 안)에서 찾되, 좁히기만 하고 묻지는 않는다.
    """
    from src.retrieval import region_rules as R
    from src.retrieval.region_mentions import CLARIFY_MARK, Resolution, confirmed_from_history, resolve

    history = [h for h in state.get("history") or [] if isinstance(h, dict)]
    text_of = lambda t: str(t.get("content") or t.get("text") or "")  # noqa: E731
    last = history[-1] if history else {}
    answering = last.get("role") == "assistant" and CLARIFY_MARK in text_of(last)
    confirmed = confirmed_from_history(selection, history, index)
    base = confirmed or selection
    res = resolve(base, state["question"], index, answering_region_question=answering)
    if res.refused:
        # 지역을 묻는 말에 거절했다. 앞 대화의 지역으로 덮어쓰지 않고, 화면 지역 그대로 새 질문으로 본다.
        return Resolution("keep", selection, refused=True), None
    original = None
    if answering and res.kind != "ask" and res.mentioned:
        # 실제로 지역을 골라 답했을 때만 원래 질문으로 돌아간다 ("모르겠어요" 같은 답은 새 질문으로 본다).
        before = [text_of(t) for t in history[:-1] if t.get("role") == "user"]
        original = before[-1] if before else None
    if res.kind == "keep" and not res.mentioned:
        if confirmed is not None and confirmed != selection:
            res = Resolution("confirmed", confirmed)
        else:
            for turn in reversed(history[-6:]):
                if turn.get("role") != "user":
                    continue
                earlier = resolve(base, text_of(turn), index)
                if earlier.mentioned:
                    if earlier.kind == "use":
                        res = earlier
                    break
    elif res.kind == "keep" and confirmed is not None and confirmed != selection:
        res = Resolution("confirmed", confirmed, mentioned=res.mentioned, compared=res.compared)
    return res, original


def _align_region_words(question: str, screen: Any, chosen: Any, index: Any) -> str:
    """검색어 속 지역 이름을 정한 검색 지역에 맞춘다. 지역 이름으로 알아본 자리만 바꾸고, 일반 낱말은 건드리지 않는다.

    - 정한 지역 이름이 이미 있으면 그대로 둔다 (겹쳐 붙이지 않는다).
    - 화면 지역(또는 그 시도)으로 알아본 자리가 있으면 그 자리를 정한 지역 이름으로 바꾼다.
    - 어느 쪽도 없으면 정한 지역 이름을 앞에 붙인다.
    """
    from src.retrieval.region_mentions import find_mentions

    target = " ".join(x for x in (chosen.sido, chosen.sigungu) if x)
    if not target:
        return question
    mentions = find_mentions(question, index)

    def region_of(m):
        if m.sido:
            return (m.sido, None)
        return sorted(m.options)[0] if len(m.options) == 1 else None

    found = [(m, region_of(m)) for m in mentions]
    if any(r and r[0] == chosen.sido and r[1] == chosen.sigungu for _, r in found):
        return question
    screen_spans = [m for m, r in found if r and r[0] == screen.sido and r[1] in (screen.sigungu, None)]
    if screen_spans:
        out = question
        for m in sorted(screen_spans, key=lambda x: x.start, reverse=True):
            out = out[:m.start] + (target if m is screen_spans[0] else "") + out[m.end:]
        return " ".join(out.split())
    return f"{target} {question}"


def _empty_result(question: str) -> dict[str, Any]:
    return {
        "question": question, "mode": V3_RESULT_MODE, "documents": [], "graph_results": [], "graph_only_results": [],
        "guideline_results": [], "graph_expansion_results": [], "unverified_candidates": [], "has_evidence": False,
        "verification_level": "vector_only_v3",
        "warnings": ["정책 관계 정보(Neo4j)는 같은 데이터 버전 적재 전이라 사용하지 않았습니다."],
    }


def public_unverified(state: dict[str, Any]) -> list[dict[str, Any]]:
    """API 응답에 내보낼 '적용 지역 미확인' 목록. 내부 검색 결과 전체가 아니라 공개해도 되는 칸만 뽑는다.

    답변을 만든 경우에만 내보낸다(긴급 안내·되묻기·근거 부족에서는 빈 목록).
    registered_sido 는 그 자료가 등록된 시도일 뿐, 적용 지역이 아니다.
    """
    result = state.get("retrieval_result")
    if not is_v3_result(result) or state.get("answer_status") != "success":
        return []
    return [
        {"policy_id": d.get("policy_id"), "title": d.get("title"),
         "registered_sido": (d.get("metadata") or {}).get("sido_name"), "scope_status": "unknown"}
        for d in result.get("unverified_candidates") or [] if d.get("policy_id")
    ]


def route_after_grouped_retrieval(state: WelfareState) -> str:
    result = state.get("retrieval_result") or {}
    return "region_clarify" if result.get("region_error") else "evidence_check"


def region_clarify_node(state: WelfareState) -> WelfareState:
    """지역을 풀 수 없을 때: 검색하지 않고 지역을 다시 고르게 한다."""
    error = (state.get("retrieval_result") or {}).get("region_error") or {}
    if error.get("kind") == "region_conflict":
        choices = [{"id": str(i), "label": c} for i, c in enumerate(error.get("choices") or [], 1)]
        return {"answer": error.get("message") or REGION_CLARIFY_ANSWERS["invalid"], "answer_status": "no_evidence",
                "sources": [], "choices": choices}
    answer = REGION_CLARIFY_ANSWERS.get(error.get("kind"), REGION_CLARIFY_ANSWERS["invalid"])
    return {"answer": answer, "answer_status": "no_evidence", "sources": []}


# ───────────── 정책별 관련성 판정 (근거 검사 단계에서 쓴다) ─────────────

RELEVANCE_RULES = """

[추가 규칙: 문서별 관련성]
- documents 의 각 문서에는 번호(no)와 묶음(evidence_group)이 있습니다.
  local 은 사용자가 고른 지역의 정책, national 은 전국 공통 자료, reference 는 다른 지역일 수 있는 지역 정책입니다.
- 모든 문서에 대해 하나씩 판단해 documents 목록에 적으세요. 번호(no)마다 정확히 한 번씩, 빠짐없이 적습니다.
- relevant 는 그 문서가 사용자의 요구(예: 식사, 보일러 수리, 안부 확인)에 직접 답하는 내용을 담고 있을 때만 true 입니다.
  같은 지역의 정책이라는 이유만으로 true 로 하지 마세요 (예: 식사 지원 질문에 아이돌봄·난임 의료비 정책은 false).
- relevant 가 true 이면 why 에 그 문서가 질문의 어떤 요구에 답하는지 적고, quote 에 그 근거가 되는 문장을 문서 text 에서
  글자 그대로 복사해 넣으세요 (10~60자). 문서에 그런 문장이 없으면 relevant 는 false 입니다.
- 주제가 맞는 정책은 사용자의 신청 자격이 불명확하더라도 relevant 를 true 로 두세요. 자격 확정과 관련성은 다릅니다.
  지원 대상에 나이·대상 제한이 있으면(예: 만 40~64세) why 에 그 제한을 함께 적으세요.
- national 문서가 사용자의 요구에 해당하는 전국 제도(예: 식사 질문에 결식 우려 노인 무료급식, 안부 질문에 독거노인 돌봄)를
  설명하면 relevant 를 true 로 두세요. 고른 지역에 관련 정책이 없을 때 이런 전국 자료가 안내의 근거가 됩니다.
- 사용자가 "여긴 왜 없어?", "우리 동네에도 있어?"처럼 고른 지역에 그런 정책이 있는지를 물을 때,
  local 문서 중 관련 정책이 없더라도 관련 있는 national 문서가 있으면 verdict 는 partial 입니다 (insufficient 가 아님).
  "고른 지역의 정책을 현재 자료에서 찾지 못했다"는 점은 시스템이 따로 안내하므로 insufficient 의 이유가 되지 않습니다.
  insufficient 는 local·national 어느 문서도 사용자의 요구에 답하지 못할 때만 씁니다.
- 사용자가 "나도 받을 수 있지?", "무조건 받는 거지?"처럼 자격을 확정해 달라고 해도, 질문이 가리키는 정책이 문서에 있고
  대상·조건이 적혀 있으면 그 문서는 relevant 를 true 로 두고 verdict 는 partial 로 하세요.
  자격을 확정할 수 없다는 점은 답변 단계에서 안내합니다. 질문이 가리키는 정책이 문서에 아예 없을 때만 insufficient 입니다.
- region_status 가 candidate 인 지역 정책은 적용 지역이 후보로 분류된 자료입니다. relevant 를 true 로 두는 것은 주제가 맞다는 뜻일 뿐,
  그 지역에 적용된다고 확정하거나 사용자가 받을 수 있다고 판단한 것이 아닙니다.
- verdict 가 sufficient 또는 partial 이면 relevant 가 true 인 문서가 하나 이상 있어야 합니다.
  verdict 가 insufficient 또는 uncertain 이면 모든 문서의 relevant 가 false 여야 합니다.
- reason 에 쓴 판단과 각 문서의 relevant 가 서로 어긋나지 않게 하세요.

반드시 아래 JSON 객체만 반환하세요.

{
  "verdict": "sufficient 또는 partial 또는 insufficient 또는 uncertain",
  "reason": "판단 이유를 짧게",
  "documents": [
    {"no": 1, "relevant": true 또는 false, "why": "관련 있으면 질문의 어떤 요구에 답하는지, 없으면 빈 문자열", "quote": "관련 있으면 문서 text 의 근거 문장, 없으면 빈 문자열"}
  ]
}
"""
MIN_QUOTE = 4


def numbered_evidence(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """근거 검사 LLM 에 보낼 문서 목록. 번호·묶음·지역을 붙인다."""
    return [
        {
            "no": i,
            "evidence_group": doc.get("evidence_group"),
            "region": doc.get("region_keys") or [],
            "region_status": (doc.get("metadata") or {}).get("scope_status"),
            "title": doc.get("title"),
            "text": str(doc.get("text") or "")[:1800],
            "record_type": doc.get("record_type"),
            "parent_id": doc.get("parent_id"),
        }
        for i, doc in enumerate(docs, 1)
    ]


_QUOTE_BREAK = re.compile(r"\n|\.\.\.|…|⋯")


def _letters(text: str) -> str:
    """한글·영문·숫자만 남긴다. 띄어쓰기·줄바꿈·따옴표·목록 기호(‑, ･, |), 괄호 속 한자(洞), 로마 숫자(Ⅰ)처럼
    인용할 때 흔히 빠지거나 달라지는 부분을 무시한다."""
    return "".join(ch for ch in str(text) if "가" <= ch <= "힣" or (ch.isascii() and ch.isalnum()))


QUOTE_ANCHOR = 10   # 문서에서 그대로 찾아야 하는 조각의 최소 글자 수


def quote_parts(quote: str, text: str) -> tuple[list[str], list[str]]:
    """인용을 줄·말줄임표로 나눠, 문서에 그대로 있는 조각과 없는 조각으로 가른다 (짧은 조각은 뺀다)."""
    body = _letters(text)
    verified, unverified = [], []
    for raw in _QUOTE_BREAK.split(str(quote)):
        piece = raw.strip()
        if len(_letters(piece)) < MIN_QUOTE:
            continue
        (verified if _letters(piece) in body else unverified).append(piece)
    return verified, unverified


def quote_check(quote: str, text: str) -> str:
    """근거 문장이 문서에 있는가: "exact"(모든 조각이 문서에 있음) / "partial"(일부 조각만) / "missing".

    LLM 은 여러 줄을 이어 붙이거나 "..." 로 줄이고, 가끔 몇 글자를 바꿔 인용한다. 그래서 줄·말줄임표로 나눈 조각마다 본다.
    10글자 이상인 조각 하나가 문서에 그대로 있으면 그 문서를 보고 판단한 것으로 인정한다. 이때 문서에 없는 조각은
    검증된 인용으로 남기지 않는다(parse_relevance 가 따로 떼어 기록한다). 그런 조각이 하나도 없으면 missing.
    인용이 있다는 것이 관련성을 보장하지는 않는다. 근거 없는 판단을 걸러 내는 최소한의 확인이다.
    """
    verified, unverified = quote_parts(quote, text)
    if not any(len(_letters(p)) >= QUOTE_ANCHOR for p in verified):
        return "missing"
    return "partial" if unverified else "exact"


def quote_in_document(quote: str, text: str) -> bool:
    return quote_check(quote, text) != "missing"


def parse_relevance(parsed: dict[str, Any], texts: list[str]) -> tuple[str, str, list[int], dict[int, dict]]:
    """LLM 판정을 검사한다. 형식이 틀리거나 서로 모순되면 ValueError (판정 실패로 처리된다).

    texts 는 판정에 보낸 문서 본문(번호 순서). 돌려주는 값: verdict, reason, 관련 문서 번호, 문서별 판단(why·quote·버린 까닭).
    관련 있다고 했지만 근거 문장이 그 문서에 없으면 그 문서는 관련 없음으로 바꾸고 기록한다(근거 없는 판단을 믿지 않는다).
    """
    verdict = parsed.get("verdict")
    if verdict not in ("sufficient", "partial", "insufficient", "uncertain"):
        raise ValueError("잘못된 검증 결과")
    docs = parsed.get("documents")
    if not isinstance(docs, list) or not all(isinstance(d, dict) for d in docs):
        raise ValueError("documents 는 문서별 판단의 목록이어야 함")
    numbers = [d.get("no") for d in docs]
    if any(isinstance(n, bool) or not isinstance(n, int) for n in numbers) or sorted(numbers) != list(range(1, len(texts) + 1)):
        raise ValueError("documents 에 모든 문서 번호가 정확히 한 번씩 있어야 함")
    details: dict[int, dict] = {}
    for d in docs:
        if not isinstance(d.get("relevant"), bool):
            raise ValueError("relevant 는 true 또는 false 여야 함")
        why, quote = d.get("why", ""), d.get("quote", "")
        if not isinstance(why, str) or not isinstance(quote, str):
            raise ValueError("why 와 quote 는 글자여야 함")
        if d["relevant"] and not why.strip():
            raise ValueError("관련 있다고 한 문서에 이유(why)가 없음")
        item = {"relevant": d["relevant"], "why": why.strip()[:200], "quote": ""}
        if item["relevant"]:
            text = texts[d["no"] - 1]
            if quote_check(quote, text) == "missing":
                item.update(relevant=False, dropped="quote_not_in_document", quote_unverified=quote[:200])
            else:
                verified, unverified = quote_parts(quote, text)
                item["quote"] = " … ".join(verified)[:300]   # 문서에서 확인된 조각만 인용으로 남긴다
                if unverified:
                    item.update(note="quote_partly_rephrased", quote_unverified=" … ".join(unverified)[:200])
        details[d["no"]] = item
    claimed = [n for n, d in details.items() if d["relevant"] or d.get("dropped")]
    if (verdict in ("sufficient", "partial")) != bool(claimed):
        raise ValueError("verdict 와 문서별 판단이 서로 맞지 않음")
    relevant = sorted(n for n, d in details.items() if d["relevant"])
    if verdict in ("sufficient", "partial") and not relevant:
        # 관련 있다고 한 문서가 모두 근거 문장 확인에서 떨어졌다. 판정을 믿을 수 없으므로 실패로 본다.
        raise ValueError("관련 있다고 한 문서의 근거 문장을 하나도 확인하지 못함")
    return verdict, str(parsed.get("reason") or "")[:300], relevant, details


def relevance_uncertain(result: dict[str, Any]) -> dict[str, Any]:
    """LLM 이 판단하기 어렵다고 답했을 때. 근거를 건드리지 않고, '관련 정책 없음'으로 기록하지 않는다."""
    updated = dict(result)
    updated["relevance"] = {"status": "uncertain"}
    return updated


def v3_region_fields(result: dict[str, Any], selected: str | None, instructions: str) -> tuple[str | None, str]:
    """LLM 에 넘길 선택 지역과 지역 지침. 시도까지만 고른 경우를 3차 지침과 충돌하지 않게 바꾼다.

    시스템 프롬프트는 selected_region 이 있으면 지역을 다시 묻지 말라고 한다. 시도까지만 골랐을 때 그대로 두면
    시군구를 물어야 한다는 지침과 부딪친다. 그래서 selected_region 은 비우고, 지역 지침에 시도는 이미 골랐다고 적는다.
    """
    selection = result.get("selection") or {}
    from_question = selection.get("source") == "question"
    if selection.get("kind") == "sido_only":
        sido = selection.get("sido")
        where = "질문에서 말한" if from_question else "화면에서 고른"
        return None, (
            f"사용자가 {where} 지역은 '{sido}'이고 시·군·구는 정해지지 않았습니다. "
            "시·도는 이미 확인됐으므로 다시 묻지 마세요. 시·군·구는 아직 모르므로 물어볼 수 있습니다. "
            "지역 정책은 시·군·구마다 다르므로, 그 시·도 전체에 적용된다고 말하지 마세요."
        )
    if from_question and selection.get("kind") == "region":
        # "횡성인데 보청기 돼?"처럼 질문에서 말한 지역으로 검색했다. 이미 말한 지역을 다시 묻지 않게 한다.
        name = f"{selection.get('sido')} {selection.get('sigungu')}"
        return name, (
            f"사용자가 질문에서 말한 지역은 '{name}'입니다. 이 지역 기준으로 안내하세요. "
            "사용자가 이미 말한 지역이므로 어디에 사는지 다시 묻지 마세요. "
            "선택 지역에 대한 검색 후보가 없더라도 정책이 존재하지 않는다고 단정하지 마세요."
        )
    return selected, instructions


def apply_relevance(result: dict[str, Any], docs: list[dict[str, Any]], relevant: list[int],
                    details: dict[int, dict] | None = None) -> tuple[list[dict], dict]:
    """관련 없다고 판정된 문서를 근거에서 완전히 뺀다. 원래 후보와 문서별 판단은 진단용으로 남긴다."""
    details = details or {}
    kept = [docs[n - 1] for n in relevant]
    updated = dict(result)
    updated["documents"] = kept
    updated["has_evidence"] = bool(kept)
    updated["candidates_before_relevance"] = [
        {"chunk_id": d.get("chunk_id"), "evidence_group": d.get("evidence_group"), "kept": (i in relevant),
         **{k: v for k, v in (details.get(i) or {}).items() if k in ("why", "quote", "quote_unverified", "dropped", "note")}}
        for i, d in enumerate(docs, 1)
    ]
    groups = [d.get("evidence_group") for d in kept]
    updated["relevance"] = {
        "status": "judged",
        "kept": {g: groups.count(g) for g in ("local", "national", "reference")},
        # 정상 판정에서 고른 지역의 관련 정책이 하나도 남지 않았는가 (판정 실패와 구분한다)
        "local_policy_found": "local" in groups,
        # 관련 있다고 했지만 근거 문장이 문서에 없어 뺀 문서 수 (0 이어야 정상)
        "quote_mismatch": sum(1 for d in details.values() if d.get("dropped")),
        "quote_partly_rephrased": sum(1 for d in details.values() if d.get("note")),
    }
    return kept, updated


# 전국 자료를 "전국 공통 지원"이라 부르지 않게 한다. 안내서에는 기초연금처럼 전국 같은 기준의 제도와
# 무료급식·식사 배달처럼 시·군·구가 자체 시행하는 사업(지방이양사업)이 함께 실려 있다.
# 답변 LLM 에는 묶음 이름 national 대신 guidebook 을 넘긴다 ('national' 이라는 말 자체가 '전국 공통'으로 읽히기 때문).
_ANSWER_GROUP_LABELS = {"national": "guidebook"}


def answer_group_label(group: str | None) -> str | None:
    """답변 프롬프트에 넘길 묶음 이름. 검색·판정·기록에서는 원래 이름(national)을 그대로 쓴다."""
    return _ANSWER_GROUP_LABELS.get(group, group)


NATIONAL_WORDING = (
    "guidebook 문서의 사업을 모두 '전국 공통 지원'이라고 뭉뚱그려 말하지 마세요. 안내서에는 나라가 정한 제도와 "
    "시·군·구가 자체적으로 하는 사업이 함께 실려 있으니 문서 내용에 따라 구분하세요.\n"
    "- 건강보험·의료급여·기초연금·장기요양보험처럼 나라가 정한 급여·보험 제도이면 전국 제도로 안내하세요. "
    "이때 '이 지역에서 시행하는지 확인하라'고 하지 말고, 자격·본인부담은 확인이 필요하다고 안내하세요.\n"
    "- 문서에 지방자치단체가 자체적으로 계획·시행한다(지방이양사업, 지역 재정여건에 따라)는 내용이 있으면 "
    "'정부 안내서에 소개된 제도'라고 하고, 사는 지역에서 하는지는 주민센터나 시·군·구청에 확인해야 한다고 안내하세요.\n"
    "- 어느 쪽인지 문서로 알 수 없으면 '정부 안내서에 소개된 제도'라고만 하고, 자세한 대상과 신청 방법은 주민센터에 문의하도록 안내하세요.\n"
    "나라가 정한 급여·보험 제도가 아니면 '전국적으로 ~ 있습니다', '전국 어디서나'처럼 어디서나 받을 수 있다고 들리는 말도 쓰지 마세요."
)


def v3_answer_guidance(result: dict[str, Any]) -> str:
    """답변 생성 프롬프트에 붙일 4차 지침. 문구를 다듬는 일은 B5 에서 한다."""
    selection = result.get("selection") or {}
    relevance = result.get("relevance") or {}
    lines = [
        "\ndocuments 의 evidence_group 은 문서의 종류입니다. local 은 사용자가 고른 지역의 정책, "
        "guidebook 은 정부가 펴낸 안내서(사업 안내·복지서비스 책자)의 내용, reference 는 특정 지역의 정책입니다. "
        "지역 정책과 안내서 내용을 구분해서 설명하세요.",
        NATIONAL_WORDING,
        "region_status 가 candidate 인 지역 정책은 적용 지역이 후보로 분류된 자료입니다. 그 지역에 살면 받을 수 있다고 확정하지 말고, "
        "적용 지역과 자격은 담당 기관에서 확인하도록 안내하세요.",
        "문서의 지원 대상에 나이·대상 제한이 있으면(예: 만 40~64세 중장년) 그 제한을 반드시 함께 말하고, "
        "사용자가 해당하지 않을 수 있다고 안내하세요. 해당한다고 단정하거나 신청을 권하지 마세요.",
    ]
    if selection.get("compared"):
        lines.append(
            f"사용자가 다른 지역({', '.join(selection['compared'])})을 비교해서 말했습니다. 검색은 사용자가 고른 지역 기준입니다. "
            "다른 지역의 정책을 사용자가 고른 지역의 것처럼 말하지 마세요."
        )
    if selection.get("kind") == "sido_only":
        lines.append(
            "사용자는 시·도까지만 골랐습니다. local 문서는 그 시·도 안의 특정 시·군·구 정책이므로 어느 시·군·구 것인지(region) 함께 말하고, "
            "시·도 전체에 적용된다고 말하지 마세요. 고른 시·도는 다시 묻지 말고, 빠진 시·군·구만 물어보세요."
        )
    if selection.get("kind") == "nationwide":
        lines.append(
            "reference 문서는 특정 지역 주민을 위한 정책입니다. 어느 지역 것인지(region) 밝히고, 사용자가 그 지역에 사는지 알 수 없으므로 "
            "받을 수 있다고 말하지 마세요. 사는 지역을 물어보세요."
        )
    if selection.get("kind") == "region" and relevance.get("status") == "judged" and not relevance.get("local_policy_found"):
        lines.append(
            "사용자가 고른 지역에서 이 질문과 관련된 정책은 현재 자료에서 찾지 못했습니다. 이 점을 먼저 알리되, "
            "그 지역에 정책이 없다고 단정하지 마세요. 이것은 그 지역의 자체 사업 이야기입니다. guidebook 문서의 제도는 위 방식대로 구분하세요. "
            "건강보험 틀니·임플란트처럼 나라가 정한 급여·보험 제도는 그 지역에서도 같은 기준이므로 '이 지역에서 시행하는지 확인하라'고 하지 말고, "
            "지자체가 자체적으로 하는 사업만 시행 여부를 확인하도록 안내하세요. 자세한 상담은 주민센터에 문의해 보도록 권하세요."
        )
    return "\n".join(lines)


def relevance_failed(result: dict[str, Any]) -> dict[str, Any]:
    """판정 자체가 실패했을 때. '관련 정책 없음'과 구분해 기록한다."""
    updated = dict(result)
    updated["relevance"] = {"status": "failed"}
    return updated
