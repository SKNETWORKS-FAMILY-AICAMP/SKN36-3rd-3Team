"""Runpod에서 내려받은 v3 임베딩 결과를 검사한다 (내 PC에서 실행, 읽기 전용).

검사하는 것
  - 결과 파일이 전송 중 손상되지 않았는지 (해시)
  - 승인된 v3 청크 파일로 만든 것이 맞는지 (입력 해시, 버전)
  - 벡터의 줄 순서와 청크가 정확히 대응하는지
  - 벡터 자체가 정상인지 (개수, 차원, 빈 값, 정규화)
  - (선택) 본문이 같은 3차 청크의 벡터와 얼마나 가까운지

DB에 쓰지 않는다. --qdrant-url 을 주면 3차 컬렉션을 "읽기만" 한다.

사용 예
  python verify_v3_vectors.py --vectors-dir out_full --data-dir <청크 폴더>
  python verify_v3_vectors.py --vectors-dir out_full --data-dir <청크 폴더> \
      --script scripts/embed_v3_chunks.py --qdrant-url http://localhost:6333 --collection welfare_chunks_v1
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import urllib.request
import uuid
from pathlib import Path

import numpy as np

MODEL = "nlpai-lab/KURE-v1"
REVISION = "8b418a58414668e75532ed045c22d9ca018ae2b2"
DIM = 1024
PREPROCESS = "newline_to_space"
MAX_SEQ_LENGTH = 8192
BATCH_SIZE = 16
OUTPUT_FILES = ("vectors.npy", "chunk_map.csv")
MANIFEST = "release_manifest.json"
INPUTS = (("policy", "policy_chunks.jsonl"), ("guideline", "guideline_chunks.jsonl"))

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> bool:
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return status != "FAIL"


def check(ok: bool, name: str, detail: str = "") -> bool:
    return record("PASS" if ok else "FAIL", name, detail)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest_hash(manifest: dict, file_name: str) -> str | None:
    hits = [v for k, v in manifest.get("files", {}).items() if k.replace("\\", "/").split("/")[-1] == file_name]
    return hits[0] if len(hits) == 1 else None


def load_chunks(data_dir: Path) -> list[dict]:
    rows = []
    for record_type, name in INPUTS:
        with open(data_dir / name, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    rows.append({"record_type": record_type, "chunk_id": r["chunk_id"], "point_id": r["id"], "text": r["text"]})
    return rows


def config_id(emb: dict) -> str:
    """embed_v3_chunks.py 의 config_id 와 같은 계산."""
    key = {k: emb.get(k) for k in ("model", "revision", "dim", "normalize", "preprocess", "dtype", "max_seq_length")}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def spread_rows(n: int, count: int, boundary: int) -> list[int]:
    """처음·끝·파일 경계를 포함해 고르게 뽑는다. 줄이 한 칸이라도 밀리면 걸리게 하기 위해서다."""
    picks = {0, n - 1, boundary - 1, boundary} | {round(i * (n - 1) / max(count - 1, 1)) for i in range(count)}
    return sorted(i for i in picks if 0 <= i < n)


def fetch_old_points(url: str, collection: str, ids: list[str]) -> dict[str, dict]:
    """3차 컬렉션에서 같은 id의 본문과 벡터를 읽어 온다 (조회 요청만 사용)."""
    found: dict[str, dict] = {}
    for i in range(0, len(ids), 200):
        body = json.dumps({"ids": ids[i:i + 200], "with_payload": ["page_content"], "with_vector": True}).encode()
        req = urllib.request.Request(f"{url.rstrip('/')}/collections/{collection}/points", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            for p in json.load(resp)["result"]:
                found[p["id"]] = p
    return found


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="v3 임베딩 결과 검사 (읽기 전용)")
    ap.add_argument("--vectors-dir", type=Path, required=True, help="vectors.npy, chunk_map.csv, embedding_info.json 이 있는 폴더")
    ap.add_argument("--data-dir", type=Path, required=True, help="청크 파일 2개와 release_manifest.json 이 있는 폴더")
    ap.add_argument("--script", type=Path, default=None, help="실행에 쓴 embed_v3_chunks.py (해시 대조용)")
    ap.add_argument("--qdrant-url", default=None, help="3차 벡터와 비교할 때만 지정 (읽기만 함)")
    ap.add_argument("--collection", default="welfare_chunks_v1")
    ap.add_argument("--recheck", type=int, default=0, help="이 개수만큼 내 PC에서 다시 계산해 대조 (sentence-transformers 필요, CPU는 1개당 1~2초)")
    ap.add_argument("--allow-sample", action="store_true", help="--limit 로 만든 시험 결과도 허용")
    args = ap.parse_args()

    info = json.loads((args.vectors_dir / "embedding_info.json").read_text(encoding="utf-8"))
    manifest = json.loads((args.data_dir / MANIFEST).read_text(encoding="utf-8"))
    emb = info["embedding"]

    # 1. 전송 무결성
    for name in OUTPUT_FILES:
        expected = info.get("outputs", {}).get(name)
        check(bool(expected) and sha256_file(args.vectors_dir / name) == expected, f"결과 파일 해시: {name}",
              "" if expected else "실행 기록에 해시가 없음")

    # 2. 승인된 입력으로 만들었는가
    check(manifest.get("status") == "approved", "매니페스트 승인 상태", str(manifest.get("status")))
    check(info["data_version"] == manifest["data_version"], "데이터 버전", info["data_version"])
    check(info["manifest_sha256"] == sha256_file(args.data_dir / MANIFEST), "매니페스트 해시")
    for _, name in INPUTS:
        local = sha256_file(args.data_dir / name)
        check(local == info["inputs"][name]["sha256"] == manifest_hash(manifest, name), f"입력 파일 해시: {name}")

    # 3. 임베딩 설정
    expected_cfg = {"model": MODEL, "revision": REVISION, "dim": DIM, "normalize": True, "preprocess": PREPROCESS,
                    "dtype": "torch.float32", "prompt": None, "max_seq_length": MAX_SEQ_LENGTH,
                    "batch_size": BATCH_SIZE, "distance": "cosine"}
    wrong = {k: emb.get(k) for k, v in expected_cfg.items() if emb.get(k) != v}
    if emb.get("config_id") != config_id(emb):
        wrong["config_id"] = emb.get("config_id")
    check(not wrong, "임베딩 설정 (모델·리비전·차원·정규화·전처리·fp32·입력 한도·배치)",
          json.dumps(wrong, ensure_ascii=False) if wrong else emb["config_id"])
    check(info["max_tokens"] <= emb["max_seq_length"], "토큰 한도", f"최대 {info['max_tokens']} / 한도 {emb['max_seq_length']}")
    if args.script:
        check(sha256_file(args.script) == info["script"]["sha256"], "실행 스크립트 해시")
    else:
        record("SKIP", "실행 스크립트 해시", "--script 미지정")

    # 4. 줄 순서와 청크 대응
    chunks = load_chunks(args.data_dir)
    with open(args.vectors_dir / "chunk_map.csv", encoding="utf-8", newline="") as f:
        cmap = list(csv.DictReader(f))
    vectors = np.load(args.vectors_dir / "vectors.npy", allow_pickle=False)
    sample = bool(info.get("sample"))
    check(len(cmap) == info["n_rows"] == vectors.shape[0], "개수 일치 (대응표 = 기록 = 벡터)", f"{len(cmap):,}")
    check(info.get("n_rows_total") == len(chunks), "실행 기록의 전체 청크 수", f"{len(chunks):,}")
    if sample:
        record("WARN" if args.allow_sample else "FAIL", "시험 실행 결과",
               f"{len(cmap):,} / {len(chunks):,}개만 있음. 적재용이 아님" + ("" if args.allow_sample else " (시험 결과를 보려면 --allow-sample)"))
        by_id = {c["chunk_id"]: c for c in chunks}
        targets = [by_id.get(m["chunk_id"]) for m in cmap]
        check(all(t is not None for t in targets), "대응표의 청크가 모두 입력에 있음")
    else:
        check(len(cmap) == len(chunks), "전체 청크 수", f"{len(chunks):,}")
        targets = chunks if len(cmap) == len(chunks) else [None] * len(cmap)
    bad = 0
    for i, (m, c) in enumerate(zip(cmap, targets)):
        if c is None or int(m["row"]) != i or m["chunk_id"] != c["chunk_id"] or m["point_id"] != c["point_id"] \
                or m["record_type"] != c["record_type"] or m["text_sha256"] != sha256_text(c["text"]) \
                or m["embed_input_sha256"] != sha256_text(c["text"].replace("\n", " ")) \
                or m["point_id"] != str(uuid.uuid5(uuid.NAMESPACE_URL, m["chunk_id"])):
            bad += 1
    check(bad == 0, "줄 순서·ID·본문 해시 대응", f"불일치 {bad}건")
    check(len({m["point_id"] for m in cmap}) == len(cmap), "ID 중복 없음")

    # 5. 벡터 자체
    check(vectors.ndim == 2 and vectors.shape[1] == DIM and vectors.dtype == np.float32, "벡터 모양·자료형", f"{vectors.shape} {vectors.dtype}")
    finite = bool(np.isfinite(vectors).all())
    check(finite, "NaN·Inf 없음")
    if finite:
        norms = np.linalg.norm(vectors, axis=1)
        check(float(np.abs(norms - 1).max()) < 1e-3, "정규화 (길이 1)", f"{norms.min():.6f} ~ {norms.max():.6f}")
        # 본문이 다른데 벡터가 완전히 같으면 줄이 밀렸거나 복사된 것이다.
        seen: dict[bytes, str] = {}
        clash = 0
        for m, v in zip(cmap, vectors):
            key = v.tobytes()
            if seen.setdefault(key, m["embed_input_sha256"]) != m["embed_input_sha256"]:
                clash += 1
        check(clash == 0, "서로 다른 본문이 같은 벡터를 갖지 않음", f"{clash}건")

    # 6. (선택) 3차 벡터와 비교
    if args.qdrant_url:
        old = fetch_old_points(args.qdrant_url, args.collection, [m["point_id"] for m in cmap])
        sims = []
        for m, c, v in zip(cmap, targets, vectors):
            p = old.get(m["point_id"])
            if p and c and p["payload"].get("page_content") == c["text"]:
                sims.append(cosine(v, np.asarray(p["vector"], dtype=np.float32)))
        if not sims:
            record("SKIP", "3차 벡터 비교", "본문이 같은 청크가 없음")
        else:
            lo, mean = min(sims), sum(sims) / len(sims)
            status = "PASS" if lo >= 0.999 else ("WARN" if lo >= 0.99 else "FAIL")
            record(status, "3차 벡터 비교 (본문이 같은 청크의 코사인)", f"{len(sims):,}개, 최소 {lo:.6f}, 평균 {mean:.6f}")
    else:
        record("SKIP", "3차 벡터 비교", "--qdrant-url 미지정")

    # 7. (선택) 독립 재계산: 대응표가 아니라 "그 줄의 벡터가 정말 그 본문의 것인지"를 확인한다.
    if args.recheck > 0 and bad == 0:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(MODEL, revision=REVISION)
        boundary = sum(m["record_type"] == "policy" for m in cmap)
        picks = spread_rows(len(cmap), args.recheck, boundary)
        again = model.encode([targets[i]["text"].replace("\n", " ") for i in picks], batch_size=BATCH_SIZE,
                             normalize_embeddings=True, convert_to_numpy=True)
        sims = [cosine(vectors[i], again[k]) for k, i in enumerate(picks)]
        worst = picks[sims.index(min(sims))]
        check(min(sims) >= 0.999, "독립 재계산 대조 (처음·끝·경계 포함)",
              f"{len(picks)}개, 최소 {min(sims):.6f} (줄 {worst}: {cmap[worst]['chunk_id']})")
    else:
        record("SKIP", "독립 재계산 대조", "--recheck 미지정" if args.recheck <= 0 else "대응 불일치로 생략")

    fails = sum(s == "FAIL" for s, _, _ in results)
    warns = sum(s == "WARN" for s, _, _ in results)
    print(f"\n검사 {len(results)}개: FAIL {fails}, WARN {warns}")
    if fails:
        print("결론: 사용하면 안 됩니다. FAIL 항목을 먼저 해결하세요.")
        raise SystemExit(1)
    print("결론: 시험 실행 결과로는 정상입니다 (적재용 아님)." if sample else "결론: 적재에 사용할 수 있습니다.")


if __name__ == "__main__":
    main()
