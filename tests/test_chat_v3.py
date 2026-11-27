"""4차(v3) 채팅 연결(B3) 테스트. 가짜 검색·가짜 LLM 으로 돈다 (DB·API 없이)."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from src.agents import welfare_retrieval_v3 as V
from src.agents.evidence_check import EVIDENCE_PROMPT, EVIDENCE_PROMPT_V3, make_evidence_node
from src.retrieval import region_rules as R
from src.retrieval.config import RetrievalConfigError

HS = "강원특별자치도|횡성군"
REGION = {"kind": "region", "sido_name": "강원", "sigungu_name": "횡성군"}


def doc(name, group, *, kind="policy", keys=(HS,), score=0.5):
    pid = f"local:{name}" if kind == "policy" else name
    return {
        "id": f"uuid-{name}", "chunk_id": f"{name}::1", "parent_id": pid, "record_type": kind,
        "policy_id": pid if kind == "policy" else None, "section_id": pid if kind == "guideline" else None,
        "text": f"{name} 본문", "score": score, "title": f"제목-{name}", "source_url": None,
        "metadata": {"record_type": kind, "applies_to_keys": list(keys),
                     "scope_status": ("candidate" if keys else "unknown") if kind == "policy" else None},
        "evidence_group": group, "region_keys": list(keys),
    }


LOCAL = [doc("식사배달", "local"), doc("난임의료비", "local"), doc("봉양수당", "local")]
NATIONAL = [doc("sec-급식", "national", kind="guideline", keys=("national",)), doc("sec-돌봄", "national", kind="guideline", keys=("national",))]
UNVERIFIED = [doc("미상자료", "unverified", keys=())]
REFERENCE = [doc("부산보청기", "reference", keys=("부산광역시|기장군",))]


class FakeSearch:
    def __init__(self):
        self.calls = []

    def __call__(self, question, selection, **kwargs):
        self.calls.append((question, selection, kwargs))
        out = {"local": [], "national": list(NATIONAL), "unverified": [], "reference": [],
               "info": {"returned": {}, "dropped": {}, "short": []}}
        if selection.kind in ("region", "sido_only"):
            out["local"], out["unverified"] = list(LOCAL), list(UNVERIFIED)
        if selection.kind == "nationwide":
            out["reference"] = list(REFERENCE)
        return out


class FakeLLM:
    """근거 검사 호출에는 정해 둔 판정을, 답변 호출에는 고정 문장을 돌려주고 받은 프롬프트를 남긴다."""

    def __init__(self, judgement):
        self.judgement, self.evidence_calls, self.answer_prompts = judgement, [], []

    def __call__(self, system_text, user_text):
        if "근거 검증기" in system_text:
            self.evidence_calls.append((system_text, json.loads(user_text)))
            if isinstance(self.judgement, Exception):
                raise self.judgement
            return self.judgement if isinstance(self.judgement, str) else json.dumps(self.judgement, ensure_ascii=False)
        self.answer_prompts.append(user_text)
        return "안내 드릴게요."


def judged(verdict, relevant, reason="확인"):
    return {"verdict": verdict, "reason": reason, "relevant": relevant}


class RelevanceParsingTests(unittest.TestCase):
    def test_accepts_consistent_judgements(self):
        self.assertEqual(V.parse_relevance(judged("sufficient", [3, 1]), 5), ("sufficient", "확인", [1, 3]))
        self.assertEqual(V.parse_relevance(judged("insufficient", []), 5)[2], [])

    def test_rejects_contradictions_and_bad_shapes(self):
        bad = [
            judged("sufficient", []), judged("partial", []), judged("uncertain", [1]), judged("insufficient", [2]),
            judged("sufficient", [0]), judged("sufficient", [6]), judged("sufficient", [1, 1]), judged("sufficient", ["1"]),
            judged("sufficient", [True]), judged("sufficient", "1"), judged("maybe", [1]), {"verdict": "sufficient", "reason": "x"},
        ]
        for parsed in bad:
            with self.subTest(parsed=parsed), self.assertRaises(ValueError):
                V.parse_relevance(parsed, 5)

    def test_v3_prompt_keeps_legacy_criteria_and_changes_only_the_format(self):
        self.assertIn("문서 제목이 비슷하다는 이유만으로", EVIDENCE_PROMPT_V3)
        self.assertIn('"relevant"', EVIDENCE_PROMPT_V3)
        self.assertNotIn('"relevant"', EVIDENCE_PROMPT)
        self.assertIn("신청 자격이 불명확하더라도", EVIDENCE_PROMPT_V3)


class RetrievalNodeTests(unittest.TestCase):
    def run_node(self, region, **state):
        search = FakeSearch()
        out = V.make_grouped_retrieval_node(search)({"question": "밥 갖다주는 데 없나?", "region": region, **state})
        return out, search

    def test_region_selection_builds_evidence_from_local_then_national(self):
        out, search = self.run_node(REGION)
        self.assertEqual([d["evidence_group"] for d in out["retrieved_docs"]], ["local"] * 3 + ["national"] * 2)
        self.assertEqual(search.calls[0][1], R.select_region("강원", "횡성군"))
        result = out["retrieval_result"]
        self.assertTrue(V.is_v3_result(result))
        self.assertEqual([d["chunk_id"] for d in result["unverified_candidates"]], ["미상자료::1"])
        self.assertNotIn("미상자료::1", [d["chunk_id"] for d in result["documents"]])
        self.assertEqual(out["graph_results"], [])

    def test_no_region_and_explicit_nationwide_are_different(self):
        none, _ = self.run_node(None)
        self.assertEqual({d["evidence_group"] for d in none["retrieved_docs"]}, {"national"})
        nationwide, _ = self.run_node({"kind": "nationwide"})
        self.assertEqual([d["evidence_group"] for d in nationwide["retrieved_docs"]], ["national", "national", "reference"])

    def test_uses_intent_search_query_when_present(self):
        _, search = self.run_node(REGION, search_query="노인 식사 배달 지원")
        self.assertEqual(search.calls[0][0], "노인 식사 배달 지원")

    def test_region_that_cannot_be_resolved_skips_search(self):
        for region, kind in (({"kind": "region", "sido_name": "광주"}, "ambiguous"),
                             ({"kind": "region", "sido_name": "함경북도"}, "unknown"),
                             ({"kind": "city", "sido_name": "서울"}, "invalid")):
            with self.subTest(region=region):
                out, search = self.run_node(region)
                self.assertEqual(search.calls, [])
                self.assertEqual(out["retrieval_result"]["region_error"]["kind"], kind)
                self.assertEqual(V.route_after_grouped_retrieval(out), "region_clarify")
                self.assertIn("다시 골라", V.region_clarify_node(out)["answer"])

    def test_search_errors_are_not_turned_into_region_errors(self):
        def broken(*args, **kwargs):
            raise ConnectionError("Qdrant down")
        with self.assertRaises(ConnectionError):
            V.make_grouped_retrieval_node(broken)({"question": "q", "region": REGION})


class EvidenceNodeTests(unittest.TestCase):
    def state(self):
        out = V.make_grouped_retrieval_node(FakeSearch())({"question": "밥 갖다주는 데 없나?", "region": REGION})
        return {"question": "밥 갖다주는 데 없나?", "region": REGION, **out}

    def test_irrelevant_documents_are_removed_from_evidence(self):
        llm = FakeLLM(judged("sufficient", [1, 4]))
        out = make_evidence_node(llm_call=llm)(self.state())
        self.assertEqual([d["chunk_id"] for d in out["retrieved_docs"]], ["식사배달::1", "sec-급식::1"])
        result = out["retrieval_result"]
        self.assertEqual([d["chunk_id"] for d in result["documents"]], ["식사배달::1", "sec-급식::1"])
        self.assertEqual(result["relevance"], {"status": "judged", "kept": {"local": 1, "national": 1, "reference": 0}, "local_policy_found": True})
        self.assertEqual(sum(c["kept"] for c in result["candidates_before_relevance"]), 2)
        sent = llm.evidence_calls[0][1]["documents"]
        self.assertEqual([d["no"] for d in sent], [1, 2, 3, 4, 5])
        self.assertEqual(sent[0]["evidence_group"], "local")
        self.assertNotIn("미상자료", json.dumps(sent, ensure_ascii=False))   # 지역 미상 자료는 LLM 에 보내지 않는다

    def test_no_relevant_local_policy_is_recorded_only_when_judged(self):
        out = make_evidence_node(llm_call=FakeLLM(judged("partial", [4, 5])))(self.state())
        self.assertEqual(out["retrieval_result"]["relevance"]["local_policy_found"], False)
        self.assertEqual({d["evidence_group"] for d in out["retrieved_docs"]}, {"national"})

    def test_failed_judgement_is_not_reported_as_no_policy(self):
        for judgement in ("JSON 이 아님", judged("sufficient", []), judged("sufficient", [9]), RuntimeError("LLM down")):
            with self.subTest(judgement=str(judgement)[:20]):
                state = self.state()
                out = make_evidence_node(llm_call=FakeLLM(judgement))(state)
                self.assertEqual(out["evidence_verdict"], "uncertain")
                self.assertEqual(out["retrieval_result"]["relevance"], {"status": "failed"})
                self.assertNotIn("retrieved_docs", out)   # 근거를 건드리지 않고, 답변은 만들지 않는다

    def test_uncertain_answer_is_not_recorded_as_no_policy(self):
        # LLM 이 형식에 맞게 "판단하기 어렵다"고 답한 경우. '관련 정책 없음'과 다르다.
        out = make_evidence_node(llm_call=FakeLLM(judged("uncertain", [])))(self.state())
        self.assertEqual(out["evidence_verdict"], "uncertain")
        self.assertEqual(out["retrieval_result"]["relevance"], {"status": "uncertain"})
        self.assertNotIn("local_policy_found", out["retrieval_result"]["relevance"])
        self.assertNotIn("retrieved_docs", out)

    def test_llm_sees_region_status_and_sido_only_instructions(self):
        llm = FakeLLM(judged("sufficient", [1]))
        make_evidence_node(llm_call=llm)(self.state())
        payload = llm.evidence_calls[0][1]
        self.assertEqual(payload["documents"][0]["region_status"], "candidate")
        self.assertEqual(payload["selected_region"], "강원 횡성군")
        sido_only = {"kind": "region", "sido_name": "강원"}
        out = V.make_grouped_retrieval_node(FakeSearch())({"question": "q", "region": sido_only})
        llm = FakeLLM(judged("sufficient", [1]))
        make_evidence_node(llm_call=llm)({"question": "q", "region": sido_only, **out})
        payload = llm.evidence_calls[0][1]
        self.assertIsNone(payload["selected_region"])     # 시스템 지침의 "지역을 다시 묻지 말라"와 부딪치지 않게
        self.assertIn("시·군·구는 아직 모르므로 물어볼 수 있습니다", payload["region_instructions"])
        self.assertIn("시·도는 이미 확인됐으므로 다시 묻지 마세요", payload["region_instructions"])

    def test_insufficient_clears_evidence(self):
        out = make_evidence_node(llm_call=FakeLLM(judged("insufficient", [])))(self.state())
        self.assertEqual(out["evidence_verdict"], "insufficient")
        self.assertEqual(out["retrieved_docs"], [])
        self.assertFalse(out["retrieval_result"]["has_evidence"])

    def test_legacy_result_uses_the_old_prompt_and_keeps_documents(self):
        legacy_docs = [{"id": "u1", "chunk_id": "c1", "parent_id": "p1", "record_type": "policy", "text": "본문", "title": "t", "metadata": {}}]
        state = {"question": "q", "region": None, "retrieved_docs": legacy_docs, "retrieval_result": {"mode": "hybrid", "documents": legacy_docs}}
        llm = FakeLLM({"verdict": "sufficient", "reason": "ok"})
        out = make_evidence_node(llm_call=llm)(state)
        self.assertEqual(out, {"evidence_verdict": "sufficient", "evidence_reason": "ok"})
        self.assertEqual(llm.evidence_calls[0][0], EVIDENCE_PROMPT)
        self.assertNotIn("no", llm.evidence_calls[0][1]["documents"][0])


class GraphTests(unittest.TestCase):
    """실제 그래프를 조립해 끝까지 돌린다. 의도 확인 LLM 만 고정값으로 바꾼다."""

    def setUp(self):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            self.skipTest("langgraph 가 설치되지 않은 환경")
        from src.agents import graph as graph_module
        self.graph_module = graph_module
        intent = patch("src.agents.intent_check.classify_intent",
                       side_effect=lambda question, history, region: {"intent": "search", "search_query": question, "clarification_question": ""})
        intent.start()
        self.addCleanup(intent.stop)

    def invoke(self, judgement, region=REGION, question="혼자 사는데 밥 갖다주는 데 없나?"):
        llm, search = FakeLLM(judgement), FakeSearch()
        graph = self.graph_module.build_graph(grouped_search=search, llm_call=llm)
        result = graph.invoke({"question": question, "session_id": None, "region": region})
        return result, llm, search

    def test_groups_reach_the_answer_step_and_unverified_never_does(self):
        result, llm, _ = self.invoke(judged("sufficient", [1, 4]))
        self.assertEqual(result["answer_status"], "success")
        prompt = llm.answer_prompts[0]
        data = json.loads(prompt.split("\n", 1)[0])
        self.assertEqual([(d["evidence_group"], d["region"], d["region_status"]) for d in data["documents"]],
                         [("local", [HS], "candidate"), ("national", ["national"], None)])
        self.assertIn("담당 기관에서 확인", prompt)
        self.assertNotIn("난임의료비", prompt)    # 관련 없다고 판정된 정책
        self.assertNotIn("미상자료", prompt)      # 적용 지역 미상 자료
        self.assertEqual([s["chunk_id"] for s in result["sources"]], ["식사배달::1", "sec-급식::1"])
        self.assertEqual([d["chunk_id"] for d in result["retrieval_result"]["unverified_candidates"]], ["미상자료::1"])

    def test_answer_is_told_when_no_local_policy_is_relevant(self):
        result, llm, _ = self.invoke(judged("partial", [4]))
        self.assertIn("현재 자료에서 찾지 못했습니다", llm.answer_prompts[0])
        self.assertIn("없다고 단정하지 마세요", llm.answer_prompts[0])
        self.assertEqual(result["retrieval_result"]["relevance"]["local_policy_found"], False)
        found, llm2, _ = self.invoke(judged("sufficient", [1]))
        self.assertNotIn("현재 자료에서 찾지 못했습니다", llm2.answer_prompts[0])

    def test_failed_judgement_gives_no_answer_from_evidence(self):
        result, llm, _ = self.invoke("JSON 이 아님")
        self.assertEqual(result["answer_status"], "no_evidence")
        self.assertEqual(llm.answer_prompts, [])
        self.assertEqual(result["retrieval_result"]["relevance"], {"status": "failed"})
        self.assertNotIn("찾지 못했어요", result["answer"])   # '없음'이 아니라 '확인하기 어려움'으로 안내

    def test_unresolvable_region_ends_with_region_question(self):
        result, llm, search = self.invoke(judged("sufficient", [1]), region={"kind": "region", "sido_name": "광주"})
        self.assertIn("광주광역시인지 경기도 광주시인지", result["answer"])
        self.assertEqual((result["answer_status"], result["sources"]), ("no_evidence", []))
        self.assertEqual((search.calls, llm.evidence_calls, llm.answer_prompts), ([], [], []))

    def test_sido_only_and_nationwide_guidance(self):
        _, llm, _ = self.invoke(judged("sufficient", [1]), region={"kind": "region", "sido_name": "강원"})
        self.assertIn("시·도까지만 골랐습니다", llm.answer_prompts[0])
        data = json.loads(llm.answer_prompts[0].split("\n", 1)[0])
        self.assertIsNone(data["selected_region"])
        self.assertIn("시·군·구는 아직 모르므로 물어볼 수 있습니다", data["region_instructions"])
        _, llm, _ = self.invoke(judged("sufficient", [3]), region={"kind": "nationwide"})
        self.assertIn("사는 지역을 물어보세요", llm.answer_prompts[0])

    def test_urgent_question_never_reaches_search(self):
        result, llm, search = self.invoke(judged("sufficient", [1]), question="그만 살고 싶어.")
        self.assertEqual(result["answer_status"], "safety_response")
        self.assertEqual((search.calls, llm.evidence_calls), ([], []))

    def test_mode_is_chosen_when_the_graph_is_built(self):
        legacy_retriever = lambda question, mode="hybrid", k=12: {"documents": [], "graph_results": [], "has_evidence": False}  # noqa: E731
        nodes = lambda g: set(g.get_graph().nodes)  # noqa: E731
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RAG_RETRIEVAL_MODE", None)
            self.assertNotIn("region_clarify", nodes(self.graph_module.build_graph(retriever=legacy_retriever, llm_call=FakeLLM({}))))
            self.assertNotIn("region_clarify", nodes(self.graph_module.build_graph(mock=True)))
            with patch("src.retrieval.hybrid_retriever.retrieve_welfare", legacy_retriever, create=True):
                legacy = self.graph_module.build_graph(llm_call=FakeLLM({}))
            self.assertNotIn("region_clarify", nodes(legacy))
            os.environ.update({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": "col_a", "RAG_DATA_VERSION": "dv_a"})
            os.environ.pop("QDRANT_COLLECTION_NAME", None)
            v3 = self.graph_module.build_graph(llm_call=FakeLLM({}))
            self.assertIn("region_clarify", nodes(v3))
            self.assertNotIn("region_clarify", nodes(legacy))   # 이미 만든 그래프는 환경 변수가 바뀌어도 그대로다
            os.environ["RAG_RETRIEVAL_MODE"] = "v2"
            with self.assertRaises(RetrievalConfigError):
                self.graph_module.build_graph(llm_call=FakeLLM({}))
            os.environ["RAG_RETRIEVAL_MODE"] = "v3"
            os.environ.pop("RAG_DATA_VERSION")
            with self.assertRaises(RetrievalConfigError):       # v3 인데 데이터 버전이 없으면 그래프를 만들 때 바로 멈춘다
                self.graph_module.build_graph(llm_call=FakeLLM({}))

    def test_built_graph_keeps_searching_the_collection_it_was_built_with(self):
        seen = []

        def fake_search(question, selection, *, settings=None, **kwargs):
            seen.append((settings.collection, settings.data_version))
            return FakeSearch()(question, selection)

        env = {"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": "col_a", "RAG_DATA_VERSION": "dv_a"}
        with patch.dict(os.environ, env, clear=False), patch("src.retrieval.grouped_search.search_grouped", fake_search):
            os.environ.pop("QDRANT_COLLECTION_NAME", None)
            graph = self.graph_module.build_graph(llm_call=FakeLLM(judged("sufficient", [1])))
            os.environ.update({"QDRANT_COLLECTION": "col_b", "RAG_DATA_VERSION": "dv_b"})   # 만든 뒤에 환경 변수가 바뀜
            graph.invoke({"question": "밥 갖다주는 데 없나?", "session_id": None, "region": REGION})
            os.environ["RAG_RETRIEVAL_MODE"] = "legacy_v1"
            graph.invoke({"question": "밥 갖다주는 데 없나?", "session_id": None, "region": REGION})
        self.assertEqual(seen, [("col_a", "dv_a"), ("col_a", "dv_a")])


if __name__ == "__main__":
    unittest.main()
