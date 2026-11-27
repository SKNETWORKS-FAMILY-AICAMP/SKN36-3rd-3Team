"""v3 청크 임베딩 스크립트 (Runpod GPU에서 실행).

하는 일
  1. 승인된 release_manifest.json 과 청크 파일 2개의 해시를 대조한다.
  2. 청크 본문을 3차와 같은 설정(KURE-v1, 리비전 고정, 줄바꿈→공백, 정규화)으로 벡터로 바꾼다.
  3. 벡터와 "어느 줄이 어느 청크인지" 대응표, 실행 기록을 파일로 남긴다.

하지 않는 일
  - Qdrant·Neo4j 등 어떤 DB에도 쓰지 않는다. 결과 파일만 만든다.
  - 입력 파일을 고치지 않는다.

사용 예
  python embed_v3_chunks.py --input-dir . --limit 100     # 시험 실행 (시간 측정)
  python embed_v3_chunks.py --input-dir .                 # 전체 실행
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

MODEL = "nlpai-lab/KURE-v1"
REVISION = "8b418a58414668e75532ed045c22d9ca018ae2b2"
DIM = 1024
BATCH_SIZE = 16          # 3차 실행과 같은 값
MAX_SEQ_LENGTH = 8192    # 3차 실행 기록과 같은 값
DTYPE = "torch.float32"
NORMALIZE = True
PREPROCESS = "newline_to_space"
MANIFEST = "release_manifest.json"
# (record_type, 파일 이름). 이 순서가 곧 벡터의 줄 순서다.
INPUTS = (("policy", "policy_chunks.jsonl"), ("guideline", "guideline_chunks.jsonl"))


def embed_input(text: str) -> str:
    """모델에 실제로 넣는 글자. 3차(LangChain HuggingFaceEmbeddings)와 같은 전처리."""
    return text.replace("\n", " ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def config_id(dtype: str, max_seq_length: int) -> str:
    """임베딩 설정을 한 줄로 식별하는 짧은 값. 질문 쪽도 같은 설정이어야 한다."""
    key = {"model": MODEL, "revision": REVISION, "dim": DIM, "normalize": NORMALIZE,
           "preprocess": PREPROCESS, "dtype": dtype, "max_seq_length": max_seq_length}
    return sha256_bytes(json.dumps(key, sort_keys=True).encode())[:12]


def fail(message: str) -> None:
    print(f"[중단] {message}", file=sys.stderr)
    raise SystemExit(1)


def load_manifest(input_dir: Path) -> tuple[dict, str]:
    path = input_dir / MANIFEST
    if not path.is_file():
        fail(f"{MANIFEST} 이 없습니다: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("status") != "approved":
        fail(f"매니페스트가 승인 상태가 아닙니다: status={manifest.get('status')!r}")
    return manifest, sha256_file(path)


def manifest_hash(manifest: dict, file_name: str) -> str:
    hits = [v for k, v in manifest.get("files", {}).items() if k.replace("\\", "/").split("/")[-1] == file_name]
    if len(hits) != 1:
        fail(f"매니페스트에서 {file_name} 해시를 하나로 찾지 못했습니다 ({len(hits)}개).")
    return hits[0]


def load_chunks(input_dir: Path, manifest: dict) -> tuple[list[dict], dict]:
    version = manifest["data_version"]
    rows: list[dict] = []
    file_info: dict = {}
    for record_type, name in INPUTS:
        path = input_dir / name
        if not path.is_file():
            fail(f"입력 파일이 없습니다: {path}")
        digest = sha256_file(path)
        if digest != manifest_hash(manifest, name):
            fail(f"{name} 해시가 매니페스트와 다릅니다. 파일이 바뀌었거나 전송 중 손상됐습니다.")
        count = 0
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                where = f"{name}:{line_no}"
                text = row.get("text")
                if not isinstance(text, str) or not text.strip():
                    fail(f"{where} 본문이 비어 있습니다.")
                if row.get("data_version") != version:
                    fail(f"{where} data_version 이 매니페스트와 다릅니다.")
                if (row.get("metadata") or {}).get("record_type") != record_type:
                    fail(f"{where} record_type 이 {record_type} 가 아닙니다.")
                if row.get("id") != str(uuid.uuid5(uuid.NAMESPACE_URL, row.get("chunk_id") or "")):
                    fail(f"{where} id 가 chunk_id 에서 만든 UUID 와 다릅니다.")
                rows.append({"record_type": record_type, "chunk_id": row["chunk_id"], "point_id": row["id"], "text": text})
                count += 1
        file_info[name] = {"sha256": digest, "rows": count}
    for key in ("chunk_id", "point_id"):
        if len({r[key] for r in rows}) != len(rows):
            fail(f"{key} 가 중복됩니다.")
    return rows, file_info


def pick_sample(rows: list[dict], limit: int) -> list[dict]:
    """길이가 고르게 섞이도록 뽑는다 (짧은 것만 뽑으면 시간 추정이 틀린다)."""
    order = sorted(range(len(rows)), key=lambda i: (len(rows[i]["text"]), i))
    step = len(order) / limit
    chosen = sorted({order[int(i * step)] for i in range(limit)})
    return [rows[i] for i in chosen]


def write_atomic(path: Path, writer) -> None:
    tmp = path.with_name(path.name + ".tmp")
    writer(tmp)
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser(description="v3 청크 임베딩 (DB에 쓰지 않음)")
    ap.add_argument("--input-dir", type=Path, default=Path("."), help="청크 파일 2개와 release_manifest.json 이 있는 폴더")
    ap.add_argument("--out-dir", type=Path, default=None, help="결과 폴더 (기본: out_full 또는 out_sample)")
    ap.add_argument("--limit", type=int, default=0, help="시험용: 이 개수만 뽑아 실행")
    ap.add_argument("--device", default="cuda", help="cuda(기본) 또는 cpu")
    args = ap.parse_args()
    if args.limit < 0:
        fail("--limit 은 0(전체) 또는 양수여야 합니다.")

    started_at = datetime.now(timezone.utc)
    manifest, manifest_sha = load_manifest(args.input_dir)
    all_rows, file_info = load_chunks(args.input_dir, manifest)
    total = len(all_rows)
    is_sample = 0 < args.limit < total
    rows = pick_sample(all_rows, args.limit) if is_sample else all_rows
    out_dir = args.out_dir or Path("out_sample" if is_sample else "out_full")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"입력 확인 완료: 버전 {manifest['data_version']}, 전체 {total:,}개, 이번 실행 {len(rows):,}개")

    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    if args.device == "cuda" and not torch.cuda.is_available():
        fail("GPU가 보이지 않습니다. Pod 설정을 확인하거나 --device cpu 를 지정하세요.")

    t0 = time.time()
    model = SentenceTransformer(MODEL, revision=REVISION, device=args.device)
    load_sec = time.time() - t0
    dtype = str(next(model.parameters()).dtype)
    max_len = int(model.max_seq_length)
    # 3차와 다른 조건으로 계산되는 일을 막는다: 계산 정밀도, 입력 한도, 자동으로 붙는 지시문.
    if dtype != DTYPE:
        fail(f"모델 계산 자료형이 {DTYPE} 가 아닙니다: {dtype}")
    if max_len != MAX_SEQ_LENGTH:
        fail(f"모델 입력 한도가 {MAX_SEQ_LENGTH} 가 아닙니다: {max_len}")
    if getattr(model, "default_prompt_name", None) is not None:
        fail(f"모델에 기본 지시문이 설정돼 있습니다: {model.default_prompt_name!r}")

    inputs = [embed_input(r["text"]) for r in rows]
    # 잘림 없이 들어가는지 먼저 확인한다. 넘으면 뒷부분이 조용히 버려지기 때문이다.
    token_counts = [len(ids) for ids in model.tokenizer(inputs, add_special_tokens=True, truncation=False)["input_ids"]]
    if max(token_counts) > max_len:
        worst = rows[token_counts.index(max(token_counts))]["chunk_id"]
        fail(f"토큰 수 {max(token_counts)} 가 모델 한도 {max_len} 를 넘습니다: {worst}")

    if args.device == "cuda":  # 첫 호출의 준비 시간이 측정에 섞이지 않게 한다.
        model.encode(inputs[:BATCH_SIZE], batch_size=BATCH_SIZE, normalize_embeddings=NORMALIZE)
        torch.cuda.synchronize()
    t0 = time.time()
    vectors = model.encode(inputs, batch_size=BATCH_SIZE, normalize_embeddings=NORMALIZE,
                           convert_to_numpy=True, show_progress_bar=True)
    if args.device == "cuda":
        torch.cuda.synchronize()
    encode_sec = time.time() - t0

    vectors = np.ascontiguousarray(vectors)
    if vectors.shape != (len(rows), DIM):
        fail(f"벡터 모양이 다릅니다: {vectors.shape}")
    if vectors.dtype != np.float32:
        fail(f"벡터 자료형이 float32 가 아닙니다: {vectors.dtype}")
    if not np.isfinite(vectors).all():
        fail("벡터에 NaN 또는 Inf 가 있습니다.")
    norms = np.linalg.norm(vectors, axis=1)
    if np.abs(norms - 1.0).max() > 1e-3:
        fail(f"정규화되지 않은 벡터가 있습니다 (길이 {norms.min():.5f}~{norms.max():.5f}).")

    vec_path, map_path = out_dir / "vectors.npy", out_dir / "chunk_map.csv"

    def save_vectors(tmp: Path) -> None:
        with open(tmp, "wb") as f:
            np.save(f, vectors)

    def save_map(tmp: Path) -> None:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["row", "record_type", "chunk_id", "point_id", "text_sha256", "embed_input_sha256", "n_chars", "n_tokens"])
            for i, (r, s, n) in enumerate(zip(rows, inputs, token_counts)):
                w.writerow([i, r["record_type"], r["chunk_id"], r["point_id"],
                            sha256_bytes(r["text"].encode("utf-8")), sha256_bytes(s.encode("utf-8")), len(r["text"]), n])

    write_atomic(vec_path, save_vectors)
    write_atomic(map_path, save_map)

    import importlib.metadata as im

    def version(pkg: str) -> str | None:
        try:
            return im.version(pkg)
        except im.PackageNotFoundError:
            return None

    info = {
        "data_version": manifest["data_version"],
        "manifest_sha256": manifest_sha,
        "inputs": file_info,
        "row_order": [name for _, name in INPUTS],
        "n_rows": len(rows),
        "n_rows_total": total,
        "sample": is_sample,
        "embedding": {
            "model": MODEL, "revision": REVISION, "dim": DIM, "dtype": dtype, "max_seq_length": max_len,
            "normalize": NORMALIZE, "batch_size": BATCH_SIZE, "preprocess": PREPROCESS, "prompt": None,
            "distance": "cosine", "config_id": config_id(dtype, max_len),
        },
        "max_tokens": max(token_counts),
        "timing": {"model_load_sec": round(load_sec, 1), "encode_sec": round(encode_sec, 2),
                   "chunks_per_sec": round(len(rows) / encode_sec, 1)},
        "environment": {
            "device": args.device,
            "gpu": torch.cuda.get_device_name(0) if args.device == "cuda" else None,
            "torch": torch.__version__, "cuda": torch.version.cuda,
            "sentence-transformers": version("sentence-transformers"), "transformers": version("transformers"),
            "numpy": np.__version__, "python": platform.python_version(), "platform": platform.platform(),
        },
        "script": {"name": Path(__file__).name, "sha256": sha256_file(Path(__file__))},
        "outputs": {vec_path.name: sha256_file(vec_path), map_path.name: sha256_file(map_path)},
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    info_path = out_dir / "embedding_info.json"
    write_atomic(info_path, lambda tmp: tmp.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"))

    print(f"\n완료: {len(rows):,}개 → {out_dir}/ (vectors.npy, chunk_map.csv, embedding_info.json)")
    print(f"모델 불러오기 {load_sec:.0f}초, 임베딩 {encode_sec:.1f}초 ({len(rows) / encode_sec:.0f}개/초), 최대 토큰 {max(token_counts)} / 한도 {max_len}")
    if is_sample:
        print(f"시험 실행입니다. 전체 {total:,}개 예상 임베딩 시간: 약 {total / (len(rows) / encode_sec):.0f}초")
    else:
        print("결과 폴더를 통째로 내려받아 verify_v3_vectors.py 로 검사하세요.")


if __name__ == "__main__":
    main()
