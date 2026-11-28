"""질문 속 지역 이름 읽기 테스트. 데이터의 지역 키 일부를 고정해 쓴다 (DB 없이)."""
from __future__ import annotations

import unittest

from src.retrieval import region_rules as R
from src.retrieval.region_mentions import CLARIFY_MARK, RegionIndex, find_mentions, resolve

KEYS = [
    "강원특별자치도|강릉시", "강원특별자치도|횡성군", "강원특별자치도|고성군", "강원특별자치도|동해시", "강원특별자치도|태백시",
    "경상남도|고성군", "서울특별시|강북구", "서울특별시|강서구", "서울특별시|중구", "부산광역시|중구", "부산광역시|강서구",
    "대구광역시|중구", "경기도|광주시", "경상북도|상주시",
]
INDEX = RegionIndex.from_keys(KEYS)
HS = R.select_region("강원", "횡성군")


def run(question, sido=None, sigungu=None, **kwargs):
    return resolve(R.select_region(sido, sigungu), question, INDEX, **kwargs)


class FindTests(unittest.TestCase):
    def test_full_and_short_names(self):
        for text in ("횡성군에 살아요", "횡성인데 보청기 돼?", "횡성 엄마가", "횡성에서 왔어"):
            with self.subTest(text=text):
                self.assertEqual([m.options for m in find_mentions(text, INDEX)], [{("강원특별자치도", "횡성군")}])

    def test_name_inside_another_word_is_not_a_region(self):
        self.assertEqual([m.options for m in find_mentions("강서구에 살아", INDEX)],
                         [{("서울특별시", "강서구"), ("부산광역시", "강서구")}])   # "서구"를 따로 찾지 않는다
        self.assertEqual(find_mentions("횡성장터에 가요", INDEX), [])            # 짧은 이름 뒤에 다른 글자가 붙음

    def test_common_words_need_a_location_word(self):
        for text in ("고성이 오가는 집이라 무서워", "동해 바다 보러 가고 싶다", "상주가 되어 장례를 치렀어", "경기가 안 좋아"):
            with self.subTest(text=text):
                self.assertEqual(find_mentions(text, INDEX), [])
        self.assertTrue(find_mentions("고성 사는데 보청기 돼?", INDEX))
        self.assertTrue(find_mentions("동해에 살아요", INDEX))

    def test_gwangju_is_never_read_from_text(self):
        self.assertEqual(find_mentions("광주시에 살아요", INDEX), [])
        self.assertEqual(find_mentions("광주에 살아요", INDEX), [])


class ResolveTests(unittest.TestCase):
    def test_no_region_in_text_keeps_screen(self):
        r = run("혼자 사는데 밥 갖다주는 데 없나?", "강원", "강릉시")
        self.assertEqual((r.kind, r.selection), ("keep", R.select_region("강원", "강릉시")))

    def test_sido_only_screen_is_narrowed_by_text(self):
        r = run("횡성인데 보청기 돼?", "강원")
        self.assertEqual((r.kind, r.selection), ("use", HS))

    def test_no_screen_uses_text(self):
        self.assertEqual(run("횡성 보청기").selection, HS)
        self.assertEqual(run("서울 강서구 사는데 쌀 지원 있어?").selection, R.select_region("서울", "강서구"))
        self.assertEqual(run("서울 사는데 쌀 지원 있어?").selection, R.select_region("서울"))
        r = resolve(R.NATIONWIDE, "횡성 보청기", INDEX)   # 전국을 고른 상태에서 말한 지역
        self.assertEqual(r.selection, HS)

    def test_same_region_as_screen_keeps_screen(self):
        for q in ("횡성에 혼자 계신 아버지, 도시락 배달 되나요?", "강원도 횡성군인데요", "강원 사는데"):
            with self.subTest(q=q):
                self.assertEqual(run(q, "강원", "횡성군").kind, "keep")

    def test_different_sigungu_asks(self):
        r = run("횡성 엄마가 밥을 못 챙겨 드세요. 도시락 되나요?", "강원", "강릉시")
        self.assertEqual(r.kind, "ask")
        self.assertIn(CLARIFY_MARK, r.message)
        self.assertEqual(r.choices, ["강원특별자치도 강릉시 기준", "강원특별자치도 횡성군 기준"])
        self.assertEqual(r.selection, R.select_region("강원", "강릉시"))   # 묻는 동안 검색 지역을 바꾸지 않는다

    def test_comparison_with_here_keeps_screen(self):
        r = run("횡성은 밥 갖다준다던데 여긴 왜 없어?", "강원", "강릉시")
        self.assertEqual((r.kind, r.selection, r.compared), ("keep", R.select_region("강원", "강릉시"), [("강원특별자치도", "횡성군")]))

    def test_other_sido_is_asked_unless_it_is_a_comparison(self):
        # 다른 시도를 말하면 다른 사람 이야기일 수도 있지만, 그 지역 기준으로 찾으려는 것일 수도 있어 묻는다.
        for q in ("서울 엄마 도시락 지원돼?", "서울 사는 아들이 안 와"):
            with self.subTest(q=q):
                self.assertEqual(run(q, "강원", "강릉시").kind, "ask")
        r = run("서울은 쌀 준다던데 여기는 없어?", "강원", "강릉시")
        self.assertEqual((r.kind, r.compared), ("keep", [("서울특별시", None)]))

    def test_here_with_a_change_word_is_not_a_comparison(self):
        self.assertEqual(run("여기 말고 횡성 엄마 기준으로 찾아 줘", "강원", "강릉시").kind, "ask")

    def test_words_that_only_look_like_regions(self):
        for q in ("경기 회복이 안 돼요", "중구난방으로 얘기해서 미안해", "강북구청에 가 봤어"):
            with self.subTest(q=q):
                self.assertEqual(run(q, "강원", "강릉시").kind, "keep")

    def test_gyeonggi_gwangju_is_read_only_with_its_province(self):
        self.assertEqual(run("경기도 광주시에 살아").selection, R.select_region("경기도", "광주시"))
        self.assertEqual(run("경기 광주 사는데").selection, R.select_region("경기도", "광주시"))
        self.assertEqual(run("광주 사는데").kind, "keep")   # 어느 광주인지 글만으로는 알 수 없다

    def test_place_not_in_the_list_is_not_silently_replaced(self):
        # "분당구"처럼 지역 꼴인데 목록에 없는 말은 '확인하지 못한 지역'으로 남긴다.
        r = run("분당구에 사는데 보청기 돼?", "강원", "강릉시")
        self.assertEqual((r.kind, r.unknown_places, r.choices), ("ask", ["분당구"], ["강원특별자치도 강릉시 기준"]))
        self.assertIn(CLARIFY_MARK, r.message)                                  # 화면 지역으로 대신하지 않고 묻는다
        r = run("분당구에 사는데 보청기 돼?")
        self.assertEqual((r.kind, r.choices), ("ask", []))
        # 물음에 "강릉시 기준"이나 목록에 있는 지역으로 답하면 그대로 받는다
        self.assertEqual(run("강원특별자치도 강릉시 기준", "강원", "강릉시", answering_region_question=True).kind, "keep")
        self.assertEqual(run("성남시예요", "강원", "강릉시", answering_region_question=True).kind, "keep")  # 목록에 없는 이름 (시험용 목록)
        for q in ("신도시에 살아", "대도시에 사는 아들"):                        # 지역 이름이 아닌 말
            with self.subTest(q=q):
                self.assertEqual(run(q, "강원", "강릉시").unknown_places, [])

    def test_refusal_is_not_a_choice_whatever_the_screen(self):
        from src.retrieval.region_mentions import confirmed_from_history
        for screen in ((None, None), ("강원", None), ("강원", "강릉시"), ("강원", "횡성군")):
            for q in ("횡성 말고요", "아니요 횡성 아니에요", "모르겠어요"):
                with self.subTest(screen=screen, q=q):
                    r = run(q, *screen, answering_region_question=True)
                    self.assertEqual((r.kind, r.refused, r.mentioned), ("keep", True, []))
        history = [{"role": "assistant", "content": "말씀하신 '분당구'을(를) … " + CLARIFY_MARK}, {"role": "user", "content": "횡성 말고요"}]
        self.assertIsNone(confirmed_from_history(R.select_region("강원"), history, INDEX))

    def test_known_sido_with_unknown_place_still_asks(self):
        r = run("강원도 주문진읍에 사는데 경로당 있어?", "강원", "횡성군")
        self.assertEqual((r.kind, r.unknown_places), ("ask", ["주문진읍"]))

    def test_chosen_region_is_dropped_when_the_screen_changed(self):
        from src.retrieval.region_mentions import confirmed_from_history
        history = [{"role": "user", "content": "횡성 엄마가 밥을 못 챙겨 드세요."},
                   {"role": "assistant", "content": "화면에서 고르신 지역은 강원특별자치도 강릉시인데, 말씀에는 … " + CLARIFY_MARK},
                   {"role": "user", "content": "강원특별자치도 횡성군 기준"}]
        self.assertEqual(confirmed_from_history(R.select_region("강원", "강릉시"), history, INDEX), HS)
        self.assertIsNone(confirmed_from_history(R.select_region("강원", "태백시"), history, INDEX))

    def test_same_name_in_several_sidos(self):
        self.assertEqual(run("고성 사는데 보청기 돼?").kind, "ask")                       # 강원·경남 고성군
        self.assertEqual(run("고성 사는데 보청기 돼?", "강원").selection, R.select_region("강원", "고성군"))
        self.assertEqual(run("경남 고성군 사는데").selection, R.select_region("경남", "고성군"))
        r = run("중구에 사는데 경로당 어디야")
        self.assertEqual((r.kind, len(r.choices)), ("ask", 3))
        self.assertEqual(run("중구에 사는데", "부산").selection, R.select_region("부산", "중구"))

    def test_several_regions_ask(self):
        r = run("횡성 엄마랑 태백 아빠 둘 다 밥을 못 챙겨", "강원")
        self.assertEqual(r.kind, "ask")
        self.assertEqual(r.choices, ["강원특별자치도 횡성군", "강원특별자치도 태백시"])

    def test_answer_to_region_question_is_accepted(self):
        r = run("강원특별자치도 횡성군 기준", "강원", "강릉시", answering_region_question=True)
        self.assertEqual((r.kind, r.selection), ("use", HS))
        self.assertEqual(run("강원특별자치도 강릉시 기준", "강원", "강릉시", answering_region_question=True).kind, "keep")


if __name__ == "__main__":
    unittest.main()
