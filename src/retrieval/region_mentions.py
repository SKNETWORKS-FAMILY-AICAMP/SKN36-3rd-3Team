"""질문 속 지역 이름 읽기 (B3 보완).

화면에서 고른 지역과 질문에서 말한 지역을 함께 보고, 어느 지역으로 검색할지 정한다.

- 화면은 시도까지만 골랐고 질문에 그 시도의 시군구가 나오면 → 그 시군구로 좁힌다 ("횡성인데 보청기 돼?").
- 화면에서 고른 지역과 질문 속 지역이 다르면 → 추측하지 않고 어느 지역 기준인지 묻는다 ("횡성 엄마가…", "서울 엄마…").
  다만 "여기/여긴/우리 동네" 같은 말이 있고 "말고/대신/기준" 같은 바꾸는 말이 없으면 다른 지역은 비교로 보고
  화면 지역을 그대로 쓴다 ("횡성은 준다던데 여긴 왜 없어?").
- 앞 대화에서 지역을 물어 사용자가 고른 지역은, 그 뒤의 질문에서도 계속 쓴다 (confirmed_from_history).
  구조화된 대화 상태가 없어 앞 대화 글로 판단하는 임시 방법이다. 불러오는 대화 기록(최근 8개 메시지)에서
  물었던 말이 밀려나면 확정 지역도 잊는다. 물을 때의 화면 지역과 지금 화면 지역이 다르면 예전 선택은 버린다.
- "○○구에 사는데"처럼 지역 꼴인데 이름 목록에 없는 말(일반구·읍면동 등)은 화면 지역으로 대신하지 않고 묻는다
  (화면 지역이 있으면 "그 지역 기준" 선택지를 함께 준다).
- 화면에서 지역을 고르지 않았으면 질문 속 지역을 쓴다.
- 같은 이름이 여러 시도에 있으면(고성군, 중구 등) 질문 속 시도 → 화면 시도 순으로 정하고, 그래도 안 되면 묻는다.

지역 이름 목록은 데이터에 있는 지역 키("시도|시군구")에서 만든다. 데이터에 없는 지역 이름은 알아보지 못한다.
글자 맞추기 규칙이라 놓치거나 잘못 읽을 수 있다. 잘못 읽으면 엉뚱한 지역을 검색하지 않고 묻는 쪽으로 기울게 했다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from . import region_rules as R

# 앞 대화의 이 문구가 있으면 사용자가 지역을 골라 답하는 차례로 본다 (같은 지역 질문을 되풀이하지 않게).
CLARIFY_MARK = "어느 지역 기준으로 찾아 드릴까요?"
_HERE = re.compile(r"여기|여긴|이곳|이 동네|우리 동네|이 지역|우리 지역|사는 곳")
_CHANGE = re.compile(r"말고|아니고|아니라|대신|기준")   # 지역을 바꾸려는 말. 있으면 비교로 보지 않는다.
_REFUSE = re.compile(r"말고|아니고|아니라|아니요|아뇨|아닌데|싫|없어요|모르")   # 지역을 묻는 말에 대한 거절·부정
_PEOPLE = ("엄마", "아빠", "어머니", "아버지", "부모", "아들", "딸", "할머니", "할아버지", "동생", "형", "누나", "언니", "오빠",
           "남편", "아내", "영감", "친구", "이모", "고모", "삼촌")
# 짧은 이름(시·군·구를 뺀 "횡성") 뒤에 올 수 있는 말. 흔한 낱말과 겹치는 이름은 위치를 뜻하는 말이나 사람이 올 때만 지역으로 본다.
_STRONG_AFTER = ("에서", "에", "인데", "사는", "살아", "살고", "산다", "사시", "계신", "거주", "쪽", "지역") + _PEOPLE
_COMMON_WORD_SIDO = {"경기"}   # 시도 별칭 가운데 흔한 낱말과 겹치는 것 ("경기 회복")
_WEAK_AFTER = _STRONG_AFTER + ("이에요", "이야", "이고", "은", "는", "도", "의", " ", ",", ".", "?", "!")
# 지역 꼴의 말 ("분당구에 사는데", "주문진읍에 살아"). 이름 목록에 없으면 '확인하지 못한 지역'으로 남긴다.
_PLACE_LIKE = re.compile(r"(?<![가-힣])([가-힣]{2,6}(?:구|읍|면|동|시|군))(?=\s*(?:에서|에|인데|사는|살아|살고|산다|사시|계신|거주))")
_NOT_PLACES = {"도시", "대도시", "소도시", "신도시", "광역시", "특별시", "지역구", "선거구", "관할구", "자치구", "시군구",
               "주민센터동", "아파트단지동"}
_SCREEN_IN_MESSAGE = re.compile(r"화면에서 고르신 지역은 (.+?)인데")
_GYEONGGI_GWANGJU = re.compile(r"(?<![가-힣])(경기도|경기)\s*광주(시)?")
_COMMON_WORD_STEMS = {"고성", "상주", "동해", "남해", "양산", "보성", "청도", "진도", "완도", "광주", "영광", "광명"}
_SKIP_NAMES = {"광주시", "광주"}   # 경기도 광주시와 옛 광주광역시를 글자만으로 가를 수 없다. 화면 선택으로만 받는다.


def _hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


@dataclass
class RegionIndex:
    """지역 키 목록으로 만든 이름표. 이름(전체·짧은 이름) → 해당하는 (시도, 시군구) 들."""
    sigungu: dict[str, set[tuple[str, str]]] = field(default_factory=dict)
    sido: dict[str, str] = field(default_factory=dict)
    all_regions: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def from_keys(cls, keys: Iterable[str]) -> "RegionIndex":
        index = cls()
        for key in keys:
            if "|" not in str(key):
                continue
            sido, sigungu = str(key).split("|", 1)
            index.all_regions.add((sido, sigungu))
            if sigungu in _SKIP_NAMES:
                continue
            index.sigungu.setdefault(sigungu, set()).add((sido, sigungu))
            stem = sigungu[:-1]
            if sigungu[-1] in "시군구" and len(stem) >= 2 and stem not in _SKIP_NAMES:
                index.sigungu.setdefault(stem, set()).add((sido, sigungu))
        for name in R.SIDO_NAMES:
            index.sido[name] = name
        for alias, name in R._ALIASES.items():
            if alias not in _SKIP_NAMES:
                index.sido[alias] = name
        return index


def _matches(text: str, surface: str, *, short: bool, risky: bool) -> list[tuple[int, int]]:
    spans = []
    for m in re.finditer(re.escape(surface), text):
        start, end = m.span()
        if start and _hangul(text[start - 1]):
            continue   # 다른 낱말의 일부 ("강서구" 안의 "서구")
        rest = text[end:]
        if risky:   # 흔한 낱말과 겹치는 이름은 위치를 뜻하는 말이나 사람이 올 때만 ("고성 사는데" O, "고성이 오가는" X)
            if rest and not rest.lstrip(" ").startswith(_STRONG_AFTER):
                continue
        elif short:
            if rest and not rest.startswith(_WEAK_AFTER):
                continue
        elif rest and _hangul(rest[0]) and not rest.startswith(_WEAK_AFTER):
            continue   # 전체 이름 뒤에 다른 글자가 붙어 낱말이 됨 ("중구난방")
        spans.append((start, end))
    return spans


@dataclass
class Mention:
    start: int
    end: int
    sido: str | None = None                                   # 시도를 말한 경우
    options: set[tuple[str, str]] = field(default_factory=set)  # 시군구를 말한 경우 후보


def find_mentions(text: str, index: RegionIndex) -> list[Mention]:
    """글 속의 시도·시군구 이름을 찾는다. 긴 이름부터 찾고, 이미 찾은 자리와 겹치는 짧은 이름은 버린다."""
    taken: list[tuple[int, int]] = []
    found: list[Mention] = []

    def free(span):
        return all(span[1] <= a or span[0] >= b for a, b in taken)

    # "경기도 광주시"처럼 시도와 함께 말하면 광주시도 알아본다 (광주 혼자서는 읽지 않는다).
    for m in _GYEONGGI_GWANGJU.finditer(text):
        if ("경기도", "광주시") in index.all_regions:
            taken.append(m.span())
            found.append(Mention(*m.span(), options={("경기도", "광주시")}))
    # "서울 강서구", "경남 고성군"처럼 시도 바로 뒤에 그 시도의 시군구가 오면 한 지역으로 묶어 먼저 찾는다.
    for surface in sorted(index.sido, key=len, reverse=True):
        sido = index.sido[surface]
        for m in re.finditer(re.escape(surface), text):
            if (m.start() and _hangul(text[m.start() - 1])) or not free(m.span()):
                continue
            gap = len(text[m.end():]) - len(text[m.end():].lstrip(" "))
            after = m.end() + gap
            for name in sorted(index.sigungu, key=len, reverse=True):
                pairs_ = [(s, g) for s, g in index.sigungu[name] if s == sido]
                if pairs_ and text.startswith(name, after):
                    rest = text[after + len(name):]
                    full = any(name == g for _, g in pairs_)
                    if rest and _hangul(rest[0]) and not rest.startswith(_WEAK_AFTER) and not (not full and rest[0] in "시군구"):
                        continue
                    span = (m.start(), after + len(name) + (1 if not full and rest[:1] in ("시", "군", "구") else 0))
                    taken.append(span)
                    found.append(Mention(*span, options=set(pairs_)))
                    break
    for surface in sorted(index.sido, key=len, reverse=True):
        # 흔한 낱말과 겹치는 시도 별칭("경기")은 위치를 뜻하는 말이나 사람이 올 때만 ("경기 회복" X)
        for span in _matches(text, surface, short=len(surface) <= 2, risky=surface in _COMMON_WORD_SIDO):
            if free(span):
                taken.append(span)
                found.append(Mention(*span, sido=index.sido[surface]))
    for surface in sorted(index.sigungu, key=len, reverse=True):
        options = index.sigungu[surface]
        full = any(surface == g for _, g in options)
        for span in _matches(text, surface, short=not full, risky=surface in _COMMON_WORD_STEMS):
            if free(span):
                taken.append(span)
                found.append(Mention(*span, options=set(options)))
    return sorted(found, key=lambda m: m.start)


@dataclass
class Resolution:
    """어느 지역으로 검색할지. kind: keep(화면 그대로) / use(질문 속 지역 사용) / ask(물어봐야 함)."""
    kind: str
    selection: R.RegionSelection
    mentioned: list[tuple[str, str | None]] = field(default_factory=list)   # 질문 속 지역 (시도, 시군구)
    compared: list[tuple[str, str | None]] = field(default_factory=list)    # 비교로만 언급한 다른 지역
    message: str = ""
    choices: list[str] = field(default_factory=list)
    unknown_places: list[str] = field(default_factory=list)                 # 지역 꼴인데 목록에 없는 말
    refused: bool = False                                                   # 지역을 묻는 말에 거절·부정으로 답함


def unknown_places(text: str, index: RegionIndex, mentions: list[Mention]) -> list[str]:
    """지역 꼴인데 이름 목록에 없는 말. 이미 알아본 지역 이름과 겹치는 자리는 뺀다."""
    out = []
    for m in _PLACE_LIKE.finditer(text):
        word = m.group(1)
        if word in _NOT_PLACES or word in index.sigungu or word in index.sido:
            continue
        if any(not (m.end(1) <= x.start or m.start(1) >= x.end) for x in mentions):
            continue
        out.append(word)
    return list(dict.fromkeys(out))


def _label(region: tuple[str, str | None]) -> str:
    return " ".join(x for x in region if x)


def _ask(selection, message, choices, mentioned) -> Resolution:
    text = message + ("\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(choices, 1)) if choices else "")
    return Resolution("ask", selection, mentioned=mentioned, message=text, choices=choices)


def confirmed_from_history(screen: R.RegionSelection, history: list[dict], index: RegionIndex) -> R.RegionSelection | None:
    """앞 대화에서 지역을 물었고 사용자가 답한 지역이 있으면 그 지역 (가장 최근 것). 없으면 None."""
    confirmed = None
    screen_label = _label((screen.sido, screen.sigungu))
    for i, turn in enumerate(history[:-1]):
        nxt = history[i + 1]
        if turn.get("role") == "assistant" and CLARIFY_MARK in _content(turn) and nxt.get("role") == "user":
            asked_with = _SCREEN_IN_MESSAGE.search(_content(turn))
            if asked_with and asked_with.group(1) != screen_label:
                continue   # 물을 때의 화면 지역과 지금 화면 지역이 다르다. 사용자가 화면에서 지역을 바꾼 것으로 본다.
            r = resolve(screen, _content(nxt), index, answering_region_question=True)
            if r.kind != "ask" and r.mentioned:
                confirmed = r.selection
    return confirmed


def _content(turn: dict) -> str:
    return str(turn.get("content") or turn.get("text") or "")


def resolve(screen: R.RegionSelection, text: str, index: RegionIndex, *, answering_region_question: bool = False) -> Resolution:
    """화면 선택과 글 속 지역 이름으로 검색 지역을 정한다."""
    if answering_region_question and _REFUSE.search(text):
        # "횡성 말고요", "모르겠어요"는 지역을 고른 것이 아니다. 어떤 화면 상태에서도 선택으로 보지 않는다
        # (의도 확인 건너뛰기·원래 질문 재개·확정 지역 복원 모두 하지 않는다).
        return Resolution("keep", screen, refused=True)
    mentions = find_mentions(text, index)
    unknown = unknown_places(text, index, mentions)
    if unknown and not answering_region_question and not any(m.options for m in mentions):
        # 목록에 없는 곳을 말했고 시군구는 알아보지 못했다 ("분당구에 사는데", "강원도 주문진읍에 사는데").
        # 화면 지역이나 시도만으로 대신 검색하면 엉뚱한 곳을 안내할 수 있어 묻는다.
        choices = [f"{_label((screen.sido, screen.sigungu))} 기준"] if screen.sido else []
        r = _ask(screen, f"말씀하신 '{unknown[0]}'을(를) 지금 자료의 지역 목록에서 찾지 못했어요. "
                         f"시·군·구 이름(예: ○○시, ○○군)으로 알려 주시겠어요? {CLARIFY_MARK}", choices, [])
        r.unknown_places = unknown
        return r
    if not mentions:
        return Resolution("keep", screen)

    # "강원 고성군", "서울 강북구"처럼 시도 바로 뒤의 시군구는 그 시도의 것으로 묶는다.
    regions: list[tuple[str, str | None]] = []
    ambiguous: list[tuple[str, list[tuple[str, str]]]] = []
    used_sido = set()
    for i, m in enumerate(mentions):
        if not m.options:
            continue
        before = mentions[i - 1] if i else None
        bound = before.sido if before and before.sido and m.start - before.end <= 2 else None
        name = sorted(m.options)[0][1]
        if bound and any(s == bound for s, _ in m.options):
            regions.append((bound, next(g for s, g in m.options if s == bound)))
            used_sido.add(i - 1)
            continue
        said_sidos = {x.sido for x in mentions if x.sido}
        for prefer in (said_sidos, {screen.sido} if screen.sido else set()):
            hit = [(s, g) for s, g in m.options if s in prefer]
            if len(hit) == 1:
                regions.append(hit[0])
                break
        else:
            if len(m.options) == 1:
                regions.append(next(iter(m.options)))
            else:
                ambiguous.append((name, sorted(m.options)))
    for i, m in enumerate(mentions):
        if m.sido and i not in used_sido and not any(s == m.sido for s, _ in regions):
            regions.append((m.sido, None))
    regions = list(dict.fromkeys(regions))
    mentioned = regions + [(s, g) for _, opts in ambiguous for s, g in opts]

    if ambiguous:
        name, opts = ambiguous[0]
        return _ask(screen, f"말씀하신 '{name}'이(가) 여러 곳에 있어요. {CLARIFY_MARK}", [_label(o) for o in opts], mentioned)
    if len(regions) > 1:
        return _ask(screen, f"말씀에 여러 지역이 나와요. {CLARIFY_MARK}", [_label(r) for r in regions], mentioned)

    sido, sigungu = regions[0]
    same_sido = screen.sido == sido
    if screen.kind in ("none", "nationwide") or answering_region_question:
        chosen = R.select_region(sido, sigungu)
        return Resolution("keep" if chosen == screen else "use", chosen, mentioned=mentioned)
    if screen.kind == "sido_only" and same_sido:
        return Resolution("use", R.select_region(sido, sigungu), mentioned=mentioned) if sigungu else Resolution("keep", screen)
    if screen.kind == "region" and same_sido and sigungu in (None, screen.sigungu):
        return Resolution("keep", screen, mentioned=mentioned)
    # 화면에서 고른 지역과 다르다. "여기"가 있고 바꾸는 말이 없으면 비교로 보고, 아니면 묻는다.
    if _HERE.search(text) and not _CHANGE.search(text):
        return Resolution("keep", screen, mentioned=mentioned, compared=[(sido, sigungu)])
    screen_label = _label((screen.sido, screen.sigungu))
    return _ask(screen, f"화면에서 고르신 지역은 {screen_label}인데, 말씀에는 {_label((sido, sigungu))}이(가) 나와요. {CLARIFY_MARK}",
                [f"{screen_label} 기준", f"{_label((sido, sigungu))} 기준"], mentioned)
