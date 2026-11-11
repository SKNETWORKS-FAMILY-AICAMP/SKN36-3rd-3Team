"""A/B/C 공통 채점 코드. 세 안 모두 이 파일 하나로 채점한다.

검색 함수 규칙 (세 안 모두 같은 모양):
    retrieve(question, sido, sigungu, k) -> [{"parent_id": ..., "score": ..., "text": ..., "source": ...}, ...]  (순위대로)
    → 서로 다른 parent_id 기준 최대 k개. 청크 단위로 찾는 안은 넉넉히 찾은 뒤 dedup_top(results, k)로 맞춘다.

채점 규칙:
    - 결과에서 같은 parent_id는 처음 것만 남긴다 (청크가 많은 정책이 유리하지 않게)
    - 정답 묶음이 1개인 질문 = "단일": 상위 5개 안 첫 정답 순위로 Hit@1·Hit@5·MRR@5
    - 정답 묶음이 2개 이상 = "묶음": 상위 10개 안에서 Recall@10(찾은 묶음/전체 묶음)·Precision@10
    - 함정은 금지 ID 또는 지자체 정책 노출 여부로 채점한다.
    - 답변의 기권 여부가 필요한 문항은 미채점, 시설 검색 문항은 벡터 평가에서 제외한다.
"""
import json, time
import pandas as pd

K_SINGLE, K_SET = 5, 10


def load_questions(path, set_name):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = json.loads(line)
            question = q.get("question") or q.get("user_input")
            if "expected_groups" in q:
                groups = q["expected_groups"]
            else:                                   # v3: expected_ids = 정답 후보 (하나만 찾아도 정답)
                groups = [q["expected_ids"]] if q.get("expected_ids") else []
            q_type = q.get("q_type") or q.get("query_category")
            must_not = q.get("must_not_ids") or []
            is_trap = str(q_type).startswith("함정") or not groups
            mode = "trap" if is_trap else ("single" if len(groups) == 1 else "set")
            if q_type == "함정_시설데이터":
                mode = "excluded"
            rows.append({
                "set": set_name, "qid": q["qid"], "question": question,
                "q_type": q_type,
                "persona": q.get("persona_name"),
                "sido": q.get("user_sido"), "sigungu": q.get("user_sigungu"),
                "groups": groups, "must_not": must_not, "mode": mode,
            })
    return rows


def dedup_top(results, k):
    """같은 parent_id는 처음 것만 남기고 앞에서부터 k개 (순서 유지)"""
    out, seen = [], set()
    for r in results:
        pid = r.get("parent_id")
        if pid and pid not in seen:
            seen.add(pid)
            out.append(r)
        if len(out) == k:
            break
    return out


def unique_parents(results):
    pids = []
    for r in results:
        pid = r.get("parent_id")
        if pid and pid not in pids:
            pids.append(pid)
    return pids


def score_one(q, results):
    pids = unique_parents(results)
    row = {"set": q["set"], "qid": q["qid"], "q_type": q["q_type"], "persona": q["persona"], "mode": q["mode"],
           "n_returned": len(pids), "top1": pids[0] if pids else None}
    row["n_graph_verified"] = sum(bool(result.get("neo4j_evidence")) for result in results)
    row["ranked_parent_ids"] = json.dumps(pids, ensure_ascii=False)
    if results and "qdrant_rank" in results[0]:
        row["fusion_ranks"] = json.dumps(
            [[result["qdrant_rank"], result["neo4j_rank"]] for result in results]
        )
    if q["mode"] == "excluded":
        row.update(trap_pass=None, scoring_note="시설 DB 평가 대상")
        return row
    if q["mode"] == "single":
        top = pids[:K_SINGLE]
        answers = set(q["groups"][0])
        rank = next((i for i, p in enumerate(top, start=1) if p in answers), None)
        row.update(rank=rank, hit1=rank == 1, hit5=rank is not None, rr=(1 / rank) if rank else 0.0)
    elif q["mode"] == "set":
        top = pids[:K_SET]
        found = sum(any(i in top for i in g) for g in q["groups"])
        flat = {i for g in q["groups"] for i in g}
        row.update(recall10=found / len(q["groups"]),
                   precision10=(sum(p in flat for p in top) / len(top)) if top else 0.0)
    must_not = set(q["must_not"])
    row["must_not_hits"] = sum(p in must_not for p in pids[:K_SET])
    if q["mode"] == "trap":
        if must_not:
            row["trap_pass"] = row["must_not_hits"] == 0
        elif q["q_type"] == "함정_데이터없는지역":
            has_local_policy = any(parent.startswith("local:") for parent in pids[:K_SET])
            row.update(trap_pass=not has_local_policy, scoring_note="지자체 정책 노출 여부")
        else:
            row.update(trap_pass=None, scoring_note="답변 기권 평가 필요")
    return row


def run_eval(retrieve, questions, system_name):
    """retrieve: 검색 함수, questions: load_questions 결과 리스트, system_name: "A_qdrant" 등"""
    rows = []
    for q in questions:
        if q["mode"] == "excluded":
            row = score_one(q, [])
            row.update(system=system_name, sec=None)
            rows.append(row)
            continue
        k = K_SINGLE if q["mode"] == "single" else K_SET
        t0 = time.time()
        results = retrieve(q["question"], q["sido"], q["sigungu"], k)
        sec = time.time() - t0
        row = score_one(q, results)
        row.update(system=system_name, sec=round(sec, 3))
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(detail):
    """안(system) × 질문 세트별 요약표"""
    out = []
    for (system, set_name), g in detail.groupby(["system", "set"]):
        s, m, t = g[g["mode"] == "single"], g[g["mode"] == "set"], g[g["mode"] == "trap"]
        scored_traps = t["trap_pass"].dropna() if len(t) else pd.Series(dtype=bool)
        out.append({
            "system": system, "set": set_name,
            "단일_n": len(s), "Hit@1": round(s["hit1"].mean(), 3) if len(s) else None,
            "Hit@5": round(s["hit5"].mean(), 3) if len(s) else None,
            "MRR@5": round(s["rr"].mean(), 3) if len(s) else None,
            "묶음_n": len(m), "Recall@10": round(m["recall10"].mean(), 3) if len(m) else None,
            "Precision@10": round(m["precision10"].mean(), 3) if len(m) else None,
            "함정_n": len(t), "함정_채점_n": len(scored_traps),
            "함정통과": int(scored_traps.sum()) if len(scored_traps) else None,
            "함정_미채점_n": len(t) - len(scored_traps),
            "제외_n": int(g["mode"].eq("excluded").sum()),
            "검색(초/질문)": round(g["sec"].mean(), 3),
        })
    return pd.DataFrame(out)
