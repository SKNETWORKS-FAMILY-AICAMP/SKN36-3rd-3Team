"""4차 평가 세트로 검색 방식 두 가지를 비교한다 (읽기 전용. DB에 쓰지 않고 벡터 파일만 읽는다).

  legacy : "v3 데이터에서 재현한 3차 검색 방식". 지역 구분 없이 전체에서 상위 12개 청크를 뽑은 뒤
           3차 코드의 지역 규칙(시도·시군구 이름 일치)으로 걸러 내고 최대 8개를 근거로 쓴다.
  split  : 묶음별 검색. 고른 지역의 정책 / 전국 PDF / 지역 미상 자료를 따로 찾는다. (벡터 파일로 흉내 낸 값)
  v3_code: --qdrant-collection 을 주면, 실제 코드(src/retrieval/grouped_search.search_grouped)로 Qdrant 에 읽기 전용 질의를 한다.
           같은 질문 벡터를 쓰고 전수 비교(exact)로 찾아서 split 과 결과가 같은지도 대조한다.

주의
- 실제 서비스 코드를 돌린 값이 아니라 방식을 흉내 낸 값이다. 3차의 Neo4j 검색, LLM 질의 재작성, 재검색은 재현하지 않았다.
- 검색 단계만 본다. "없는데 있다고 답했는가"는 답변을 만든 뒤에야 잴 수 있으므로 여기서는 "지역 정책이 반환됐는가"만 센다.
- 두 방식은 같은 질문 문장, 같은 임베딩, 같은 벡터를 쓰고, 근거로 넘기는 개수도 최대 8개로 같다.
- 다만 legacy 는 청크 단위, split 은 지역 정책을 정책 단위로 중복 제거한다. 그래서 차이를 "분리 검색만의 효과"로 단정하지 않는다.
- "지역 정책 Hit@k"(local_hit@k)는 전국 PDF를 뺀 지역 정책 목록의 상위 k개 안에 정답이 있는지를 본다 (전체 결과의 상위 k개가 아니다).

실행 예
  uv run --no-project --python 3.12 --with "sentence-transformers==6.2.0" python -I scripts/eval_v4_retrieval.py \
      --vec-dir <벡터 폴더> --data-dir <청크 폴더> --manifest data/eval/v4/manifests/v4-eval-0.1_r1.json \
      --out data/eval/v4/results/<이름>.json data/eval/v4/life_questions_draft.jsonl data/eval/v4/life_variants_draft.jsonl
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

LEGACY_K, LEGACY_LIMIT, MAX_PER_SECTION = 12, 8, 2   # 3차 코드의 값 (make_retrieval_node k=12, select_context_docs limit=8)
LOCAL_K, NATIONAL_K, UNVERIFIED_K = 5, 3, 3          # 묶음별 검색 (조정 전 임시값). 근거는 지역 5 + 전국 3 = 최대 8개로 legacy 와 같게 맞춤
FOLLOWUP_WORDS = ("그건", "그거", "그 정책", "그 서비스", "거기", "그곳", "그럼", "그러면", "신청은", "대상은", "조건은")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def search_text(row: dict) -> str:
    """3차 코드(build_search_question)와 같은 규칙: 짧은 후속 질문이면 앞의 사용자 말을 붙인다."""
    q = row["question"].strip()
    prev = [t["text"].strip() for t in row.get("history") or [] if t.get("role") == "user"]
    if prev and len(q) <= 80 and any(w in q for w in FOLLOWUP_WORDS):
        return f"이전 질문: {prev[-1][:300]}\n현재 질문: {q}"
    return q


class Index:
    def __init__(self, vec_dir: Path, data_dir: Path) -> None:
        self.vec = np.load(vec_dir / "vectors.npy", allow_pickle=False)
        with open(vec_dir / "chunk_map.csv", encoding="utf-8", newline="") as f:
            cmap = list(csv.DictReader(f))
        meta = {}
        for name in ("policy_chunks.jsonl", "guideline_chunks.jsonl"):
            for r in read_jsonl(data_dir / name):
                meta[r["chunk_id"]] = r
        assert len(cmap) == self.vec.shape[0] == len(meta), "벡터와 청크 수가 다름"
        assert [int(c["row"]) for c in cmap] == list(range(len(cmap))), "대응표의 행 순서가 벡터와 다름"
        for c in cmap:   # 벡터를 만들 때의 본문과 지금 청크 본문이 같은지 (행 대응 확인)
            if hashlib.sha256(meta[c["chunk_id"]]["text"].encode("utf-8")).hexdigest() != c["text_sha256"]:
                raise SystemExit(f"[중단] 벡터를 만든 본문과 지금 청크 본문이 다름: {c['chunk_id']}")
        self.is_policy = np.array([c["record_type"] == "policy" for c in cmap])
        self.row = {c["chunk_id"]: i for i, c in enumerate(cmap)}
        self.item, self.keys, self.sido, self.sigungu = [], [], [], []
        for c in cmap:
            r = meta[c["chunk_id"]]
            m = r["metadata"]
            if c["record_type"] == "policy":
                self.item.append(r["policy_id"])
                self.keys.append({f"{e['sido']}|{e['sigungu']}" for e in m.get("applies_to") or []})
            else:
                self.item.append(r["section_id"])
                self.keys.append(set())
            self.sido.append(m.get("sido_name") or "")
            self.sigungu.append(m.get("sigungu_name") or "")

    def applies(self, i: int, sido: str, sigungu: str) -> bool:
        return f"{sido}|{sigungu}" in self.keys[i]

    def legacy(self, s: np.ndarray, sido: str, sigungu: str) -> dict:
        """전체 상위 12개 -> 3차 지역 규칙(시도 이름 일치 + 시군구 이름 일치, 전국 PDF는 통과) -> 절마다 2개까지, 최대 8개."""
        top = np.argsort(-s)[:LEGACY_K]
        kept, per_section = [], collections.Counter()
        for i in top:
            if self.is_policy[i]:
                if self.sido[i] != sido or self.sigungu[i] != sigungu:
                    continue
            else:
                if per_section[self.item[i]] >= MAX_PER_SECTION:
                    continue
                per_section[self.item[i]] += 1
            kept.append(int(i))
            if len(kept) >= LEGACY_LIMIT:
                break
        return {"evidence": kept, "unverified_list": [], "candidates": int(len(top))}

    def split(self, s: np.ndarray, sido: str, sigungu: str) -> dict:
        """지역 키로 먼저 거른 지역 정책 / 전국 PDF / 시도 등록·지역 미상 자료를 따로 찾는다. 미상 자료는 근거에 넣지 않는다."""
        key = f"{sido}|{sigungu}"
        local = [i for i in np.where(self.is_policy)[0] if key in self.keys[i]]
        unknown = [i for i in np.where(self.is_policy)[0] if not self.keys[i] and self.sido[i] == sido]
        evidence = self._top_items(s, local, LOCAL_K)
        per_section = collections.Counter()
        for i in np.argsort(-s):
            if self.is_policy[i] or per_section[self.item[i]] >= MAX_PER_SECTION:
                continue
            per_section[self.item[i]] += 1
            evidence.append(int(i))
            if sum(per_section.values()) >= NATIONAL_K:
                break
        return {"evidence": evidence, "unverified_list": self._top_items(s, unknown, UNVERIFIED_K), "candidates": len(local)}

    def _top_items(self, s: np.ndarray, pool: list, k: int) -> list[int]:
        """정책마다 점수가 가장 높은 청크 하나만 남겨 상위 k개 정책."""
        best: dict[str, int] = {}
        for i in pool:
            if self.item[i] not in best or s[i] > s[best[self.item[i]]]:
                best[self.item[i]] = int(i)
        return sorted(best.values(), key=lambda i: -s[i])[:k]


def score_row(ix: Index, row: dict, got: dict, s: np.ndarray) -> dict:
    exp, region = row["expected"], row["region"]
    sido, sigungu = region["sido"], region["sigungu"]
    ev = got["evidence"]
    local_ranked = list(dict.fromkeys(ix.item[i] for i in ev if ix.is_policy[i]))   # 근거에 든 정책 (순위 유지, 중복 제거)
    sections = {ix.item[i] for i in ev if not ix.is_policy[i]}
    gold = set(exp["local_policy_ids"])
    out = {
        "returned_local": len(local_ranked), "returned_total": len(ev), "candidates": got["candidates"],
        "wrong_region": any(ix.is_policy[i] and ix.keys[i] and not ix.applies(i, sido, sigungu) for i in ev),
        "unverified_in_evidence": any(ix.is_policy[i] and not ix.keys[i] for i in ev),
        "must_not_hit": bool(set(exp["must_not_ids"]) & set(local_ranked)),
        "top_local_score": max((round(float(s[i]), 4) for i in ev if ix.is_policy[i]), default=None),
    }
    if exp["local_case"] == "has_policy":
        for k in (1, 3, 5):
            out[f"local_hit@{k}"] = bool(gold & set(local_ranked[:k]))
    else:
        out["local_returned_when_none"] = bool(local_ranked)   # 검색 단계 사실일 뿐, 잘못 안내했다는 뜻은 아님
    if exp["national_section_ids"]:
        out["national_hit"] = bool(set(exp["national_section_ids"]) & sections)
    if exp["region_unverified_policy_ids"]:
        out["unverified_list_hit"] = bool(set(exp["region_unverified_policy_ids"]) & {ix.item[i] for i in got["unverified_list"]})
    return out


METRICS = ("local_hit@1", "local_hit@3", "local_hit@5", "national_hit", "unverified_list_hit", "local_returned_when_none",
           "wrong_region", "unverified_in_evidence", "must_not_hit")


def summarize(rows: list[dict]) -> dict:
    """지표마다 해당 문항 수(n)와 비율. 해당하지 않는 문항은 분모에서 뺀다."""
    out = {"questions": len(rows)}
    for m in METRICS:
        vals = [r[m] for r in rows if m in r]
        if vals:
            out[m] = {"n": len(vals), "rate": round(sum(vals) / len(vals), 3)}
    if rows:
        out["avg_returned_local"] = round(sum(r["returned_local"] for r in rows) / len(rows), 2)
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="4차 평가 세트 검색 방식 비교 (읽기 전용)")
    ap.add_argument("--vec-dir", type=Path, required=True)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--split", default="tune", choices=["tune", "holdout"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--qdrant-collection", help="주면 실제 묶음별 검색 코드로 이 컬렉션에 읽기 전용 질의를 한다")
    ap.add_argument("--qdrant-url", default="http://localhost:6333")
    ap.add_argument("files", type=Path, nargs="+")
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit(f"[중단] 결과 파일이 이미 있습니다 (덮어쓰지 않음): {args.out}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    frozen = {e["file"]: e["sha256"] for e in manifest["files"]}
    questions = []
    for path in args.files:
        if frozen.get(path.name) != file_sha256(path):
            raise SystemExit(f"[중단] 고정 기록과 다른 파일입니다: {path.name} (문항이 바뀌었으면 새 고정 기록을 남기세요)")
        questions += [r for r in read_jsonl(path) if r["split"] == args.split and r["eval_type"] == "retrieval"]

    emb = json.loads((args.vec_dir / "embedding_info.json").read_text(encoding="utf-8"))
    info = emb["embedding"]   # 적재 때와 같은 모델·판
    # 입력 무결성: 평가 세트·청크·벡터가 모두 같은 데이터 버전이고, 임베딩 기록에 적힌 파일 지문과 지금 파일이 같아야 한다.
    data_version = json.loads((args.data_dir / "release_manifest.json").read_text(encoding="utf-8"))["data_version"]
    if not (manifest["data_version"] == emb["data_version"] == data_version):
        raise SystemExit("[중단] 평가 세트·벡터·청크의 데이터 버전이 서로 다릅니다.")
    recorded = {**{n: v["sha256"] for n, v in emb["inputs"].items()}, **emb["outputs"]}
    for name, want in recorded.items():
        folder = args.data_dir if name in emb["inputs"] else args.vec_dir
        if file_sha256(folder / name) != want:
            raise SystemExit(f"[중단] 임베딩 기록과 다른 파일입니다: {name}")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(info["model"], revision=info["revision"], device="cpu")
    ix = Index(args.vec_dir, args.data_dir)
    texts = [search_text(r) for r in questions]
    qv = model.encode([t.replace("\n", " ") for t in texts], normalize_embeddings=True)

    methods = ["legacy", "split"]
    code = None
    if args.qdrant_collection:   # 실제 코드 경로. 저장소 루트를 경로에 넣어 src 패키지를 불러온다.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from src.retrieval import grouped_search, region_rules
        from src.retrieval.config import load_settings
        code = load_settings({"RAG_RETRIEVAL_MODE": "v3", "QDRANT_COLLECTION": args.qdrant_collection,
                              "RAG_DATA_VERSION": data_version, "QDRANT_URL": args.qdrant_url})
        methods.append("v3_code")

    per_question = []
    for r, text, v in zip(questions, texts, qv):
        s = v @ ix.vec.T
        sido, sigungu = r["region"]["sido"], r["region"]["sigungu"]
        rec = {"qid": r["qid"], "base": r.get("base_qid") or r["qid"], "kind": r.get("variant_kind") or "base",
               "limit_type": r.get("limit_type"), "status": r["label"]["status"], "local_case": r["expected"]["local_case"],
               "search_text": text}
        for name, fn in (("legacy", ix.legacy), ("split", ix.split)):
            rec[name] = score_row(ix, r, fn(s, sido, sigungu), s)
        if code:
            out = grouped_search.search_grouped(
                text, region_rules.select_region(sido, sigungu), settings=code, embed=lambda _q, v=v: v.tolist(),
                local_k=LOCAL_K, national_k=NATIONAL_K, unverified_k=UNVERIFIED_K, exact=True)
            got = {"evidence": [ix.row[d["chunk_id"]] for d in out["local"] + out["national"]],
                   "unverified_list": [ix.row[d["chunk_id"]] for d in out["unverified"]],
                   "candidates": out["info"]["fetched"].get("local", 0)}
            rec["v3_code"] = score_row(ix, r, got, s)
            rec["v3_code"]["dropped"] = sum(out["info"]["dropped"].values())
            rec["v3_code"]["short"] = out["info"]["short"]
            # 벡터 파일로 흉내 낸 split 과 같은 결과인가. 다르면 점수 차가 아주 작은 동점인지 본다.
            sim = ix.split(s, sido, sigungu)
            pairs = list(zip(sim["evidence"] + sim["unverified_list"], got["evidence"] + got["unverified_list"]))
            same_len = len(sim["evidence"]) == len(got["evidence"]) and len(sim["unverified_list"]) == len(got["unverified_list"])
            gap = max((abs(float(s[a]) - float(s[b])) for a, b in pairs if a != b), default=0.0)
            rec["code_vs_simulation"] = ("same" if same_len and all(a == b for a, b in pairs)
                                         else "tie" if same_len and gap < 1e-4 else "different")
            rec["code_vs_simulation_gap"] = round(gap, 6)
        per_question.append(rec)

    def table(rows: list[dict]) -> dict:
        return {m: summarize([r[m] for r in rows]) for m in methods}

    checked = [r for r in per_question if r["status"] == "user_checked"]
    by_base = collections.defaultdict(list)
    for r in checked:
        by_base[r["base"]].append(r)
    report = {
        "what": "검색 방식 비교 (공식 성능 아님). legacy·split 은 방식 모의, v3_code 는 실제 묶음별 검색 코드", "split": args.split,
        "methods": methods,
        "v3_code": None if not code else {
            "collection": code.collection, "qdrant_url": code.qdrant_url, "exact": True,
            "vs_simulation": dict(collections.Counter(r["code_vs_simulation"] for r in per_question)),
            "dropped_total": sum(r["v3_code"]["dropped"] for r in per_question),
            # 지역 규칙과 맞지 않아 뺀 자료가 하나라도 있으면 점수와 별개로 검증 실패다.
            "verification_failed": any(r["v3_code"]["dropped"] for r in per_question),
            "short_questions": [r["qid"] for r in per_question if r["v3_code"]["short"]]},
        "manifest": {"name": manifest["name"], "revision": manifest["revision"]}, "data_version": data_version,
        "script_sha256": file_sha256(Path(__file__)), "inputs_sha256": recorded,
        "caution": "legacy 는 청크 단위, split 은 지역 정책을 정책 단위로 중복 제거한다. 분리 검색만의 효과로 단정하지 않는다. "
                   "local_hit@k 는 전국 PDF를 뺀 지역 정책 목록 기준. national_hit 는 문항당 등록한 기준 절 기준의 참고 지표.",
        "embedding": {"model": info["model"], "revision": info["revision"]},
        "params": {"legacy": {"top_k": LEGACY_K, "limit": LEGACY_LIMIT, "max_per_section": MAX_PER_SECTION},
                   "split": {"local_k": LOCAL_K, "national_k": NATIONAL_K, "unverified_k": UNVERIFIED_K}},
        "user_checked": table(checked), "all_including_draft": table(per_question),
        "user_checked_by_kind": {k: table([r for r in checked if r["kind"] == k]) for k in sorted({r["kind"] for r in checked})},
        "user_checked_by_base": {b: table(rs) for b, rs in sorted(by_base.items())},
        "per_question": per_question,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8", newline="\n")

    def show(title: str, t: dict) -> None:
        print(f"\n[{title}]")
        for m in methods:
            cells = [f"{k} {v['rate']:.0%}({v['n']})" for k, v in t[m].items() if isinstance(v, dict)]
            print(f"  {m:<7} 문항 {t[m]['questions']:>2} | " + " | ".join(cells))

    if code:
        print("실제 코드와 모의(split) 대조:", report["v3_code"]["vs_simulation"], "| 지역 규칙 불일치로 뺀 건수:",
              report["v3_code"]["dropped_total"], "| 한도까지 받고도 못 채운 문항:", report["v3_code"]["short_questions"])
    show("사람 확인 문항만", report["user_checked"])
    show("초안 포함 전체", report["all_including_draft"])
    for k, t in report["user_checked_by_kind"].items():
        show(f"사람 확인 · 종류 {k}", t)
    for b, t in report["user_checked_by_base"].items():
        show(f"사람 확인 · 기준 문항 {b}", t)
    print(f"\n결과 저장: {args.out}")


if __name__ == "__main__":
    main()
