"""정책 목록·상세의 4차(v3) 경로(B4) 테스트. 가짜 검색·가짜 Qdrant 로 돈다 (DB·API 없이)."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import pydantic  # noqa: F401
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("pydantic 이 설치되지 않은 환경")

from backend.src.schemas.chat import ChatResponse
from backend.src.schemas.policies import AskRequest, RegionSelection
from backend.src.services import policy_service_v3 as P
from src.agents.welfare_retrieval_v3 import V3_RESULT_MODE, public_unverified
from src.memory.session_manager import run_chat_session
from src.retrieval.config import RetrievalConfigError, V3_REQUIRED_INDEXES, load_settings

DV = "nationwide_2026_11_26_6efc3b7671b3"
SETTINGS = load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": "c", "RAG_DATA_VERSION": DV})
HS = "강원특별자치도|횡성군"
ROOT = Path(__file__).resolve().parents[1]


def doc(name, group, *, kind="policy", keys=(HS,), sido="강원특별자치도"):
    pid = f"local:{name}" if kind == "policy" else name
    md = {"record_type": kind, "applies_to_keys": list(keys), "sido_name": sido if kind == "policy" else None,
          "scope_status": ("candidate" if keys else "unknown") if kind == "policy" else None, "themes": ["생활지원"],
          "document_id": "doc-1" if kind == "guideline" else None, "page_start": 3, "page_end": 3, "section": "절", "approval_status": "pending"}
    return {"id": f"u-{name}", "chunk_id": f"{name}::1", "parent_id": pid, "record_type": kind,
            "policy_id": pid if kind == "policy" else None, "section_id": pid if kind == "guideline" else None,
            "text": f"{name} 본문", "score": 0.5, "title": f"제목-{name}", "source_url": None, "metadata": md,
            "evidence_group": group, "region_keys": list(keys)}


class FakeSearch:
    def __init__(self, local=2):
        self.calls, self.local = [], local

    def __call__(self, question, selection, **kwargs):
        self.calls.append((question, selection, kwargs))
        out = {"local": [], "national": [doc("sec-a", "national", kind="guideline", keys=("national",))],
               "unverified": [], "reference": [], "info": {}}
        if selection.kind in ("region", "sido_only"):
            out["local"] = [doc("식사배달", "local"), doc("목욕비", "local", keys=("강원특별자치도|강릉시", HS))][: self.local]
            out["unverified"] = [doc("미상자료", "unverified", keys=())]
        if selection.kind == "nationwide":
            out["reference"] = [doc("부산보청기", "reference", keys=("부산광역시|기장군",), sido="부산광역시")]
        return out


def ask(region, search=None):
    search = search or FakeSearch()
    return P.search_policies_v3(AskRequest(question="밥 갖다주는 데 없나?", region=RegionSelection(**region)), search=search), search


class ListTests(unittest.TestCase):
    def test_region_gives_candidates_references_and_separate_unverified(self):
        result, search = ask({"kind": "region", "sido_name": "강원", "sigungu_name": "횡성군"})
        self.assertEqual(search.calls[0][2], P.LIST_K)
        first, second = result.items
        self.assertEqual((first.policy_id, first.sido_name, first.sigungu_name, first.applies_to), ("local:식사배달", "강원특별자치도", "횡성군", [HS]))
        self.assertEqual((second.sido_name, second.sigungu_name), ("강원특별자치도", None))   # 여러 시군구에 걸친 정책
        self.assertEqual(first.badges[0].label, "적용 지역 후보")
        self.assertEqual([r.document_id for r in result.reference_candidates], ["doc-1"])
        unverified = result.region_unverified[0]
        self.assertEqual((unverified.policy_id, unverified.sido_name, unverified.registered_sido, unverified.scope_status),
                         ("local:미상자료", None, "강원특별자치도", "unknown"))
        self.assertNotIn("local:미상자료", [i.policy_id for i in result.items])
        self.assertEqual(unverified.badges[0].tone, "warn")

    def test_wording_says_candidates_not_matching_policies(self):
        result, _ = ask({"kind": "region", "sido_name": "강원", "sigungu_name": "횡성군"})
        self.assertIn("후보 2건", result.answer)
        self.assertIn("관련이 낮은 정책이 섞여 있을 수", result.answer)
        self.assertNotIn("찾았습니다", result.answer)
        self.assertIn("담당 기관에서 확인", result.scope_notice.message)

    def test_explicit_nationwide_shows_regional_references(self):
        result, _ = ask({"kind": "nationwide"})
        self.assertEqual([(i.policy_id, i.sigungu_name) for i in result.items], [("local:부산보청기", "기장군")])
        self.assertIn("지역별 참고", result.items[0].badges[0].label)
        self.assertEqual(result.region_unverified, [])
        self.assertIsNone(result.scope_notice)

    def test_sido_only_notice(self):
        result, _ = ask({"kind": "region", "sido_name": "강원"})
        self.assertIn("시·군·구마다 정책이 달라요", result.scope_notice.message)

    def test_unresolvable_region_asks_to_choose_again_without_searching(self):
        result, search = ask({"kind": "region", "sido_name": "광주"})
        self.assertEqual(search.calls, [])
        self.assertEqual((result.scope_notice.reason, result.items, result.region_unverified), ("unsupported_region", [], []))
        self.assertIn("광주광역시인지 경기도 광주시인지", result.answer)

    def test_no_candidates_gives_fallback_without_claiming_absence(self):
        result, _ = ask({"kind": "region", "sido_name": "강원", "sigungu_name": "횡성군"}, FakeSearch(local=0))
        self.assertEqual(result.fallback.reason, "no_results")
        self.assertIn("지금 가진 자료로", result.answer)

    def test_server_errors_are_not_hidden(self):
        def broken(*args, **kwargs):
            raise RetrievalConfigError("컬렉션 점검 실패")
        with self.assertRaises(RetrievalConfigError):
            ask({"kind": "region", "sido_name": "강원", "sigungu_name": "횡성군"}, broken)

    def test_new_fields_are_camel_case_and_default_empty(self):
        result, _ = ask({"kind": "region", "sido_name": "강원", "sigungu_name": "횡성군"})
        data = result.model_dump(by_alias=True)
        self.assertIn("regionUnverified", data)
        self.assertEqual(data["items"][0]["appliesTo"], [HS])


class DispatchTests(unittest.TestCase):
    """policy_service 는 스위치에 따라 3차 또는 4차 경로를 고른다."""

    def setUp(self):
        try:
            from backend.src.services import policy_service
        except ImportError as exc:
            self.skipTest(f"policy_service 를 불러올 수 없음: {exc}")
        self.service = policy_service

    def test_legacy_by_default_and_v3_when_switched(self):
        request = AskRequest(question="밥 갖다주는 데 없나?", region=RegionSelection(kind="nationwide"))
        legacy = {"documents": [], "graph_results": []}
        with patch.dict(os.environ, {}, clear=False), \
                patch.object(self.service, "retrieve_welfare", return_value=legacy) as old, \
                patch("backend.src.services.policy_service_v3.search_policies_v3", return_value="v3-result") as new, \
                patch("backend.src.services.policy_service_v3.get_policy_detail_v3", return_value="v3-detail") as detail:
            os.environ.pop("RAG_RETRIEVAL_MODE", None)
            self.assertEqual(self.service.search_policies(request).items, [])
            self.assertEqual((old.call_count, new.call_count), (1, 0))
            os.environ["RAG_RETRIEVAL_MODE"] = "v3"
            self.assertEqual(self.service.search_policies(request), "v3-result")
            self.assertEqual(self.service.get_policy_detail("local:WLF1"), "v3-detail")
            self.assertEqual((old.call_count, new.call_count, detail.call_count), (1, 1, 1))


TEXT_1 = ("사업명: 식사배달\n지역: 강원특별자치도 횡성군\n사업 개요: 결식 우려 어르신께 식사를 드립니다\n"
          "지원 대상: 결식우려가 있는 저소득 노인\n선정 기준: 저소득 어르신 중 결식우려 세대\n지원 내용: 주2회 도시락 또는 반찬 배달")
TEXT_2 = "지원 내용: 주2회 도시락 또는 반찬 배달\n참고: 이 줄은 라벨이 아님\n신청 방법: 읍면 행정복지센터 방문\n신청 방식: 방문\n담당 부서: 횡성군 가족복지과\n문의처: 033-340-2150"


def chunk(n, text, **md):
    meta = {"record_type": "policy", "policy_id": "local:WLF1", "chunk_id": f"policy::local:WLF1::fixed::{n:04d}",
            "data_version": DV, "release_status": "approved", "applies_to_keys": [HS], "sido_name": "강원특별자치도",
            "scope_status": "candidate", "title": "식사배달", "department": "횡성군 가족복지과", "contact": "033-340-2150",
            "contact_status": "source_group_confirmed", "source_url": "https://example.org/p", "start_date": "2016-07-01",
            "end_date": "9999-12-31", **md}
    return SimpleNamespace(id=f"p{n}", payload={"page_content": text, "metadata": meta})


class FakeQdrant:
    def __init__(self, points):
        self.points, self.filters = points, []

    def get_collection(self, name):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=1024, distance="Cosine"))),
                               payload_schema={k: SimpleNamespace(data_type="keyword") for k in V3_REQUIRED_INDEXES})

    def count(self, collection_name, count_filter=None, exact=True):
        return SimpleNamespace(count=5)

    def scroll(self, collection_name, scroll_filter=None, **kwargs):
        self.filters.append(scroll_filter)
        want = {c["key"]: c["match"]["value"] for c in scroll_filter["must"]}
        rows = [p for p in self.points if p.payload["metadata"].get("policy_id") == want["metadata.policy_id"]]
        return list(reversed(rows)), None   # 순서가 뒤섞여 와도 번호순으로 이어 붙여야 한다


def detail(points, policy_id="local:WLF1"):
    from src.retrieval import grouped_search
    grouped_search._verified.clear()
    client = FakeQdrant(points)
    return P.get_policy_detail_v3(policy_id, client=client, settings=SETTINGS), client


class DetailTests(unittest.TestCase):
    def test_merge_and_sections(self):
        self.assertEqual(P.merge_chunks(["가나다라마바사아자차카타파하 끝부분이 스무 글자 넘게 겹칩니다 정말로", "끝부분이 스무 글자 넘게 겹칩니다 정말로 그리고 뒷내용"]),
                         "가나다라마바사아자차카타파하 끝부분이 스무 글자 넘게 겹칩니다 정말로 그리고 뒷내용")
        self.assertIsNone(P.merge_chunks(["앞 조각입니다", "전혀 겹치지 않는 뒤 조각입니다"]))
        self.assertEqual(P.merge_chunks(["하나뿐"]), "하나뿐")
        sections = P.parse_sections("사업명: 가\n지원 대상: 나\n참고: 다\n신청 방법: 라")
        self.assertEqual(sections, {"사업명": "가", "지원 대상": "나\n참고: 다", "신청 방법": "라"})

    def test_two_chunks_are_joined_in_order_and_fields_filled(self):
        d, client = detail([chunk(1, TEXT_1), chunk(2, TEXT_2)])
        self.assertEqual(d.summary, "결식 우려 어르신께 식사를 드립니다")
        self.assertEqual(d.benefit_text, "주2회 도시락 또는 반찬 배달\n참고: 이 줄은 라벨이 아님")
        self.assertEqual(d.application_text, "읍면 행정복지센터 방문 (신청 방식: 방문)")
        self.assertEqual((d.sido_name, d.sigungu_name, d.applies_to), ("강원특별자치도", "횡성군", [HS]))
        self.assertEqual([(c.label, c.tel) for c in d.contacts], [("횡성군 가족복지과", "033-340-2150")])
        self.assertIsNone(d.end_date)                    # 9999-12-31 은 그대로 보여 주지 않는다
        self.assertEqual(d.start_date, "2016-07-01")
        self.assertFalse(d.body_incomplete)
        must = {(c["key"], c["match"]["value"]) for c in client.filters[0]["must"]}
        self.assertTrue({("metadata.data_version", DV), ("metadata.release_status", "approved"),
                         ("metadata.record_type", "policy"), ("metadata.policy_id", "local:WLF1")} <= must)

    def test_unconfirmed_contact_is_not_shown(self):
        for status in ("legacy_candidate_review", "unknown", None):
            d, _ = detail([chunk(1, TEXT_1, contact_status=status)])
            with self.subTest(status=status):
                self.assertEqual(d.contacts, [])
                self.assertIn("확인이 필요", d.contact_note)

    def test_several_phone_numbers_become_separate_contacts(self):
        d, _ = detail([chunk(1, TEXT_1, contact="061-830-5640 / 061-830-3837 / 061-830-5640")])
        self.assertEqual([c.tel for c in d.contacts], ["061-830-5640", "061-830-3837"])   # 번호마다 하나씩, 중복은 한 번
        self.assertIsNone(d.contact_note)
        for raw, tels in (("1588-0000 / 129", ["1588-0000", "129"]), ("033-553 / 033-550-2072", ["033-550-2072"])):
            d, _ = detail([chunk(1, TEXT_1, contact=raw)])
            with self.subTest(raw=raw):
                self.assertEqual([c.tel for c in d.contacts], tels)
        self.assertIn("형식을 확인하지 못해", d.contact_note)       # 잘린 번호는 전화 걸기 대상으로 내보내지 않는다
        d, _ = detail([chunk(1, TEXT_1, contact="033-553 / 55")])
        self.assertEqual(d.contacts, [])
        self.assertIn("확인이 필요", d.contact_note)

    def test_missing_pieces_are_reported_as_incomplete_body(self):
        only_second, _ = detail([chunk(2, TEXT_2)])                  # 첫 조각이 없음
        only_first, _ = detail([chunk(1, TEXT_1)])                   # 끝 조각이 없음 (끝 라벨 '담당 부서'가 안 나옴)
        gap, _ = detail([chunk(1, TEXT_1), chunk(3, TEXT_2)])        # 가운데 번호가 빔
        for name, d in (("첫 조각 없음", only_second), ("끝 조각 없음", only_first), ("번호가 빔", gap)):
            with self.subTest(case=name):
                self.assertTrue(d.body_incomplete)
                self.assertEqual((d.summary, d.application_text), (None, None))
                self.assertEqual(d.title, "식사배달")

    def test_all_pages_are_read(self):
        class Paged(FakeQdrant):
            def scroll(self, collection_name, scroll_filter=None, offset=None, **kwargs):
                self.filters.append(offset)
                return ([self.points[0]], "next") if offset is None else ([self.points[1]], None)
        from src.retrieval import grouped_search
        grouped_search._verified.clear()
        client = Paged([chunk(1, TEXT_1), chunk(2, TEXT_2)])
        d = P.get_policy_detail_v3("local:WLF1", client=client, settings=SETTINGS)
        self.assertEqual(client.filters, [None, "next"])
        self.assertFalse(d.body_incomplete)
        self.assertIn("읍면 행정복지센터 방문", d.application_text)

    def test_chunks_with_different_metadata_stop_instead_of_picking_one(self):
        for field, value in (("contact", "02-000-0000"), ("applies_to_keys", ["강원특별자치도|강릉시"]), ("department", "다른 부서")):
            with self.subTest(field=field), self.assertRaises(RetrievalConfigError):
                detail([chunk(1, TEXT_1), chunk(2, TEXT_2, **{field: value})])

    def test_unknown_scope_is_marked_and_registered_sido_is_not_a_region(self):
        d, _ = detail([chunk(1, TEXT_1, applies_to_keys=[], scope_status="unknown")])
        self.assertEqual((d.sido_name, d.sigungu_name, d.registered_sido), (None, None, "강원특별자치도"))
        self.assertIn("적용 지역 미확인", [b.label for b in d.badges])

    def test_chunks_that_do_not_overlap_leave_body_empty_but_keep_metadata(self):
        d, _ = detail([chunk(1, TEXT_1), chunk(2, "겹치지 않는 조각\n신청 방법: 알 수 없음")])
        self.assertTrue(d.body_incomplete)
        self.assertEqual((d.summary, d.application_text), (None, None))
        self.assertEqual((d.title, d.department), ("식사배달", "횡성군 가족복지과"))

    def test_missing_policy_is_none_and_wrong_version_is_a_server_error(self):
        self.assertIsNone(detail([chunk(1, TEXT_1)], policy_id="local:NOPE")[0])
        with self.assertRaises(RetrievalConfigError):
            detail([chunk(1, TEXT_1, release_status="draft")])
        with self.assertRaises(RetrievalConfigError):
            detail([chunk(1, TEXT_1, data_version="old")])


class RealDataMergeTests(unittest.TestCase):
    """저장소에 4차 자료가 있으면, 청크를 이어 붙인 본문이 원본 정책 문서와 글자 그대로 같은지 전부 대조한다."""

    def test_merged_chunks_equal_source_documents(self):
        folder = ROOT / "data" / "rag" / "nationwide_v3"
        if not (folder / "policy_documents.jsonl").exists() or not (folder / "policy_chunks.jsonl").exists():
            self.skipTest("4차 자료(data/rag/nationwide_v3)가 이 작업 폴더에 없음")
        chunks: dict[str, list] = {}
        with open(folder / "policy_chunks.jsonl", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                chunks.setdefault(r["policy_id"], []).append((r["chunk_id"], r["text"]))
        with open(folder / "policy_documents.jsonl", encoding="utf-8") as f:
            documents = {r["policy_id"]: r["text"] for r in map(json.loads, f)}
        self.assertEqual(set(chunks), set(documents))
        wrong = [pid for pid, parts in chunks.items() if P.merge_chunks([t for _, t in sorted(parts)]) != documents[pid]]
        self.assertEqual(wrong, [])


class ChatFieldTests(unittest.TestCase):
    def state(self, status="success", mode=V3_RESULT_MODE):
        return {"answer_status": status, "retrieval_result": {"mode": mode, "unverified_candidates": [doc("미상자료", "unverified", keys=())]}}

    def test_public_list_has_only_public_fields(self):
        self.assertEqual(public_unverified(self.state()), [
            {"policy_id": "local:미상자료", "title": "제목-미상자료", "registered_sido": "강원특별자치도", "scope_status": "unknown"}])

    def test_empty_unless_v3_answer_was_made(self):
        for state in (self.state(status="no_evidence"), self.state(status="safety_response"), self.state(mode="hybrid"),
                      {"answer_status": "success"}):
            with self.subTest(state=str(state)[:40]):
                self.assertEqual(public_unverified(state), [])

    @patch("src.memory.session_manager.save_exchange")
    @patch("src.memory.session_manager.load_history", return_value=[])
    def test_memory_path_passes_the_list_through(self, load, save):
        items = [{"policy_id": "local:미상자료", "title": "t", "registered_sido": "강원특별자치도", "scope_status": "unknown"}]
        result = run_chat_session("밥 갖다주는 데 없나?", None, lambda s: {
            "answer": "안내", "answer_status": "success", "safety_status": "normal", "region_unverified": items})
        self.assertEqual(result["region_unverified"], items)
        plain = run_chat_session("밥 갖다주는 데 없나?", None, lambda s: {"answer": "안내", "answer_status": "success", "safety_status": "normal"})
        self.assertEqual(plain["region_unverified"], [])
        response = ChatResponse.model_validate(result)
        self.assertEqual(response.region_unverified, items)

    def test_both_chat_paths_return_public_fields_only(self):
        """ask_welfare 의 대화 기억 사용·미사용 경로에 4차 모양의 결과를 넣어, 공개 목록만 끝까지 나가는지 본다."""
        from src.agents import graph as graph_module

        state = {"answer": "안내 드릴게요.", "answer_status": "success", "safety_status": "normal", "sources": [], "choices": [],
                 "retrieved_docs": [doc("식사배달", "local")],
                 "retrieval_result": {"mode": V3_RESULT_MODE, "grouped_info": {"collection": "internal"},
                                      "unverified_candidates": [doc("미상자료", "unverified", keys=())]}}
        want = [{"policy_id": "local:미상자료", "title": "제목-미상자료", "registered_sido": "강원특별자치도", "scope_status": "unknown"}]
        fake = SimpleNamespace(invoke=lambda s: dict(state))
        with patch.object(graph_module, "_default_graph", return_value=fake), \
                patch("src.memory.session_manager.load_history", return_value=[]), \
                patch("src.memory.session_manager.save_exchange"):
            for memory in (False, True):
                with self.subTest(memory=memory):
                    out = graph_module.ask_welfare("밥 갖다주는 데 없나?", memory_enabled=memory)
                    self.assertEqual(out["region_unverified"], want)
                    self.assertNotIn("retrieval_result", out)      # 내부 검색 결과는 응답에 나가지 않는다
                    self.assertNotIn("retrieved_docs", out)
                    self.assertNotIn("internal", json.dumps(out, ensure_ascii=False, default=str))
                    ChatResponse.model_validate({**out, "session_id": out["session_id"] or "a7057d35-126a-4ebe-b73a-e1ef3f2fb070"})

    def test_response_schema_defaults_to_empty(self):
        base = {"session_id": "a7057d35-126a-4ebe-b73a-e1ef3f2fb070", "answer": "a", "answer_status": "success"}
        self.assertEqual(ChatResponse.model_validate(base).region_unverified, [])

    def test_no_memory_path_adds_the_field(self):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            self.skipTest("langgraph 가 설치되지 않은 환경")
        from src.agents.graph import ask_welfare
        result = ask_welfare("기초연금 신청 방법", mock=True, memory_enabled=False)
        self.assertEqual(result["region_unverified"], [])


if __name__ == "__main__":
    unittest.main()
