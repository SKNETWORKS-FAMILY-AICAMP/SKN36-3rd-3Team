"""묶음별 검색(B2) 테스트. 가짜 Qdrant 로 돈다 (DB·모델 없이)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.retrieval import grouped_search as G
from src.retrieval import region_rules as R
from src.retrieval.config import RetrievalConfigError, V3_REQUIRED_INDEXES, load_settings

DV = "nationwide_2026_11_26_6efc3b7671b3"
SETTINGS = load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": "c", "RAG_DATA_VERSION": DV})
VECTOR = [0.0] * 1023 + [1.0]


def point(pid, score, *, kind="policy", keys=(), sido=None, scope="candidate", chunk=1, section=None,
          version=DV, status="approved"):
    md = {"record_type": kind, "applies_to_keys": list(keys), "sido_name": sido, "scope_status": scope,
          "data_version": version, "release_status": status, "chunk_id": f"{pid}::{chunk}", "parent_id": section or pid,
          "policy_id": pid if kind == "policy" else None, "section_id": section if kind == "guideline" else None,
          "title": pid, "source_url": None}
    return SimpleNamespace(id=f"{pid}-{chunk}", score=score, payload={"page_content": f"{pid} 본문", "metadata": md})


def guide(section, score, chunk=1, keys=("national",)):
    return point(section, score, kind="guideline", keys=keys, scope=None, chunk=chunk, section=section)


class FakeQdrant:
    """dict 필터(must / must_not 의 match.value)를 payload 에 적용하고 점수순으로 돌려준다."""

    def __init__(self, points):
        self.points, self.calls = list(points), []

    def get_collection(self, name):
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=1024, distance="Cosine"))),
            payload_schema={k: SimpleNamespace(data_type="keyword") for k in V3_REQUIRED_INDEXES},
        )

    @staticmethod
    def _ok(p, flt):
        def hit(cond):
            value = p.payload["metadata"].get(cond["key"].split(".", 1)[1])
            want = cond["match"]["value"]
            return want in value if isinstance(value, list) else value == want
        return all(hit(c) for c in (flt or {}).get("must", [])) and not any(hit(c) for c in (flt or {}).get("must_not", []))

    def count(self, collection_name, count_filter=None, exact=True):
        return SimpleNamespace(count=sum(self._ok(p, count_filter) for p in self.points))

    def query_points(self, collection_name, query, query_filter=None, limit=10, offset=0, **kwargs):
        self.calls.append({"filter": query_filter, "limit": limit, "offset": offset, **kwargs})
        rows = sorted((p for p in self.points if self._ok(p, query_filter)), key=lambda p: -p.score)
        return SimpleNamespace(points=rows[offset:offset + limit])


HS, GN = "강원특별자치도|횡성군", "강원특별자치도|강릉시"
BASE = [
    point("hs-meal", 0.50, keys=[HS], sido="강원특별자치도"),
    point("hs-meal", 0.45, keys=[HS], sido="강원특별자치도", chunk=2),
    point("hs-bath", 0.30, keys=[HS], sido="강원특별자치도"),
    point("gn-hair", 0.60, keys=[GN], sido="강원특별자치도"),
    point("gg-meal", 0.70, keys=["경기도|광주시"], sido="경기도"),
    point("gw-unknown", 0.40, sido="강원특별자치도", scope="unknown"),
    point("gg-unknown", 0.90, sido="경기도", scope="unknown"),
    guide("sec-a", 0.80), guide("sec-a", 0.79, 2), guide("sec-a", 0.78, 3), guide("sec-b", 0.20),
]


def run(selection, points=BASE, **kwargs):
    G._verified.clear()
    client = FakeQdrant(points)
    out = G.search_grouped("밥 갖다주는 데 없나?", selection, settings=SETTINGS, client=client, embed=lambda q: VECTOR, **kwargs)
    return out, client


def ids(docs):
    return [d["policy_id"] or d["section_id"] for d in docs]


class GroupTests(unittest.TestCase):
    def test_sigungu_selection_separates_groups(self):
        out, client = run(R.select_region("강원", "횡성군"))
        self.assertEqual(ids(out["local"]), ["hs-meal", "hs-bath"])           # 정책 단위로 한 번씩, 다른 지역 정책 없음
        self.assertEqual(out["local"][0]["chunk_id"], "hs-meal::1")           # 정책마다 점수가 가장 높은 청크
        self.assertEqual(ids(out["national"]), ["sec-a", "sec-a", "sec-b"])   # 같은 절은 2개까지
        self.assertEqual(ids(out["unverified"]), ["gw-unknown"])             # 같은 시도의 지역 미상만, 별도 목록
        self.assertEqual(out["reference"], [])
        self.assertEqual({d["evidence_group"] for d in out["local"]}, {"local"})
        self.assertEqual(out["info"]["dropped"], {})
        self.assertEqual(out["info"]["short"], [])

    def test_every_query_carries_version_and_approval_filter(self):
        _, client = run(R.select_region("강원", "횡성군"))
        self.assertEqual(len(client.calls), 3)
        for call in client.calls:
            must = {(c["key"], c["match"]["value"]) for c in call["filter"]["must"]}
            self.assertIn(("metadata.data_version", DV), must)
            self.assertIn(("metadata.release_status", "approved"), must)

    def test_sido_only_returns_candidates_of_that_sido_with_their_region(self):
        out, _ = run(R.select_region("강원"))
        self.assertEqual(ids(out["local"]), ["gn-hair", "hs-meal", "hs-bath"])
        self.assertEqual(out["local"][0]["region_keys"], [GN])
        self.assertEqual(ids(out["unverified"]), ["gw-unknown"])

    def test_explicit_nationwide_gives_reference_not_local(self):
        out, _ = run(R.NATIONWIDE)
        self.assertEqual(out["local"], [])
        self.assertEqual(ids(out["reference"]), ["gg-meal", "gn-hair", "hs-meal", "hs-bath"])
        self.assertEqual(out["unverified"], [])

    def test_no_selection_gives_national_only(self):
        out, client = run(R.NO_REGION)
        self.assertEqual((out["local"], out["reference"], out["unverified"]), ([], [], []))
        self.assertEqual(len(out["national"]), 3)
        self.assertEqual(len(client.calls), 1)

    def test_region_without_policy_returns_empty_local(self):
        out, _ = run(R.select_region("강원", "태백시"))
        self.assertEqual(out["local"], [])
        self.assertEqual(ids(out["unverified"]), ["gw-unknown"])


class SafetyNetTests(unittest.TestCase):
    def test_keeps_fetching_until_k_policies(self):
        many = [point("big", 0.9 - i * 0.001, keys=[HS], sido="강원특별자치도", chunk=i) for i in range(70)]
        many += [point(f"p{i}", 0.5 - i * 0.01, keys=[HS], sido="강원특별자치도") for i in range(3)]
        out, client = run(R.select_region("강원", "횡성군"), points=many + [guide("sec-a", 0.1)], local_k=3)
        self.assertEqual(ids(out["local"]), ["big", "p0", "p1"])
        local_calls = [c for c in client.calls if any(m["key"] == "metadata.applies_to_keys" and m["match"]["value"] == HS for m in c["filter"]["must"])]
        # 근사 검색 첫 쪽으로 모자라면, 순서가 고정되는 전수 비교로 처음부터 다시 받는다.
        self.assertEqual([(c["offset"], c["search_params"]) for c in local_calls],
                         [(0, None), (0, {"exact": True}), (G.PAGE, {"exact": True})])

    def test_unstable_first_page_cannot_cause_duplicates_or_gaps(self):
        # 근사 검색이 쪽마다 다른 순서를 돌려주는 상황: 근사 쪽은 뒤집힌 순서, 전수 비교는 올바른 순서.
        class Unstable(FakeQdrant):
            def query_points(self, collection_name, query, query_filter=None, limit=10, offset=0, **kwargs):
                res = super().query_points(collection_name, query, query_filter, limit, offset, **kwargs)
                if not kwargs.get("search_params"):
                    res.points = list(reversed(res.points)) + res.points[:1]   # 순서가 다르고 같은 포인트가 다시 나옴
                return res
        many = [point("big", 0.9 - i * 0.001, keys=[HS], sido="강원특별자치도", chunk=i) for i in range(70)]
        many += [point(f"p{i}", 0.5 - i * 0.01, keys=[HS], sido="강원특별자치도") for i in range(3)]
        G._verified.clear()
        out = G.search_grouped("q", R.select_region("강원", "횡성군"), settings=SETTINGS,
                               client=Unstable(many + [guide("sec-a", 0.1)]), embed=lambda q: VECTOR, local_k=3)
        self.assertEqual(ids(out["local"]), ["big", "p0", "p1"])

    def test_same_point_twice_takes_one_slot(self):
        class Repeating(FakeQdrant):
            def query_points(self, *args, **kwargs):
                res = super().query_points(*args, **kwargs)
                res.points = [p for p in res.points for _ in range(2)]
                return res
        G._verified.clear()
        out = G.search_grouped("q", R.NO_REGION, settings=SETTINGS, client=Repeating(BASE), embed=lambda q: VECTOR)
        self.assertEqual([d["chunk_id"] for d in out["national"]], ["sec-a::1", "sec-a::2", "sec-b::1"])

    def test_successful_collection_check_is_reused(self):
        class Counting(FakeQdrant):
            checks = 0

            def get_collection(self, name):
                Counting.checks += 1
                return super().get_collection(name)
        G._verified.clear()
        client = Counting(BASE)
        for _ in range(3):
            G.search_grouped("q", R.NO_REGION, settings=SETTINGS, client=client, embed=lambda q: VECTOR)
        self.assertEqual(Counting.checks, 1)

    def test_reports_short_when_limit_reached(self):
        many = [point("big", 0.9 - i * 0.0001, keys=[HS], sido="강원특별자치도", chunk=i) for i in range(G.PAGE * G.MAX_PAGES)]
        out, _ = run(R.select_region("강원", "횡성군"), points=many + [guide("sec-a", 0.1)], local_k=2)
        self.assertEqual(ids(out["local"]), ["big"])
        self.assertIn("local", out["info"]["short"])

    def test_wrong_scope_is_dropped_and_counted(self):
        # 필터는 통과했지만 지역 규칙과 맞지 않는 자료(전국 표시가 없는 PDF)를 흉내 낸다.
        class Leaky(FakeQdrant):
            def query_points(self, collection_name, query, query_filter=None, limit=10, offset=0, **kwargs):
                res = super().query_points(collection_name, query, query_filter, limit, offset, **kwargs)
                if any(c["match"]["value"] == "national" for c in query_filter["must"]) and offset == 0:
                    res.points.insert(0, guide("sec-local", 0.99, keys=(HS,)))
                return res
        G._verified.clear()
        out = G.search_grouped("q", R.select_region("강원", "횡성군"), settings=SETTINGS, client=Leaky(BASE), embed=lambda q: VECTOR)
        self.assertNotIn("sec-local", ids(out["national"]))
        self.assertEqual(out["info"]["dropped"], {"national": 1})

    def test_unapproved_or_other_version_stops_the_search(self):
        class Dirty(FakeQdrant):
            def __init__(self, points, bad):
                super().__init__(points)
                self.bad = bad

            def query_points(self, *args, **kwargs):
                res = super().query_points(*args, **kwargs)
                res.points.insert(0, self.bad)
                return res
        for bad in (guide("sec-x", 0.99), guide("sec-y", 0.99)):
            bad.payload["metadata"]["release_status" if bad.id.startswith("sec-x") else "data_version"] = "draft"
            G._verified.clear()
            with self.subTest(bad=bad.id), self.assertRaises(RetrievalConfigError):
                G.search_grouped("q", R.NO_REGION, settings=SETTINGS, client=Dirty(BASE, bad), embed=lambda q: VECTOR)

    def test_refuses_legacy_mode_and_bad_inputs(self):
        legacy = load_settings({"QDRANT_COLLECTION": "c"})
        with self.assertRaises(RetrievalConfigError):
            G.search_grouped("q", R.NO_REGION, settings=legacy, client=FakeQdrant(BASE), embed=lambda q: VECTOR)
        for kwargs in ({"local_k": 0}, {"national_k": 21}, {"unverified_k": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run(R.NO_REGION, **kwargs)
        with self.assertRaises(ValueError):
            G.search_grouped(" ", R.NO_REGION, settings=SETTINGS, client=FakeQdrant(BASE), embed=lambda q: VECTOR)
        with self.assertRaises(TypeError):
            G.search_grouped("q", {"kind": "region"}, settings=SETTINGS, client=FakeQdrant(BASE), embed=lambda q: VECTOR)

    def test_bad_question_vector_is_rejected(self):
        for vec in ([0.1] * 768, [float("nan")] * 1024, [float("inf")] + [0.0] * 1023, [0.0] * 1024):
            G._verified.clear()
            with self.subTest(n=len(vec)), self.assertRaises(RuntimeError):
                G.search_grouped("q", R.NO_REGION, settings=SETTINGS, client=FakeQdrant(BASE), embed=lambda q, v=vec: v)

    def test_server_side_errors_are_not_value_errors(self):
        # API 는 ValueError 를 사용자 입력 오류(400)로 돌려준다. 설정·검색 문제는 거기에 섞이면 안 된다.
        self.assertFalse(issubclass(RetrievalConfigError, ValueError))

    def test_collection_check_failure_stops_search_and_is_not_cached(self):
        class NoIndex(FakeQdrant):
            def get_collection(self, name):
                return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=1024, distance="Cosine"))),
                                       payload_schema={})
        G._verified.clear()
        bad = NoIndex(BASE)
        for _ in range(2):   # 실패는 기억하지 않으므로 두 번 다 점검에서 멈춘다
            with self.assertRaises(RetrievalConfigError):
                G.search_grouped("q", R.NO_REGION, settings=SETTINGS, client=bad, embed=lambda q: VECTOR)
        self.assertEqual(bad.calls, [])
        self.assertEqual(G._verified, set())

    def test_default_client_uses_the_server_in_settings(self):
        other = load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": "c", "RAG_DATA_VERSION": DV,
                               "QDRANT_URL": "http://other-host:6333"})
        G._verified.clear()
        with patch.object(G, "_client_for", return_value=FakeQdrant(BASE)) as make:
            out = G.search_grouped("q", R.NO_REGION, settings=other, embed=lambda q: VECTOR)
        make.assert_called_once_with("http://other-host:6333")
        self.assertEqual(out["info"]["qdrant_url"], "http://other-host:6333")

    def test_exact_flag_is_passed_to_qdrant(self):
        _, client = run(R.NO_REGION, exact=True)
        self.assertEqual(client.calls[0]["search_params"], {"exact": True})
        _, client = run(R.NO_REGION)
        self.assertIsNone(client.calls[0]["search_params"])


if __name__ == "__main__":
    unittest.main()
