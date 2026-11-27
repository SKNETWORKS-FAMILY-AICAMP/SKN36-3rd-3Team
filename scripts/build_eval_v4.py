"""4차 평가 질문 세트를 만들고 점검한다 (읽기 전용 대조. DB와 검색기를 쓰지 않는다).

  migrate : 3차 평가 질문(122문항)을 새 파일로 옮긴다. 원본 파일은 읽기만 한다.
            지역 이름을 v3 기준으로 바꾸고, 정답 ID·지역·인용문이 v3 데이터에 실제로 있는지 대조한다.
  check   : 새로 쓴 문항 파일의 모양·상태·정답 표시가 서로, 그리고 v3 데이터와 맞는지 대조한다.
  check-safety : 안전 평가 문항 파일의 모양과 연락처 근거를 대조한다 (위험 단계가 옳은지는 사람이 본다).
  freeze  : 점검을 통과한 세트의 파일 지문·문항 수·확인 현황을 고정 기록으로 남긴다 (이전 기록은 덮어쓰지 않는다).
  stamp   : 사람이 확인한 문항에 확인 표시와 그때의 내용 지문을 적는다 (그 문항의 label 칸만 고친다).

사용 예
  python scripts/build_eval_v4.py migrate --source notebooks/qdrant/data/test_questions_v3.jsonl \
      --data-dir <청크 폴더> --out data/eval/v4/regression_r3_122.jsonl
  python scripts/build_eval_v4.py check --data-dir <청크 폴더> data/eval/v4/life_questions_draft.jsonl
  python scripts/build_eval_v4.py stamp data/eval/v4/life_questions_draft.jsonl --data-dir <청크 폴더> \
      --reviewer <확인한 사람> --date 2026-11-27 --qid L010 L020   (파일 이름을 맨 앞에 적는다)
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

SIDO_ALIAS = {"전라남도": "전남광주통합특별시", "광주광역시": "전남광주통합특별시"}
ENUMS = {
    "split": {"tune", "holdout"}, "style": {"bare", "context"}, "eval_type": {"behavior", "retrieval"},
    "confidence": {"high", "medium"},
}
REGION_KINDS = {"region", "sido_only", "none"}
LABEL_STATUS = {"draft", "user_checked"}
ASKING = {"ask_clarify", "cautious_candidates_with_question"}   # 되묻는 행동
# answer_without_asking: 되묻지 않고 바로 답하기 / accept_refusal: 말하기 싫다는 뜻을 받아들이고 일반 안내하기
BEHAVIORS = ASKING | {"answer_without_asking", "accept_refusal"}
VARIANT_KINDS = {"paraphrase", "caregiver", "limit"}   # 기준 문항에서 파생한 문항의 종류
ID_SETS = ("local_policy_ids", "distractor_ids", "must_not_ids", "region_unverified_policy_ids", "national_section_ids")
GOLD_SETS = ("local_policy_ids", "region_unverified_policy_ids", "national_section_ids")   # 근거 인용이 필요한 정답
RETRIEVAL_ONLY = ID_SETS + ("local_case", "no_local_message")   # 행동 평가 문항에는 없어야 하는 칸
SPLIT_GOLD = ("local_policy_ids", "region_unverified_policy_ids", "acceptable_if_offered_policy_ids")   # 조정용·검증용이 겹치면 안 되는 정책
REVIEWED_FIELDS = ("question", "given_context", "region", "style", "eval_type", "expected", "evidence")
HASH_KEY = "reviewed_content_sha256"
BEHAVIOR_ONLY = ("allowed_behaviors", "should_ask", "forbidden", "acceptable_if_offered_policy_ids", "offer_rule")
GUIDANCE_KEYS = {"say", "should_ask", "confirm_with_agency", "do_not_state", "basis"}
MIN_QUOTE = 4


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def squash(text: str) -> str:
    return "".join(text.split())


class Corpus:
    """v3 청크 파일에서 정답 대조에 필요한 것만 읽는다."""

    def __init__(self, data_dir: Path) -> None:
        self.version = json.loads((data_dir / "release_manifest.json").read_text(encoding="utf-8"))["data_version"]
        self.policy_text: dict[str, str] = collections.defaultdict(str)
        self.policy_keys: dict[str, set[str]] = {}
        self.policy_sido: dict[str, str] = {}
        self.chunks: dict[str, tuple[str, str]] = {}   # chunk_id -> (정책 또는 절 ID, 본문)
        for r in read_jsonl(data_dir / "policy_chunks.jsonl"):
            pid, m = r["policy_id"], r["metadata"]
            self.chunks[r["chunk_id"]] = (pid, r["text"])
            self.policy_text[pid] += r["text"] + "\n"
            self.policy_keys[pid] = {f"{e['sido']}|{e['sigungu']}" for e in m["applies_to"]}
            self.policy_sido[pid] = m["sido_name"]
        self.section_text: dict[str, str] = collections.defaultdict(str)
        for r in read_jsonl(data_dir / "guideline_chunks.jsonl"):
            self.chunks[r["chunk_id"]] = (r["section_id"], r["text"])
            self.section_text[r["section_id"]] += r["text"] + "\n"

    def applies(self, pid: str, sido: str, sigungu: str | None) -> bool:
        """검색 규칙과 같은 기준: 시군구를 골랐으면 지역 키, 시도만 골랐으면 등록 시도(지역 미상 제외)."""
        keys = self.policy_keys[pid]
        if sigungu:
            return f"{sido}|{sigungu}" in keys
        return bool(keys) and self.policy_sido[pid] == sido

    def quoted(self, item_id: str, quote: str) -> bool:
        text = self.policy_text.get(item_id) or self.section_text.get(item_id) or ""
        return squash(quote) in squash(text)


# ───────────────────────── 3차 문항 이관 ─────────────────────────

def migrate(args) -> int:
    corpus = Corpus(args.data_dir)
    out_rows, problems = [], []
    for q in read_jsonl(args.source):
        sido = SIDO_ALIAS.get(q["user_sido"], q["user_sido"])
        sigungu = q["user_sigungu"]
        checks = {"ids_exist": True, "region_match": None, "evidence_found": None}
        expected_kind = "none"
        if not q["expected_ids"]:
            pass   # 함정 문항: 찾아야 할 정답이 없다 (금지 ID만 있을 수 있음)
        elif q["target"] == "guideline":
            expected_kind = "national_sections"
            checks["ids_exist"] = all(i in corpus.section_text for i in q["expected_ids"])
        elif q["target"] == "policy":
            checks["ids_exist"] = all(i in corpus.policy_text for i in q["expected_ids"])
            if checks["ids_exist"]:
                if all(corpus.applies(i, sido, sigungu) for i in q["expected_ids"]):
                    expected_kind, checks["region_match"] = "local_policies", True
                elif all(not corpus.policy_keys[i] and corpus.policy_sido[i] == sido for i in q["expected_ids"]):
                    # v3 에서는 적용 지역이 확정되지 않은 시도 등록 자료다. 답변 근거가 아니라 별도 목록 대상.
                    expected_kind, checks["region_match"] = "region_unverified", True
                else:
                    expected_kind, checks["region_match"] = "local_policies", False
        if q.get("evidence") and q["expected_ids"]:
            checks["evidence_found"] = any(corpus.quoted(i, q["evidence"]) for i in q["expected_ids"])
        bad_must_not = [i for i in q.get("must_not_ids") or []
                        if i in corpus.policy_text and sido and corpus.applies(i, sido, sigungu)]
        if not checks["ids_exist"] or checks["region_match"] is False or checks["evidence_found"] is False or bad_must_not:
            problems.append((q["qid"], checks, bad_must_not))
        kind = "none" if not sido else ("region" if sigungu else "sido_only")
        out_rows.append({
            "qid": f"R3-{q['qid']}", "source_qid": q["qid"], "source_file": args.source.as_posix(),
            "group_id": f"r3-{q['pair_id']}" if q.get("pair_id") else f"r3-{q['qid']}",
            "split": "regression",   # 3차 때 이미 검색 조정에 쓴 문항이라 새 검증용으로 쓰지 않는다.
            "q_type": q["q_type"], "question": q["question"],
            "region": {"kind": kind, "sido": sido, "sigungu": sigungu},
            "region_original": {"sido": q["user_sido"], "sigungu": q["user_sigungu"]},
            "expected": {"kind": expected_kind, "ids": q["expected_ids"], "must_not_ids": q.get("must_not_ids") or [],
                         "title": q.get("expected_title") or ""},
            "evidence": q.get("evidence"), "note": q.get("note") or "", "origin": q.get("source"),
            "checks": checks,
            "label": {"source": "round3", "status": "draft", "data_version": corpus.version,
                      "method": "3차 정답을 v3 데이터와 자동 대조 (ID 존재·지역·인용문). 사람 재확인 전",
                      "reviewer": None, "reviewed_at": None},
        })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    kinds = collections.Counter(r["expected"]["kind"] for r in out_rows)
    ev = collections.Counter(str(r["checks"]["evidence_found"]) for r in out_rows)
    print(f"이관 {len(out_rows)}문항 -> {args.out}")
    print(f"  정답 종류: {dict(kinds)}")
    print(f"  인용문 대조: 찾음 {ev['True']}, 못 찾음 {ev['False']}, 인용문 없음 {ev['None']}")
    for qid, checks, bad in problems:
        print(f"  [확인 필요] {qid}: {checks}" + (f" 금지 ID가 같은 지역에 있음 {bad}" if bad else ""))
    print(f"  확인 필요 {len(problems)}문항 (모든 문항은 사람 확인 전 draft 상태)")
    return 1 if problems else 0   # 파일은 만들지만, 대조에서 어긋난 문항이 있으면 실패로 알린다.


# ───────────────────────── 새 문항 점검 ─────────────────────────

def content_hash(r: dict) -> str:
    """사람이 확인한 내용(질문·전달 정보·지역·정답·근거·답변 지침)의 지문. 검토자·날짜 같은 기록 칸은 빼고 계산한다."""
    body = {k: r.get(k) for k in REVIEWED_FIELDS}
    if "history" in r:   # 이전 대화가 있는 문항만 지문에 넣는다 (없는 문항의 지문은 그대로).
        body["history"] = r["history"]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def text_list(value) -> bool:
    """빈 값이 없는 글자 목록인가 (빈 목록은 허용)."""
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def check_guidance(g, corpus: Corpus, own_ids: set[str]) -> list[str]:
    """문항별 답변 지침(있을 때만). 형식과, 조건의 근거 문장이 이 문항의 정책 원문에 있는지만 본다.
    지침이 옳은지는 사람이 본다. own_ids 는 이 문항이 정답·제시 허용으로 적은 정책·절 ID."""
    if g is None:
        return []
    if not isinstance(g, dict):
        return ["answer_guidance 모양이 잘못됨 (칸 이름과 값의 묶음이어야 함)"]
    out: list[str] = []
    unknown = sorted(set(g) - GUIDANCE_KEYS)
    if unknown:
        out.append(f"answer_guidance 에 모르는 칸이 있음 (오타 확인): {unknown}")
    if not isinstance(g.get("say"), str) or not g["say"].strip():
        out.append("answer_guidance 에 안내 방식(say)이 없음")
    for key in ("should_ask", "do_not_state", "confirm_with_agency"):
        if key == "confirm_with_agency" and key not in g:
            continue   # 기관 확인 항목은 없어도 된다.
        if not text_list(g.get(key)):
            out.append(f"answer_guidance.{key} 는 빈 값이 없는 글자 목록이어야 함")
    if g.get("do_not_state") == []:
        out.append("answer_guidance.do_not_state 가 비어 있음")
    if isinstance(g.get("should_ask"), list) and len(g["should_ask"]) > 2:
        out.append("answer_guidance.should_ask 는 2개 이하여야 함 (질문을 연달아 던지지 않기)")
    basis = g.get("basis")
    if not isinstance(basis, list) or not basis:
        out.append("answer_guidance.basis(조건의 원문 근거)가 목록이 아니거나 비어 있음")
        return out
    for b in basis:
        if not isinstance(b, dict) or not isinstance(b.get("id"), str) or not isinstance(b.get("quote"), str):
            out.append(f"answer_guidance.basis 항목은 id 와 quote 를 가져야 함: {b!r}")
        elif b["id"] not in own_ids:
            out.append(f"answer_guidance 의 근거가 이 문항의 정책이 아님: {b['id']}")
        elif len(squash(b["quote"])) < MIN_QUOTE or not corpus.quoted(b["id"], b["quote"]):
            out.append(f"answer_guidance 의 근거 문장이 원문에 없음: {b['id']} / {b['quote']}")
    return out


def check_row(r: dict, corpus: Corpus) -> list[str]:
    """한 문항의 모양·상태·정답 집합이 서로, 그리고 v3 데이터와 맞는지 본다."""
    out: list[str] = []
    # 큰 칸의 모양이 틀리면 아래 대조를 할 수 없다. 여기서 멈추고 알린다 (도구가 죽지 않게).
    for key, kind_of in (("region", dict), ("label", dict), ("expected", dict), ("evidence", list)):
        if not isinstance(r.get(key), kind_of):
            out.append(f"{key} 칸이 없거나 모양이 잘못됨")
    if out:
        return out
    if not all(isinstance(e, dict) and all(isinstance(e.get(k), str) for k in ("id", "chunk_id", "quote"))
               for e in r["evidence"]):
        return ["evidence 항목은 id·chunk_id·quote 를 글자로 가져야 함"]
    for key, allowed in ENUMS.items():
        if not isinstance(r.get(key), str) or r[key] not in allowed:
            out.append(f"{key} 값이 잘못됨: {r.get(key)!r}")
    if not all(isinstance(r.get(k), str) and r[k].strip() for k in ("question", "given_context")):
        out.append("question 또는 given_context 가 비어 있거나 글자가 아님")
    # 한마디 질문은 행동 평가만 한다. 상황이 담긴 질문은 검색 평가일 수도, 행동 평가(되묻기가 정답)일 수도 있다.
    if r.get("style") == "bare" and r.get("eval_type") != "behavior":
        out.append("한마디(bare) 질문은 행동 평가(behavior)여야 함")

    if "history" in r:   # 이전 대화: 시험용으로 정해 둔 것. 마지막은 시스템의 말이어야 이번 질문이 이어진다.
        h = r["history"]
        if not isinstance(h, list) or not h or not all(
                isinstance(t, dict) and t.get("role") in ("user", "assistant")
                and isinstance(t.get("text"), str) and t["text"].strip() for t in h) or h[-1]["role"] != "assistant":
            out.append("history 모양이 잘못됨 (role·text 목록이고 마지막은 assistant 여야 함)")
    if "base_qid" in r:
        if not isinstance(r["base_qid"], str) or not isinstance(r.get("variant_kind"), str) \
                or r["variant_kind"] not in VARIANT_KINDS:
            out.append(f"파생 문항의 base_qid 또는 variant_kind 가 잘못됨: {r.get('variant_kind')!r}")
        elif (r["variant_kind"] == "limit") != (isinstance(r.get("limit_type"), str) and bool(r["limit_type"].strip())):
            out.append("limit_type 은 한계 질문(limit)에만, 그리고 반드시 있어야 함")
    elif "variant_kind" in r or "limit_type" in r:
        out.append("base_qid 없이 variant_kind·limit_type 이 적혀 있음")

    region = r["region"]
    kind, sido, sigungu = region.get("kind"), region.get("sido"), region.get("sigungu")
    if not all(v is None or isinstance(v, str) for v in (kind, sido, sigungu)) or kind not in REGION_KINDS \
            or (kind == "region") != bool(sido and sigungu) \
            or (kind == "sido_only") != bool(sido and not sigungu) or (kind == "none") != (not sido and not sigungu):
        out.append(f"region 모양이 맞지 않음: {region!r}")
        return out   # 지역이 틀리면 아래 대조는 의미가 없다.

    label = r["label"]
    status, stamped = label.get("status"), label.get(HASH_KEY)
    if not isinstance(status, str) or status not in LABEL_STATUS:
        out.append(f"label.status 값이 잘못됨: {status!r}")
    if label.get("data_version") != corpus.version:
        out.append("data_version 이 현재 데이터와 다름")
    if status == "user_checked" and not (label.get("reviewer") and label.get("reviewed_at")):
        out.append("user_checked 인데 검토자·검토일이 없음")
    if status == "draft" and (label.get("reviewer") or label.get("reviewed_at") or stamped):
        out.append("draft 인데 검토자·검토일·확인 기록이 적혀 있음")
    if status == "user_checked" and stamped and stamped != content_hash(r):
        out.append("사람이 확인한 뒤에 문항 내용이 바뀜 (다시 확인받아야 함)")

    exp, evidence = r["expected"], r["evidence"]
    behavior = r.get("eval_type") == "behavior"
    # 목록이어야 하는 칸이 글자 하나로 적혀 있으면 글자 단위로 쪼개져 엉뚱하게 통과하므로 먼저 막는다.
    list_keys = ("allowed_behaviors", "should_ask", "forbidden", "acceptable_if_offered_policy_ids") if behavior else ID_SETS
    bad_lists = [k for k in list_keys if k in exp and not text_list(exp[k])]
    if bad_lists:
        out.append(f"목록이어야 하는 칸의 모양이 잘못됨 (빈 값 없는 글자 목록): {bad_lists}")
        return out
    own_ids = set(exp.get("acceptable_if_offered_policy_ids") or []) if behavior \
        else {i for k in GOLD_SETS for i in exp.get(k) or []}
    out += check_guidance(exp.get("answer_guidance"), corpus, own_ids)
    cited: set[str] = set()
    for e in evidence:
        quote = str(e.get("quote") or "")
        owner = corpus.chunks.get(e.get("chunk_id") or "")
        if len(squash(quote)) < MIN_QUOTE:
            out.append(f"인용문이 비었거나 너무 짧음: {e.get('id')}")
        elif owner is None or owner[0] != e.get("id"):
            out.append(f"근거 청크가 없거나 그 정책·절의 청크가 아님: {e.get('id')} / {e.get('chunk_id')}")
        elif squash(quote) not in squash(owner[1]):
            out.append(f"인용문이 그 청크 원문에 없음: {e.get('chunk_id')} / {quote}")
        else:
            cited.add(e["id"])

    if behavior:
        if not exp.get("allowed_behaviors") or not set(exp["allowed_behaviors"]) <= BEHAVIORS:
            out.append("allowed_behaviors 가 비었거나 모르는 값이 있음")
        asking_only = set(exp.get("allowed_behaviors") or []) <= ASKING
        if not exp.get("forbidden") or (asking_only and not exp.get("should_ask")):
            out.append("should_ask 또는 forbidden 이 비어 있음")
        if not asking_only and not exp.get("answer_guidance"):
            out.append("되묻기가 아닌 행동(바로 답하기·거절 받아들이기)에는 answer_guidance 가 있어야 함")
        offer = exp.get("acceptable_if_offered_policy_ids") or []
        if offer and kind == "none":
            out.append("지역을 고르지 않았는데 제시 허용 정책이 있음")
        for pid in offer:
            if kind != "none" and (pid not in corpus.policy_text or not corpus.applies(pid, sido, sigungu)):
                out.append(f"제시 허용 정책이 이 지역 것이 아님: {pid}")
        left = [k for k in RETRIEVAL_ONLY if exp.get(k)]
        if left:   # 검색 평가에서 행동 평가로 바꿀 때 옛 칸이 남으면 채점이 섞인다.
            out.append(f"행동 평가 문항에 검색 평가용 칸이 채워져 있음: {left}")
        for item in sorted({str(e.get("id")) for e in evidence} - set(offer)):
            out.append(f"제시 허용 정책이 아닌 ID의 근거가 적혀 있음: {item}")
        return out

    left = [k for k in BEHAVIOR_ONLY if exp.get(k)]
    if left:
        out.append(f"검색 평가 문항에 행동 평가용 칸이 채워져 있음: {left}")
    if kind == "none":
        out.append("검색 평가 문항인데 지역이 없음")
        return out
    sets = {k: list(exp.get(k) or []) for k in ID_SETS}
    for k, ids in sets.items():
        if len(set(ids)) != len(ids):
            out.append(f"{k} 안에 같은 ID가 두 번 있음")
    for i, a in enumerate(ID_SETS):
        for b in ID_SETS[i + 1:]:
            both = set(sets[a]) & set(sets[b])
            if both:
                out.append(f"{a} 와 {b} 에 같은 ID가 있음: {sorted(both)}")
    local = sets["local_policy_ids"]
    if exp.get("local_case") not in ("has_policy", "no_policy") or bool(local) != (exp.get("local_case") == "has_policy"):
        out.append("local_case 와 local_policy_ids 가 맞지 않음")
    if bool(exp.get("no_local_message")) != (exp.get("local_case") == "no_policy"):
        out.append("no_local_message 는 정책 없는 문항에만 있어야 함")
    for pid in local:
        if pid not in corpus.policy_text:
            out.append(f"정답 정책이 데이터에 없음: {pid}")
        elif not corpus.applies(pid, sido, sigungu):
            out.append(f"정답 정책이 이 지역에 적용되지 않음: {pid}")
    for pid in sets["distractor_ids"]:
        if pid not in corpus.policy_text or not corpus.applies(pid, sido, sigungu):
            out.append(f"방해 정책이 이 지역 것이 아님: {pid}")
    for pid in sets["must_not_ids"]:
        if pid not in corpus.policy_text:
            out.append(f"금지 정책이 데이터에 없음: {pid}")
        elif corpus.applies(pid, sido, sigungu):
            out.append(f"금지 정책이 실제로는 이 지역에 적용됨: {pid}")
    for pid in sets["region_unverified_policy_ids"]:
        if pid not in corpus.policy_text or corpus.policy_keys[pid] or corpus.policy_sido[pid] != sido:
            out.append(f"지역 미상 목록 대상이 아님 (시도 등록·적용 지역 없음이어야 함): {pid}")
    for sid in sets["national_section_ids"]:
        if sid not in corpus.section_text:
            out.append(f"전국 절이 데이터에 없음: {sid}")
    need_evidence = own_ids
    for item in sorted(need_evidence - cited):
        out.append(f"정답으로 적은 ID의 근거 인용문이 없음: {item}")
    for item in sorted({str(e.get("id")) for e in evidence} - need_evidence):
        out.append(f"정답 목록에 없는 ID의 근거가 적혀 있음: {item}")
    return out


def check_variant(r: dict, base: dict | None) -> list[str]:
    """파생 문항이 기준 문항과 맞는지 본다. 기준 문항은 사람이 확인한 것이어야 한다."""
    if base is None:
        return [f"기준 문항이 없거나 오류가 있음: {r['base_qid']} (기준 문항 파일도 함께 넘겨야 함)"]
    out: list[str] = []
    if "base_qid" in base:
        out.append("파생 문항을 기준 문항으로 삼을 수 없음")
    if base["label"]["status"] != "user_checked" or not base["label"].get(HASH_KEY):
        out.append(f"기준 문항이 사람 확인 전임: {base['qid']}")
    if (r["group_id"], r["split"]) != (base["group_id"], base["split"]):
        out.append("기준 문항과 묶음·분할이 다름")
    if r["variant_kind"] != "limit":   # 말만 바꾼 질문은 지역·평가 종류·전달 정보·이전 대화·정답표·근거가 기준 문항과 같아야 한다.
        diff = [k for k in ("region", "eval_type", "given_context", "history", "expected", "evidence") if r.get(k) != base.get(k)]
        if diff:
            out.append(f"말만 바꾼 문항인데 기준 문항과 다른 칸이 있음: {diff}")
        if squash(r["question"]) == squash(base["question"]):
            out.append("기준 문항과 질문이 같음")
    return out


def check(args) -> int:
    """넘겨받은 파일 전체를 한 세트로 본다 (qid 중복·묶음 분할·조정용/검증용 겹침은 파일을 넘어서 확인)."""
    corpus = Corpus(args.data_dir)
    errors: list[str] = []
    recheck: list[str] = []
    seen: set[str] = set()
    group_split: dict[str, str] = {}
    gold_by_split: dict[str, set[str]] = collections.defaultdict(set)
    ok_rows: dict[str, tuple[str, dict]] = {}   # 문항 검사를 통과한 문항 (파생 문항 대조용)
    for path in args.files:
        try:
            rows = read_jsonl(path)
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: 파일을 읽을 수 없음 ({type(exc).__name__}: {exc})")
            continue
        stat = collections.Counter()
        for n, r in enumerate(rows, 1):
            if not isinstance(r, dict) or not all(isinstance(r.get(k), str) and r[k].strip() for k in ("qid", "group_id")):
                errors.append(f"{path.name} {n}번째 문항: 문항 모양이 잘못됐거나 qid·group_id 가 글자가 아님")
                stat[("(오류 문항)", "", "")] += 1
                continue
            qid = r["qid"]
            if qid in seen:
                errors.append(f"{path.name} {qid}: qid 중복")
            seen.add(qid)
            row_errors = check_row(r, corpus)
            if row_errors:   # 모양이 틀린 문항은 아래 집계에 넣지 않는다 (집계하다 멈추지 않게).
                errors += [f"{path.name} {qid}: {m}" for m in row_errors]
                stat[("(오류 문항)", "", "")] += 1
                continue
            exp, label = r["expected"], r["label"]
            ok_rows.setdefault(qid, (path.name, r))
            if group_split.setdefault(r["group_id"], r["split"]) != r["split"]:
                errors.append(f"{path.name} {qid}: 같은 묶음({r['group_id']})이 서로 다른 분할에 있음")
            gold_by_split[r["split"]] |= {i for k in SPLIT_GOLD for i in exp.get(k) or []}
            if label["status"] == "user_checked" and not label.get(HASH_KEY):
                recheck.append(f"{path.name} {qid}")
            stat[(r["split"], r["eval_type"], str(exp.get("local_case", "-")))] += 1
        print(f"{path}: {len(rows)}문항")
        for (split, etype, case), n in sorted(stat.items()):
            print(f"  {split:<11} {etype:<9} {case:<10} {n}")
    for qid, (name, r) in ok_rows.items():
        if "base_qid" in r:
            errors += [f"{name} {qid}: {m}" for m in check_variant(r, ok_rows.get(r["base_qid"], (None, None))[1])]
    shared = gold_by_split["tune"] & gold_by_split["holdout"]
    if shared:   # 검증용은 질문뿐 아니라 정답·제시 허용·별도 목록 정책도 조정용과 겹치지 않게 한다.
        errors.append(f"조정용과 검증용에 같은 정책이 있음: {sorted(shared)}")
    for e in errors:
        print("[오류]", e)
    for w in recheck:
        print("[재확인 필요]", w, "- 사람 확인 표시는 있지만 확인 당시 내용 기록이 없음")
    print(f"오류 {len(errors)}건, 재확인 필요 {len(recheck)}건")
    return 1 if errors else 0


SAFETY_CATEGORIES = {"self_harm_direct", "self_harm_indirect", "figurative", "harm_others", "abuse", "emergency_symptom",
                     "scam", "medication", "fraud_request", "distress"}
SAFETY_LEVELS = {"urgent", "check_in", "normal"}   # 긴급 안내 먼저 / 마음·상황 확인 먼저 / 일반 처리


def check_safety_row(r: dict, corpus: Corpus) -> list[str]:
    """안전 평가 문항 한 개의 모양과, 연락처 근거가 원문에 있는지 본다. 위험 단계가 옳은지는 사람이 본다."""
    exp, label = r.get("expected"), r.get("label")
    if not isinstance(exp, dict) or not isinstance(label, dict):
        return ["expected 또는 label 칸이 없거나 모양이 잘못됨"]
    out: list[str] = []
    if not isinstance(r.get("category"), str) or r["category"] not in SAFETY_CATEGORIES:
        out.append(f"category 값이 잘못됨: {r.get('category')!r}")
    if not all(isinstance(r.get(k), str) and r[k].strip() for k in ("question", "given_context")):
        out.append("question 또는 given_context 가 비어 있거나 글자가 아님")
    level, judgement, search = exp.get("risk_level"), exp.get("judgement"), exp.get("search")
    if not isinstance(level, str) or level not in SAFETY_LEVELS:
        out.append(f"risk_level 값이 잘못됨: {level!r}")
    if judgement not in ("clear", "hold"):
        out.append(f"judgement 는 clear 또는 hold(보류)여야 함: {judgement!r}")
    if search not in ("skip", "allowed") or (level == "urgent") != (search == "skip"):
        out.append("search 는 긴급(urgent)일 때만 skip, 나머지는 allowed 여야 함")
    for key in ("must_do", "must_not"):
        if not text_list(exp.get(key)) or not exp[key]:
            out.append(f"{key} 는 비어 있지 않은 글자 목록이어야 함")
    contacts = exp.get("contacts")
    if not isinstance(contacts, list):
        out.append("contacts 는 목록이어야 함")
        contacts = []
    if level == "urgent" and not any(isinstance(c, dict) and c.get("required") is True for c in contacts):
        out.append("긴급 문항에는 반드시 안내할 연락처(required)가 하나 이상 있어야 함")
    basis = exp.get("basis", [])
    if not isinstance(basis, list):
        out.append("basis 는 목록이어야 함")
        basis = []
    for b in basis:   # 지침에 적은 사실(예: 신고자 비밀 보장)의 자료 근거
        owner = corpus.chunks.get(b.get("chunk_id") if isinstance(b, dict) and isinstance(b.get("chunk_id"), str) else "")
        quote = b.get("quote") if isinstance(b, dict) and isinstance(b.get("quote"), str) else ""
        if owner is None or len(squash(quote)) < MIN_QUOTE or squash(quote) not in squash(owner[1]):
            out.append(f"지침의 근거 문장이 원문에 없음: {b!r}")
    for c in contacts:
        # required: 반드시 안내할 번호(true) / 상황에 따라 안내할 번호(false). 채점자가 모든 번호를 요구하지 않게 구분한다.
        if not isinstance(c, dict) or not all(isinstance(c.get(k), str) and c[k].strip() for k in ("number", "name")) \
                or c.get("source") not in ("data", "general") or not isinstance(c.get("required"), bool):
            out.append(f"연락처 모양이 잘못됨: {c!r}")
        elif c["source"] == "data":   # 우리 자료에 있다고 적은 번호는 그 청크 원문에 실제로 있어야 한다.
            owner = corpus.chunks.get(c.get("chunk_id") if isinstance(c.get("chunk_id"), str) else "")
            quote = c.get("quote") if isinstance(c.get("quote"), str) else ""
            if owner is None or c["number"] not in quote or squash(quote) not in squash(owner[1]):
                out.append(f"연락처 근거가 원문에 없음: {c['number']} / {c.get('chunk_id')}")
    status = label.get("status")
    if not isinstance(status, str) or status not in LABEL_STATUS:
        out.append(f"label.status 값이 잘못됨: {status!r}")
    if label.get("data_version") != corpus.version:
        out.append("data_version 이 현재 데이터와 다름")
    if status == "draft" and (label.get("reviewer") or label.get("reviewed_at")):
        out.append("draft 인데 검토자·검토일이 적혀 있음")
    if status == "user_checked" and (judgement == "hold" or not (label.get("reviewer") and label.get("reviewed_at"))):
        out.append("user_checked 는 검토자·검토일이 있고 보류(hold)가 풀린 문항만 가능")
    if status == "draft" and label.get(HASH_KEY):
        out.append("draft 인데 확인 기록이 적혀 있음")
    if status == "user_checked" and label.get(HASH_KEY) != safety_hash(r):
        out.append("확인 당시 내용 기록이 없거나, 사람이 확인한 뒤에 문항 내용이 바뀜 (다시 확인받아야 함)")
    return out


def safety_hash(r: dict) -> str:
    """안전 문항에서 사람이 확인한 내용(분류·질문·전달 정보·이전 대화·정답 지침)의 지문."""
    body = {k: r.get(k) for k in ("category", "question", "given_context", "history", "expected")}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def check_safety(args) -> int:
    corpus = Corpus(args.data_dir)
    errors: list[str] = []
    seen: set[str] = set()
    stat = collections.Counter()
    try:
        rows = read_jsonl(args.file)
    except (OSError, ValueError) as exc:
        print(f"[오류] 파일을 읽을 수 없음 ({type(exc).__name__}: {exc})")
        return 1
    for n, r in enumerate(rows, 1):
        if not isinstance(r, dict) or not isinstance(r.get("qid"), str) or not r["qid"].strip():
            errors.append(f"{n}번째 문항: 문항 모양이 잘못됐거나 qid 가 글자가 아님")
            continue
        if r["qid"] in seen:
            errors.append(f"{r['qid']}: qid 중복")
        seen.add(r["qid"])
        row_errors = check_safety_row(r, corpus)
        errors += [f"{r['qid']}: {m}" for m in row_errors]
        if not row_errors:
            stat[(r["category"], r["expected"]["risk_level"], r["expected"]["judgement"])] += 1
    print(f"{args.file}: {len(rows)}문항")
    for (cat, level, judgement), n in sorted(stat.items()):
        print(f"  {cat:<19} {level:<9} {judgement:<6} {n}")
    for e in errors:
        print("[오류]", e)
    print(f"오류 {len(errors)}건, 사람 판단 보류 {sum(n for (_, _, j), n in stat.items() if j == 'hold')}건")
    return 1 if errors else 0


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(args) -> int:
    """평가 세트의 현재 내용을 고정 기록(매니페스트)으로 남긴다. 점검에 오류가 있으면 남기지 않고, 이전 기록은 덮어쓰지 않는다.
    문항 내용이 바뀌면 --name 의 버전을 올리고, 확인 상태만 바뀌면 --revision 을 올린다."""
    out = args.out_dir / f"{args.name}_r{args.revision}.json"
    if out.exists():
        print(f"[중단] 이미 있는 기록입니다 (덮어쓰지 않음): {out}")
        return 1
    with contextlib.redirect_stdout(io.StringIO()):
        bad = check(argparse.Namespace(data_dir=args.data_dir, files=args.files)) \
            or check_safety(argparse.Namespace(data_dir=args.data_dir, file=args.safety))
    if bad:
        print("[중단] 점검에 오류가 있어 고정하지 않았습니다. check / check-safety 를 먼저 통과시키세요.")
        return 1
    corpus_version = json.loads((args.data_dir / "release_manifest.json").read_text(encoding="utf-8"))["data_version"]
    files = []
    for path in [*args.files, args.safety, *args.extra]:
        entry = {"file": path.name, "sha256": file_sha256(path)}
        if path.suffix == ".jsonl":
            rows = read_jsonl(path)
            entry["questions"] = len(rows)
            entry["label_status"] = dict(collections.Counter(r["label"]["status"] for r in rows))
            if all("split" in r for r in rows):
                entry["split"] = dict(collections.Counter(r["split"] for r in rows))
        files.append(entry)
    manifest = {"name": args.name, "revision": args.revision, "frozen_at": args.date, "data_version": corpus_version,
                "checker_sha256": file_sha256(Path(__file__)), "files": files,
                "note": "공식 평가에는 user_checked 이면서 확인 당시 내용 지문이 일치하는 문항만 넣는다. 안전 문항은 전문가 검토를 거친 것이 아니다."}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"고정 기록: {out}")
    for e in files:
        print(f"  {e['file']:<32} {e.get('questions', '-'):>4}문항 {e.get('label_status', '')} {e['sha256'][:12]}")
    return 0


def stamp(args) -> int:
    """사람이 실제로 확인한 문항에만 쓴다. 확인 표시와 함께 그때의 내용 지문을 적어, 나중에 내용이 바뀌면 드러나게 한다."""
    corpus = Corpus(args.data_dir)
    with open(args.file, encoding="utf-8", newline="") as f:
        lines = f.readlines()
    wanted, todo, problems = set(args.qid), set(args.qid), []
    for n, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            problems.append(f"{n + 1}번째 줄을 읽을 수 없음")
            continue
        if not isinstance(r, dict) or not isinstance(r.get("qid"), str) or r["qid"] not in wanted:
            continue
        if r["qid"] not in todo:   # 같은 qid 가 두 번 있으면 어느 쪽을 확인했는지 알 수 없다.
            problems.append(f"{r['qid']}: 파일에 같은 qid 가 두 번 있음")
            continue
        todo.discard(r["qid"])
        if not isinstance(r.get("label"), dict):
            problems.append(f"{r['qid']}: label 칸이 없음")
            continue
        hasher, checker = (safety_hash, check_safety_row) if getattr(args, "safety", False) else (content_hash, check_row)
        r["label"].update({"status": "user_checked", "reviewer": args.reviewer, "reviewed_at": args.date,
                           HASH_KEY: hasher(r)})
        problems += [f"{r['qid']}: {m}" for m in checker(r, corpus)]
        lines[n] = json.dumps(r, ensure_ascii=False) + "\n"   # 다른 문항의 줄은 그대로 둔다.
    problems += [f"{qid}: 파일에 없는 문항" for qid in sorted(todo)]
    if problems:
        for p in problems:
            print("[오류]", p)
        print("기록하지 않았습니다.")
        return 1
    with open(args.file, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
    print(f"확인 기록 {len(args.qid)}문항: {', '.join(args.qid)} (검토자 {args.reviewer}, {args.date})")
    return 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="4차 평가 질문 세트 만들기·점검")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate")
    m.add_argument("--source", type=Path, required=True)
    m.add_argument("--data-dir", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("--data-dir", type=Path, required=True)
    c.add_argument("files", type=Path, nargs="+")
    cs = sub.add_parser("check-safety")
    cs.add_argument("--data-dir", type=Path, required=True)
    cs.add_argument("file", type=Path)
    fz = sub.add_parser("freeze")
    fz.add_argument("--data-dir", type=Path, required=True)
    fz.add_argument("--name", required=True, help="세트 이름과 내용 버전 (예: v4-eval-0.1)")
    fz.add_argument("--revision", type=int, required=True, help="같은 내용 버전 안에서 확인 상태가 바뀔 때마다 올리는 번호")
    fz.add_argument("--date", required=True)
    fz.add_argument("--out-dir", type=Path, required=True)
    fz.add_argument("--safety", type=Path, required=True)
    fz.add_argument("--extra", type=Path, nargs="*", default=[], help="점검 없이 지문만 남길 파일 (3차 이관 문항, 페르소나 등)")
    fz.add_argument("--files", type=Path, nargs="+", required=True)
    s = sub.add_parser("stamp")
    s.add_argument("--data-dir", type=Path, required=True)
    s.add_argument("--reviewer", required=True)
    s.add_argument("--date", required=True, help="확인한 날짜 (예: 2026-11-27)")
    s.add_argument("--qid", nargs="+", required=True)
    s.add_argument("--safety", action="store_true", help="안전 평가 문항 파일일 때 (보류가 풀린 문항만 기록됨)")
    s.add_argument("file", type=Path)
    args = ap.parse_args()
    if args.cmd == "migrate" and args.out.resolve() == args.source.resolve():
        raise SystemExit("[중단] 원본 파일을 덮어쓸 수 없습니다.")
    commands = {"migrate": migrate, "check": check, "check-safety": check_safety, "stamp": stamp, "freeze": freeze}
    raise SystemExit(commands[args.cmd](args))


if __name__ == "__main__":
    main()
