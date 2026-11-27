"""검색 공통 설정·지역 규칙(B1) 테스트. DB·LLM 없이 돈다."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.retrieval import region_rules as R
from src.retrieval.config import (
    RetrievalConfigError, V3_REQUIRED_INDEXES, load_settings, resolve_collection, resolve_mode, verify_v3_collection,
)

DV = "nationwide_2026_11_26_6efc3b7671b3"


class ModeAndCollectionTests(unittest.TestCase):
    def test_mode_defaults_to_legacy_and_records_that_it_was_not_set(self):
        self.assertEqual(resolve_mode({}), ("legacy_v1", False))
        self.assertEqual(resolve_mode({"RAG_RETRIEVAL_MODE": " legacy_v1 "}), ("legacy_v1", True))
        self.assertEqual(resolve_mode({"RAG_RETRIEVAL_MODE": "v3"}), ("v3", True))

    def test_unknown_mode_is_an_error(self):
        for value in ("V3", "v2", "hybrid", "legacy"):
            with self.subTest(value=value), self.assertRaises(RetrievalConfigError):
                resolve_mode({"RAG_RETRIEVAL_MODE": value})

    def test_collection_name_from_either_variable(self):
        self.assertEqual(resolve_collection({"QDRANT_COLLECTION": "a"}), "a")
        self.assertEqual(resolve_collection({"QDRANT_COLLECTION_NAME": "a"}), "a")
        self.assertEqual(resolve_collection({"QDRANT_COLLECTION": "a", "QDRANT_COLLECTION_NAME": " a "}), "a")

    def test_conflicting_or_missing_collection_is_an_error(self):
        with self.assertRaises(RetrievalConfigError):
            resolve_collection({"QDRANT_COLLECTION": "welfare_chunks_v1", "QDRANT_COLLECTION_NAME": "welfare_chunks_v3_x"})
        with self.assertRaises(RetrievalConfigError):
            resolve_collection({"QDRANT_COLLECTION": "  "})

    def test_legacy_needs_no_data_version_but_v3_does(self):
        legacy = load_settings({"QDRANT_COLLECTION": "welfare_chunks_v1"})
        self.assertEqual((legacy.mode, legacy.mode_explicit, legacy.data_version), ("legacy_v1", False, None))
        with self.assertRaises(RetrievalConfigError):
            load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": "c"})
        v3 = load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": "c", "RAG_DATA_VERSION": DV})
        self.assertEqual((v3.mode, v3.data_version, v3.qdrant_url), ("v3", DV, "http://localhost:6333"))


class FakeQdrant:
    def __init__(self, total=10, matched=10, indexes=V3_REQUIRED_INDEXES, exists=True,
                 vectors=SimpleNamespace(size=1024, distance=SimpleNamespace(value="Cosine")), index_type="keyword"):
        self.total, self.matched, self.indexes, self.exists = total, matched, indexes, exists
        self.vectors, self.index_type = vectors, index_type

    def get_collection(self, name):
        if not self.exists:
            raise KeyError(name)
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=self.vectors)),
            payload_schema={k: SimpleNamespace(data_type=SimpleNamespace(value=self.index_type)) for k in self.indexes},
        )

    def count(self, collection_name, count_filter=None, exact=True):
        return SimpleNamespace(count=self.total if count_filter is None else self.matched)


class V3CollectionCheckTests(unittest.TestCase):
    settings = load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": "c", "RAG_DATA_VERSION": DV})

    def test_passes_when_every_point_is_the_approved_version(self):
        self.assertEqual(verify_v3_collection(FakeQdrant(), self.settings)["points"], 10)

    def test_fails_on_wrong_data_missing_index_empty_or_missing_collection(self):
        cases = {
            "다른 버전이 섞임": FakeQdrant(total=10, matched=9),
            "빈 컬렉션": FakeQdrant(total=0, matched=0),
            "색인 없음": FakeQdrant(indexes=V3_REQUIRED_INDEXES[:-1]),
            "컬렉션 없음": FakeQdrant(exists=False),
            "차원이 다름": FakeQdrant(vectors=SimpleNamespace(size=768, distance="Cosine")),
            "거리 방식이 다름": FakeQdrant(vectors=SimpleNamespace(size=1024, distance="Dot")),
            "이름 붙은 여러 벡터": FakeQdrant(vectors={"dense": SimpleNamespace(size=1024, distance="Cosine")}),
            "색인 종류가 다름": FakeQdrant(index_type="text"),
        }
        for name, client in cases.items():
            with self.subTest(case=name), self.assertRaises(RetrievalConfigError):
                verify_v3_collection(client, self.settings)

    def test_refuses_legacy_settings(self):
        with self.assertRaises(RetrievalConfigError):
            verify_v3_collection(FakeQdrant(), load_settings({"QDRANT_COLLECTION": "c"}))


class SidoNameTests(unittest.TestCase):
    def test_aliases(self):
        for raw, want in {"서울": "서울특별시", "경기": "경기도", "강원도": "강원특별자치도", "전라북도": "전북특별자치도",
                          "전남": "전남광주통합특별시", "전라남도": "전남광주통합특별시", "광주광역시": "전남광주통합특별시",
                          " 제주도 ": "제주특별자치도", "전남광주통합특별시": "전남광주통합특별시"}.items():
            with self.subTest(raw=raw):
                self.assertEqual(R.normalize_sido(raw), want)

    def test_every_alias_points_to_a_known_sido(self):
        self.assertTrue(set(R._ALIASES.values()) <= set(R.SIDO_NAMES))
        self.assertEqual(len(R.SIDO_NAMES), len(set(R.SIDO_NAMES)))

    def test_bare_gwangju_is_ambiguous_and_unknown_sido_is_an_error(self):
        for raw in ("광주", "광주시"):
            with self.subTest(raw=raw), self.assertRaises(R.AmbiguousRegionError):
                R.normalize_sido(raw)
        for raw in ("함경북도", "평양", "횡성군"):
            with self.subTest(raw=raw), self.assertRaises(R.UnknownRegionError):
                R.normalize_sido(raw)
        self.assertIsNone(R.normalize_sido("  "))


class SelectionTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(R.select_region(None), R.NO_REGION)
        self.assertEqual(R.select_region("강원"), R.RegionSelection("sido_only", "강원특별자치도"))
        sel = R.select_region("강원도", "횡성군")
        self.assertEqual((sel.kind, sel.key), ("region", "강원특별자치도|횡성군"))
        self.assertIsNone(R.select_region("강원").key)

    def test_gyeonggi_gwangju_is_kept_and_old_gwangju_districts_move_to_the_merged_city(self):
        self.assertEqual(R.select_region("경기도", "광주시").key, "경기도|광주시")
        self.assertEqual(R.select_region("광주광역시", "서구").key, "전남광주통합특별시|서구")
        self.assertEqual(R.select_region("전라남도", "순천시").key, "전남광주통합특별시|순천시")

    def test_sigungu_without_sido_is_an_error(self):
        with self.assertRaises(R.RegionError):
            R.select_region(None, "횡성군")

    def test_from_chat_request(self):
        self.assertEqual(R.selection_from_request(None), R.NO_REGION)
        # 전국을 직접 고른 것과 고르지 않은 것은 다른 상태로 남긴다.
        self.assertEqual(R.selection_from_request({"kind": "nationwide"}), R.NATIONWIDE)
        self.assertNotEqual(R.NATIONWIDE, R.NO_REGION)
        self.assertEqual(R.selection_from_request({"kind": "region", "sido_name": "전남", "sigungu_name": "순천시"}).key,
                         "전남광주통합특별시|순천시")
        self.assertEqual(R.selection_from_request({"kind": "region", "sido_name": "서울", "sigungu_name": None}).kind, "sido_only")

    def test_bad_requests_and_shapes_are_errors(self):
        for region in ({"kind": "city", "sido_name": "서울"}, {"kind": "region"}, {"kind": "region", "sido_name": " "},
                       {"kind": "nationwide", "sido_name": "서울"}):
            with self.subTest(region=region), self.assertRaises(R.RegionError):
                R.selection_from_request(region)
        for args in (("region", "서울특별시", None), ("sido_only", None, None), ("none", "서울특별시", None), ("city", None, None)):
            with self.subTest(args=args), self.assertRaises(R.RegionError):
                R.RegionSelection(*args)

    def test_keys_from_applies_to(self):
        self.assertEqual(R.keys_from_applies_to([{"sido": "경기도", "sigungu": "광주시"}, {"sido": "경기도", "sigungu": "광주시"}]),
                         ["경기도|광주시"])
        self.assertEqual(R.keys_from_applies_to([]), [])
        with self.assertRaises(R.RegionError):
            R.keys_from_applies_to([{"sido": "경기도", "sigungu": None}])


def meta(record_type="policy", keys=(), sido=None):
    return {"record_type": record_type, "applies_to_keys": list(keys), "sido_name": sido}


class ScopeTests(unittest.TestCase):
    hs = R.select_region("강원", "횡성군")
    gangwon = R.select_region("강원")

    def test_national_guideline_is_national_for_any_selection(self):
        doc = meta("guideline", ["national"])
        for sel in (self.hs, self.gangwon, R.NO_REGION, R.NATIONWIDE):
            self.assertEqual(R.classify_scope(doc, sel), R.NATIONAL)

    def test_guideline_without_national_mark_is_not_evidence(self):
        # PDF라는 이유만으로 전국 자료로 보지 않는다.
        for doc in (meta("guideline", []), meta("guideline", ["강원특별자치도|횡성군"], "강원특별자치도")):
            for sel in (self.hs, self.gangwon, R.NO_REGION, R.NATIONWIDE):
                with self.subTest(doc=doc, sel=sel):
                    self.assertEqual(R.classify_scope(doc, sel), R.OTHER)

    def test_explicit_nationwide_shows_local_policies_as_reference_only(self):
        self.assertEqual(R.classify_scope(meta(keys=["강원특별자치도|횡성군"], sido="강원특별자치도"), R.NATIONWIDE), R.REFERENCE)
        self.assertEqual(R.classify_scope(meta(sido="강원특별자치도"), R.NATIONWIDE), R.OTHER)

    def test_malformed_region_keys_are_rejected(self):
        for keys in (["강원특별자치도|"], ["|횡성군"], ["강원특별자치도"], ["강원특별자치도|횡성군|x"], [None]):
            with self.subTest(keys=keys), self.assertRaises(R.RegionError):
                R.classify_scope(meta(keys=keys, sido="강원특별자치도"), self.gangwon)

    def test_sigungu_selection(self):
        self.assertEqual(R.classify_scope(meta(keys=["강원특별자치도|횡성군"], sido="강원특별자치도"), self.hs), R.LOCAL)
        self.assertEqual(R.classify_scope(meta(keys=["강원특별자치도|강릉시"], sido="강원특별자치도"), self.hs), R.OTHER)
        self.assertEqual(R.classify_scope(meta(keys=["강원특별자치도|강릉시", "강원특별자치도|횡성군"], sido="강원특별자치도"), self.hs), R.LOCAL)

    def test_unverified_is_separate_and_only_for_the_same_sido(self):
        self.assertEqual(R.classify_scope(meta(sido="강원특별자치도"), self.hs), R.UNVERIFIED)
        self.assertEqual(R.classify_scope(meta(sido="강원특별자치도"), self.gangwon), R.UNVERIFIED)
        self.assertEqual(R.classify_scope(meta(sido="경기도"), self.hs), R.OTHER)

    def test_sejong_has_only_unverified_material(self):
        # 세종은 시군구가 없어 시도까지만 고를 수 있고, 지역 미상 자료만 별도 목록에 나온다.
        sejong = R.select_region("세종")
        self.assertEqual(sejong, R.RegionSelection("sido_only", "세종특별자치시"))
        self.assertEqual(R.classify_scope(meta(sido="세종특별자치시"), sejong), R.UNVERIFIED)

    def test_sido_only_selection(self):
        self.assertEqual(R.classify_scope(meta(keys=["강원특별자치도|강릉시"], sido="강원특별자치도"), self.gangwon), R.LOCAL)
        self.assertEqual(R.classify_scope(meta(keys=["경기도|광주시"], sido="경기도"), self.gangwon), R.OTHER)

    def test_no_selection_never_uses_local_policies(self):
        self.assertEqual(R.classify_scope(meta(keys=["강원특별자치도|횡성군"], sido="강원특별자치도"), R.NO_REGION), R.OTHER)
        self.assertEqual(R.classify_scope(meta(sido="강원특별자치도"), R.NO_REGION), R.OTHER)

    def test_payload_without_keys_is_rejected(self):
        with self.assertRaises(R.RegionError):
            R.classify_scope({"record_type": "policy", "sido_name": "강원특별자치도"}, self.hs)


if __name__ == "__main__":
    unittest.main()
