"""4차(v3) 근거 판정 측정: 실제 LLM 이 문서 하나하나의 관련성을 제대로 가려내는지 본다 (B3 의 판정 단계만).

검색은 실제 묶음별 검색 코드(search_grouped, 전수 비교)로 Qdrant 에 읽기 전용 질의를 해서 후보를 고정하고,
판정은 실제 근거 판정 노드(make_evidence_node)와 실제 LLM 으로 한다. 의도 확인과 답변 생성은 부르지 않는다
(질문 문장을 그대로 검색어로 쓴다. 실제 채팅에서는 의도 확인 LLM 이 검색어를 바꿀 수 있다).

무엇을 채점하나 (사람이 확인한 정답표 기준)
- 정책 있는 문항: 정답 정책이 후보에 있었는데 판정에서 빠졌는가 (빠지면 안 된다)
- 정책 없는 문항: 지역 정책이 하나라도 근거로 남았는가 (남으면 안 된다. 그 지역 정책을 모두 읽어 관련 정책이 없다고 확인한 문항)
- 금지·방해 정책이 근거로 남았는가
- 정답이 아닌 다른 지역 정책이 남은 것은 자동으로 틀렸다고 보지 않는다. 다른 유효한 후보일 수 있어 목록만 남기고 사람이 본다.

API 비용이 든다. --max-calls 를 넘기면 시작하지 않는다. 키는 .env 에서 읽고 출력하지 않는다.

실행 예
  HF_HUB_OFFLINE=1 uv run --no-project --python 3.12 --with "sentence-transformers==6.2.0" --with qdrant-client \
      --with langchain-openai --with python-dotenv python -I scripts/eval_v4_relevance.py \
      --data-dir <청크 폴더> --manifest data/eval/v4/manifests/v4-eval-0.1_r1.json \
      --qdrant-collection welfare_chunks_v3_6efc3b7671b3 --out data/eval/v4/results/<이름>.json \
      data/eval/v4/life_questions_draft.jsonl data/eval/v4/life_variants_draft.jsonl
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_v4_retrieval import file_sha256, read_jsonl, search_text  # noqa: E402

# 비용 추정용 (gpt-4.1-mini 표준 요금, 100만 토큰당 달러). 실제 청구액과 다를 수 있다.
PRICE_PER_M = {"input": 0.40, "output": 1.60}


def chat_region(region: dict) -> dict | None:
    """평가 문항의 지역을 채팅 요청의 region 모양으로."""
    if not region.get("sido"):
        return None
    return {"kind": "region", "sido_name": region["sido"], "sigungu_name": region.get("sigungu")}


def doc_id(d: dict) -> str | None:
    return d.get("policy_id") or d.get("section_id")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="4차 근거 판정(문서별 관련성) 측정 — 실제 LLM 호출")
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--qdrant-collection", required=True)
    ap.add_argument("--qdrant-url", default="http://localhost:6333")
    ap.add_argument("--split", default="tune", choices=["tune", "holdout"])
    ap.add_argument("--max-calls", type=int, default=60, help="LLM 호출 상한. 문항 수가 이보다 많으면 시작하지 않는다")
    ap.add_argument("--limit", type=int, help="앞의 몇 문항만 (도구 점검용)")
    ap.add_argument("--replay", type=Path,
                    help="API 를 부르지 않고, 이전 결과 파일에 남은 LLM 응답을 그대로 다시 채점한다 (판정 검사 코드만 바꿨을 때)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("files", type=Path, nargs="+")
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit(f"[중단] 결과 파일이 이미 있습니다 (덮어쓰지 않음): {args.out}")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    frozen = {e["file"]: e["sha256"] for e in manifest["files"]}
    questions = []
    for path in args.files:
        if frozen.get(path.name) != file_sha256(path):
            raise SystemExit(f"[중단] 고정 기록과 다른 파일입니다: {path.name}")
        questions += [r for r in read_jsonl(path) if r["split"] == args.split and r["eval_type"] == "retrieval"]
    if args.limit:
        questions = questions[: args.limit]
    if len(questions) > args.max_calls:
        raise SystemExit(f"[중단] 문항 {len(questions)}개가 호출 상한 {args.max_calls}을 넘습니다.")
    data_version = json.loads((args.data_dir / "release_manifest.json").read_text(encoding="utf-8"))["data_version"]
    if manifest["data_version"] != data_version:
        raise SystemExit("[중단] 평가 세트와 청크의 데이터 버전이 다릅니다.")

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")   # 키는 .env 에서만 읽는다. 다른 값은 아래에서 명시한 설정을 쓴다.
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.agents import evidence_check, welfare_retrieval_v3
    from src.agents.evidence_check import EVIDENCE_PROMPT_V3, make_evidence_node
    from src.agents.welfare_retrieval_v3 import make_grouped_retrieval_node
    from src.generation.llm import get_llm
    from src.retrieval import grouped_search
    from src.retrieval.config import load_settings

    settings = load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": args.qdrant_collection,
                              "RAG_DATA_VERSION": data_version, "QDRANT_URL": args.qdrant_url})
    usage = collections.Counter()
    calls: list[dict] = []
    replay, replay_from = None, None
    if args.replay:
        old = json.loads(args.replay.read_text(encoding="utf-8"))
        if old.get("prompt_sha256") != hashlib.sha256(EVIDENCE_PROMPT_V3.encode("utf-8")).hexdigest():
            raise SystemExit("[중단] 이전 결과와 판정 프롬프트가 달라 다시 채점할 수 없습니다 (프롬프트를 바꿨으면 새로 측정하세요).")
        if any(not r.get("llm_input_sha256") for r in old["per_question"]):
            raise SystemExit("[중단] 이전 결과에 LLM 입력 지문이 없어 같은 입력인지 확인할 수 없습니다.")
        replay = {r["qid"]: (r["llm_input_sha256"], r["llm_raw"]) for r in old["per_question"]}
        replay_from = {"file": args.replay.name, "model": old.get("model"), "measured_at": old.get("measured_at")}
        current_qid: list[str] = [""]
    llm = None if replay else get_llm()

    def llm_call(system_text: str, user_text: str) -> str:
        """실제 LLM 호출. 토큰 사용량을 함께 남긴다. --replay 면 이전 응답을 그대로 돌려준다."""
        input_sha = hashlib.sha256((system_text + "\n\u0000\n" + user_text).encode("utf-8")).hexdigest()
        if replay is not None:
            want, raw = replay.get(current_qid[0], (None, None))
            if want != input_sha:   # 검색 결과·문서 순서·본문·프롬프트 중 하나라도 달라졌으면 재사용하지 않는다
                raise SystemExit(f"[중단] {current_qid[0]}: LLM 입력이 이전 측정과 달라 다시 채점할 수 없습니다.")
            calls.append({"raw": raw, "input_sha256": input_sha})
            return raw
        response = llm.invoke([SystemMessage(content=system_text), HumanMessage(content=user_text)])
        meta = getattr(response, "usage_metadata", None) or {}
        usage["input"] += int(meta.get("input_tokens") or 0)
        usage["output"] += int(meta.get("output_tokens") or 0)
        usage["calls"] += 1
        calls.append({"raw": str(response.content), "input_sha256": input_sha})   # 응답은 자르지 않고 남긴다
        return str(response.content).strip()

    def search(question, selection, **kwargs):
        return grouped_search.search_grouped(question, selection, settings=settings, exact=True, **kwargs)

    retrieve = make_grouped_retrieval_node(search)
    judge = make_evidence_node(llm_call=llm_call)

    per_question = []
    started = time.time()
    for n, q in enumerate(questions, 1):
        if replay is not None:
            current_qid[0] = q["qid"]
        exp = q["expected"]
        state = {"question": q["question"], "region": chat_region(q["region"]), "search_query": search_text(q)}
        state.update(retrieve(state))
        before = list(state["retrieved_docs"])
        context = evidence_check.select_context_docs(before, limit=8)   # 판정에 실제로 보낸 문서 (번호 순서)
        calls_before = len(calls)
        out = judge(state)
        result = out.get("retrieval_result") or state["retrieval_result"]
        relevance = result.get("relevance") or {}
        kept_ids = {d.get("chunk_id") for d in out.get("retrieved_docs", [])} if relevance.get("status") == "judged" else set()
        cands = [{"no": i, "group": d.get("evidence_group"), "id": doc_id(d), "title": d.get("title"),
                  "kept": d.get("chunk_id") in kept_ids} for i, d in enumerate(context, 1)]

        gold = set(exp["local_policy_ids"])
        local_c = [c for c in cands if c["group"] == "local"]
        rec = {
            "qid": q["qid"], "base": q.get("base_qid") or q["qid"], "kind": q.get("variant_kind") or "base",
            "status": q["label"]["status"], "local_case": exp["local_case"], "question": q["question"],
            "search_query": state["search_query"], "verdict": out.get("evidence_verdict"), "reason": out.get("evidence_reason"),
            "relevance_status": relevance.get("status") or "not_v3",
            "candidates": cands,
            "llm_raw": calls[calls_before]["raw"] if len(calls) > calls_before else None,
            "llm_input_sha256": calls[calls_before]["input_sha256"] if len(calls) > calls_before else None,
        }
        judged = rec["relevance_status"] == "judged"
        if exp["local_case"] == "has_policy":
            in_cands = gold & {c["id"] for c in local_c}
            rec["gold_in_candidates"] = bool(in_cands)
            if in_cands and judged:
                rec["gold_kept"] = bool(in_cands & {c["id"] for c in local_c if c["kept"]})
            rec["other_local_kept"] = [c["title"] for c in local_c if c["kept"] and c["id"] not in gold]
        else:
            rec["local_kept_when_none"] = [c["title"] for c in local_c if c["kept"]] if judged else None
        rec["must_not_kept"] = [c["id"] for c in cands if c["kept"] and c["id"] in set(exp["must_not_ids"]) | set(exp["distractor_ids"])]
        rec["kept_counts"] = dict(collections.Counter(c["group"] for c in cands if c["kept"]))
        rec["dropped_local"] = sum(1 for c in local_c if not c["kept"])
        rec["quote_mismatch"] = relevance.get("quote_mismatch", 0)
        notes = {c.get("chunk_id"): c for c in result.get("candidates_before_relevance") or []}
        for c, d in zip(cands, context):
            note = notes.get(d.get("chunk_id")) or {}
            c.update({k: note[k] for k in ("why", "quote", "quote_unverified", "dropped", "note") if note.get(k)})
        per_question.append(rec)
        print(f"[{n:>2}/{len(questions)}] {q['qid']:<5} {rec['relevance_status']:<9} {str(rec['verdict']):<12} "
              f"남김 {rec['kept_counts']} | {q['question'][:28]}", flush=True)

    def summarize(rows: list[dict]) -> dict:
        has = [r for r in rows if "gold_kept" in r]
        none = [r for r in rows if r["local_case"] == "no_policy" and r.get("local_kept_when_none") is not None]
        return {
            "questions": len(rows),
            "judged": sum(r["relevance_status"] == "judged" for r in rows),
            "failed_or_uncertain": sum(r["relevance_status"] in ("failed", "uncertain") for r in rows),
            "verdicts": dict(collections.Counter(str(r["verdict"]) for r in rows)),
            "gold_in_candidates": f"{sum(r.get('gold_in_candidates', False) for r in rows)}/{sum(r['local_case'] == 'has_policy' for r in rows)}",
            "gold_kept": f"{sum(r['gold_kept'] for r in has)}/{len(has)}",
            "no_policy_clean": f"{sum(not r['local_kept_when_none'] for r in none)}/{len(none)}",
            "must_not_or_distractor_kept": sum(bool(r["must_not_kept"]) for r in rows),
            "quote_mismatch_docs": sum(r.get("quote_mismatch", 0) for r in rows),
            "local_candidates_dropped": sum(r["dropped_local"] for r in rows),
            "local_candidates_total": sum(sum(c["group"] == "local" for c in r["candidates"]) for r in rows),
        }

    checked = [r for r in per_question if r["status"] == "user_checked"]
    cost = usage["input"] / 1e6 * PRICE_PER_M["input"] + usage["output"] / 1e6 * PRICE_PER_M["output"]
    report = {
        "what": "4차 근거 판정(문서별 관련성) 측정. 검색 후보는 실제 Qdrant 에서 고정, 판정은 실제 LLM. 공식 성능 아님",
        "split": args.split, "manifest": {"name": manifest["name"], "revision": manifest["revision"]},
        "data_version": data_version, "collection": args.qdrant_collection,
        "model": replay_from["model"] if replay_from else getattr(llm, "model_name", None),
        "replayed_from": replay_from,
        "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "code_sha256": {
            "script": file_sha256(Path(__file__)),
            "evidence_check": file_sha256(Path(evidence_check.__file__)),
            "welfare_retrieval_v3": file_sha256(Path(welfare_retrieval_v3.__file__)),
            "grouped_search": file_sha256(Path(grouped_search.__file__)),
        },
        "prompt_sha256": hashlib.sha256(EVIDENCE_PROMPT_V3.encode("utf-8")).hexdigest(),
        "usage": {**usage, "estimated_usd": round(cost, 4), "price_basis": PRICE_PER_M, "seconds": round(time.time() - started, 1)},
        "caution": "정답이 아닌 지역 정책이 남은 것(other_local_kept)은 틀렸다고 채점하지 않았다. 사람이 원문을 보고 판단해야 한다. "
                   "질문 문장을 그대로 검색어로 썼다(의도 확인 LLM 미사용).",
        "user_checked": summarize(checked), "all_including_draft": summarize(per_question),
        "per_question": per_question,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print("\n사람 확인 문항:", json.dumps(report["user_checked"], ensure_ascii=False))
    print("초안 포함 전체:", json.dumps(report["all_including_draft"], ensure_ascii=False))
    print("사용량:", json.dumps(report["usage"], ensure_ascii=False))
    print("결과 저장:", args.out)


if __name__ == "__main__":
    main()
