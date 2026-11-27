"""4차(v3) 채팅 전체 흐름 소규모 측정: 의도 확인 → 묶음별 검색 → 근거 판정 → 답변을 실제 LLM 으로 돌린다.

검색은 실제 Qdrant(전수 비교), LLM 은 .env 의 키로 실제 호출한다(키는 출력하지 않는다). 대화 기록 DB 는 쓰지 않고,
평가 문항에 정해 둔 이전 대화(history)를 그대로 넣는다. 자동 채점은 최소한만 하고 답변 원문을 남겨 사람이 본다.

자동으로 보는 것
- 답변 상태(answer_status), 의도 확인 결과와 검색어
- 정답 정책이 답변 출처에 들어갔는가 (정책 있는 검색 문항)
- 나이 제한이 있는 정책이 출처에 들어갔을 때 답변에 나이가 나오는가
- 정책 없는 지역에서 지역 정책이 출처에 들어갔는가

실행 예
  HF_HUB_OFFLINE=1 uv run --no-project --python 3.12 --with "sentence-transformers==6.2.0" --with qdrant-client \
      --with langchain-openai --with python-dotenv --with langgraph python -I scripts/eval_v4_chat.py \
      --data-dir <청크 폴더> --manifest data/eval/v4/manifests/v4-eval-0.1_r1.json \
      --qdrant-collection welfare_chunks_v3_6efc3b7671b3 --out data/eval/v4/results/<이름>.json \
      --qids L003 L006 ... data/eval/v4/life_questions_draft.jsonl data/eval/v4/life_variants_draft.jsonl
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_v4_relevance import PRICE_PER_M, chat_region  # noqa: E402
from eval_v4_retrieval import file_sha256, read_jsonl  # noqa: E402

AGE_LIMIT = re.compile(r"만\s*\d{2}\s*[~∼-]\s*\d{2}\s*세|\d{2}\s*세\s*이하|중장년")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="4차 채팅 전체 흐름 소규모 측정 — 실제 LLM 호출")
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--qdrant-collection", required=True)
    ap.add_argument("--qdrant-url", default="http://localhost:6333")
    ap.add_argument("--qids", nargs="+", required=True)
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("files", type=Path, nargs="+")
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit(f"[중단] 결과 파일이 이미 있습니다 (덮어쓰지 않음): {args.out}")
    if len(args.qids) * 3 > args.max_calls:
        raise SystemExit(f"[중단] 문항 {len(args.qids)}개 x 최대 3회가 호출 상한 {args.max_calls}을 넘습니다.")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    frozen = {e["file"]: e["sha256"] for e in manifest["files"]}
    rows = {}
    for path in args.files:
        if frozen.get(path.name) != file_sha256(path):
            raise SystemExit(f"[중단] 고정 기록과 다른 파일입니다: {path.name}")
        rows.update({r["qid"]: r for r in read_jsonl(path)})
    missing = [q for q in args.qids if q not in rows]
    if missing:
        raise SystemExit(f"[중단] 없는 문항: {missing}")
    data_version = json.loads((args.data_dir / "release_manifest.json").read_text(encoding="utf-8"))["data_version"]

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.agents import graph as graph_module
    from src.agents import intent_check
    from src.agents.evidence_check import EVIDENCE_PROMPT_V3 as evidence_prompt
    from src.generation.llm import get_llm
    from src.retrieval import grouped_search
    from src.retrieval.config import load_settings

    settings = load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": args.qdrant_collection,
                              "RAG_DATA_VERSION": data_version, "QDRANT_URL": args.qdrant_url})
    llm = get_llm()
    usage = collections.Counter()
    current: list[dict] = []

    def llm_call(system_text: str, user_text: str) -> str:
        response = llm.invoke([SystemMessage(content=system_text), HumanMessage(content=user_text)])
        meta = getattr(response, "usage_metadata", None) or {}
        usage["input"] += int(meta.get("input_tokens") or 0)
        usage["output"] += int(meta.get("output_tokens") or 0)
        usage["calls"] += 1
        stage = ("evidence" if system_text == evidence_prompt else "intent" if system_text == intent_check.INTENT_PROMPT
                 else "answer")
        current.append({"stage": stage, "chars_in": len(system_text) + len(user_text)})
        if stage == "answer":
            current[-1]["answer_input"] = user_text   # 나이 제한이 답변 입력에 실제 들어갔는지 보려고 남긴다
        return str(response.content).strip()

    intent_check.call_llm = llm_call   # 의도 확인도 같은 호출 함수를 쓰게 해 사용량을 함께 센다

    def search(question, selection, **kwargs):
        return grouped_search.search_grouped(question, selection, settings=settings, exact=True, **kwargs)

    graph = graph_module.build_graph(grouped_search=search, llm_call=llm_call)

    per_question = []
    started = time.time()
    for qid in args.qids:
        q = rows[qid]
        current.clear()
        history = [{"role": t["role"], "content": t["text"]} for t in q.get("history") or []]
        state = {"question": q["question"], "session_id": None, "region": chat_region(q["region"]), "history": history}
        out = graph.invoke(state)
        exp = q["expected"]
        result = out.get("retrieval_result") or {}
        sources = [s.get("parent_id") for s in out.get("sources") or []]
        kept_titles = [d.get("title") for d in out.get("retrieved_docs") or []]
        answer_inputs = [c["answer_input"] for c in current if c.get("answer_input")]
        rec = {
            "qid": qid, "kind": q.get("variant_kind") or "base", "limit_type": q.get("limit_type"), "eval_type": q["eval_type"],
            "status": q["label"]["status"], "question": q["question"], "history": history, "region": q["region"],
            "intent": out.get("intent"), "search_query": out.get("search_query"),
            "answer_status": out.get("answer_status"), "safety_status": out.get("safety_status"),
            "evidence_verdict": out.get("evidence_verdict"), "relevance": result.get("relevance"),
            "sources": sources, "kept_titles": kept_titles, "answer": out.get("answer"),
            "llm_stages": [c["stage"] for c in current],
        }
        if q["eval_type"] == "retrieval":
            gold = set(exp.get("local_policy_ids") or [])
            if exp.get("local_case") == "has_policy":
                rec["gold_in_sources"] = bool(gold & set(sources))
            else:
                rec["local_in_sources_when_none"] = [s for s in sources if str(s).startswith("local:")]
        age_docs = [d.get("title") for d in out.get("retrieved_docs") or [] if AGE_LIMIT.search(str(d.get("text") or ""))]
        if age_docs:
            rec["age_limited_docs"] = age_docs
            rec["age_limit_in_answer_input"] = any(AGE_LIMIT.search(x) for x in answer_inputs)
            rec["age_limit_in_answer"] = bool(AGE_LIMIT.search(str(out.get("answer") or "")))
        per_question.append(rec)
        print(f"{qid:<5} {str(rec['intent']):<8} {str(rec['answer_status']):<15} 판정 {str(rec['evidence_verdict']):<12} "
              f"호출 {rec['llm_stages']} | {q['question'][:26]}", flush=True)

    cost = usage["input"] / 1e6 * PRICE_PER_M["input"] + usage["output"] / 1e6 * PRICE_PER_M["output"]
    has = [r for r in per_question if "gold_in_sources" in r]
    none = [r for r in per_question if "local_in_sources_when_none" in r]
    age = [r for r in per_question if "age_limited_docs" in r]
    report = {
        "what": "4차 채팅 전체 흐름 소규모 측정 (의도 확인·묶음별 검색·근거 판정·답변, 실제 LLM). 공식 성능 아님. 답변은 사람이 확인해야 함",
        "manifest": {"name": manifest["name"], "revision": manifest["revision"]}, "data_version": data_version,
        "collection": args.qdrant_collection, "model": getattr(llm, "model_name", None),
        "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "code_sha256": {"script": file_sha256(Path(__file__))},
        "usage": {**usage, "estimated_usd": round(cost, 4), "price_basis": PRICE_PER_M, "seconds": round(time.time() - started, 1)},
        "summary": {
            "questions": len(per_question),
            "answer_status": dict(collections.Counter(str(r["answer_status"]) for r in per_question)),
            "gold_in_sources": f"{sum(r['gold_in_sources'] for r in has)}/{len(has)}",
            "no_local_when_none": f"{sum(not r['local_in_sources_when_none'] for r in none)}/{len(none)}",
            "age_limit_in_answer": f"{sum(r['age_limit_in_answer'] for r in age)}/{len(age)}",
        },
        "per_question": per_question,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print("\n요약:", json.dumps(report["summary"], ensure_ascii=False))
    print("사용량:", json.dumps(report["usage"], ensure_ascii=False))
    print("결과 저장:", args.out)


if __name__ == "__main__":
    main()
