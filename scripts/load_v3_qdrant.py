"""검증된 v3 벡터를 Qdrant의 "새 컬렉션"에 적재한다.

하는 일
  1. 승인 기록·청크 파일·벡터 파일·대응표의 해시와 내용을 다시 대조한다.
  2. 청크마다 Qdrant에 넣을 내용(본문 + 메타데이터 + 파생 칸)을 만든다.
  3. --execute 를 준 경우에만: 새 컬렉션 생성 → 색인 생성 → 적재 → 전수 검증.

하지 않는 일
  - 기본 실행은 "계획 확인"이다. --execute 없이는 DB에 아무것도 쓰지 않는다.
  - 컬렉션을 삭제하거나 다시 만들지 않는다. 같은 이름이 있으면 멈춘다.
  - 3차 컬렉션(welfare_chunks_v1 등)은 읽지도 쓰지도 않는다.
  - 서비스 전환(.env 변경)은 하지 않는다.

사용 예
  python load_v3_qdrant.py --vectors-dir out_full --data-dir <청크 폴더>               # 계획 확인 (쓰지 않음)
  python load_v3_qdrant.py --vectors-dir out_full --data-dir <청크 폴더> --execute     # 실제 적재 + 검증
  python load_v3_qdrant.py --vectors-dir out_full --data-dir <청크 폴더> --verify-only # 적재된 것 검증만 (읽기 전용)
  python load_v3_qdrant.py ... --execute --resume    # 적재 도중 끊겼을 때만. 같은 작업인지 확인 후 전체를 다시 넣는다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import numpy as np

MODEL = "nlpai-lab/KURE-v1"
REVISION = "8b418a58414668e75532ed045c22d9ca018ae2b2"
DIM = 1024
DISTANCE = "Cosine"
MANIFEST = "release_manifest.json"
INFO = "embedding_info.json"
OUTPUT_FILES = ("vectors.npy", "chunk_map.csv")
# (record_type, 파일 이름). 이 순서가 곧 벡터의 줄 순서다 (embed_v3_chunks.py 와 같다).
INPUTS = (("policy", "policy_chunks.jsonl"), ("guideline", "guideline_chunks.jsonl"))

COLLECTION_PREFIX = "welfare_chunks_v3_"
LOAD_SCHEMA_VERSION = 1   # 아래 "넣는 내용의 모양"을 바꾸면 반드시 올린다.
NATIONAL_KEY = "national"
# 적재할 때 metadata 에 새로 만들어 넣는 칸. 원본에 같은 이름이 있으면 덮어쓰지 않고 멈춘다.
DERIVED_KEYS = ("applies_to_keys", "release_status", "embedding_config_id", "load_id")
# 검색 조건으로 쓰는 칸. Qdrant 안의 실제 경로(metadata. 로 시작)로 적는다.
INDEX_FIELDS = (
    "metadata.record_type", "metadata.parent_id", "metadata.policy_id", "metadata.applies_to_keys",
    "metadata.scope_status", "metadata.data_version", "metadata.release_status",
    "metadata.sido_name", "metadata.sigungu_name",
)
UPSERT_BATCH = 128
SCROLL_BATCH = 256
MIN_COSINE = 0.9999       # Qdrant는 Cosine 벡터를 스스로 정규화하므로 바이트가 아니라 수치로 비교한다.
STATUS_WAIT_SEC = 60
# 읽기 전용 실행에서 허용하는 POST. Qdrant 에서 이 셋은 조회만 한다. (뒤에 ?옵션이 붙은 경로는 허용하지 않는다)
READ_ONLY_POST = re.compile(r"/collections/[^/?#]+/points/(count|scroll|query)")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

results: list[tuple[str, str, str]] = []


def fail(message: str) -> None:
    sys.stdout.flush()   # 앞서 출력한 내용 뒤에 중단 사유가 보이도록 한다.
    print(f"[중단] {message}", file=sys.stderr)
    raise SystemExit(1)


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


def short_hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


def manifest_hash(manifest: dict, file_name: str) -> str:
    hits = [v for k, v in manifest.get("files", {}).items() if k.replace("\\", "/").split("/")[-1] == file_name]
    if len(hits) != 1:
        fail(f"매니페스트에서 {file_name} 해시를 하나로 찾지 못했습니다 ({len(hits)}개).")
    return hits[0]


# ───────────────────────── 1. 내 PC의 파일 검사 + 넣을 내용 만들기 ─────────────────────────

def region_keys(meta: dict, where: str) -> list[str]:
    """정책의 적용 지역을 검색용 키 목록으로 바꾼다. 예: ["인천광역시|연수구"]

    추정하지 않는다. 시군구가 없는 원소처럼 약속되지 않은 모양이 나오면 멈춘다.
    ("시도 전체 적용" 키는 근거 데이터가 생겼을 때 규칙을 정해서 추가한다.)
    """
    applies = meta.get("applies_to")
    if not isinstance(applies, list):
        fail(f"{where} applies_to 가 목록이 아닙니다.")
    keys: list[str] = []
    for e in applies:
        ok = isinstance(e, dict) and set(e) == {"sido", "sigungu"} and all(
            isinstance(e[k], str) and e[k].strip() == e[k] and e[k] and "|" not in e[k] for k in ("sido", "sigungu"))
        if not ok:
            fail(f"{where} applies_to 원소가 약속한 모양(시도+시군구)이 아닙니다: {e!r}")
        keys.append(f"{e['sido']}|{e['sigungu']}")
    if len(set(keys)) != len(keys):
        fail(f"{where} applies_to 에 같은 지역이 두 번 있습니다.")
    if (meta.get("scope_status") == "unknown") != (not keys):
        fail(f"{where} scope_status={meta.get('scope_status')!r} 와 applies_to 개수({len(keys)})가 맞지 않습니다.")
    return keys


def build_payload(row: dict, record_type: str, manifest: dict, emb_config_id: str, load_id: str, where: str) -> dict:
    meta = dict(row["metadata"])
    for key in DERIVED_KEYS:
        if key in meta:
            fail(f"{where} 원본 메타데이터에 이미 {key} 칸이 있습니다. 덮어쓰지 않고 멈춥니다.")
    if meta.get("chunk_id") != row["chunk_id"] or meta.get("data_version") != row["data_version"]:
        fail(f"{where} 바깥쪽 chunk_id·data_version 이 메타데이터와 다릅니다.")
    if record_type == "policy":
        if "policy_id" in meta or meta.get("parent_id") != row.get("policy_id") or not row.get("policy_id"):
            fail(f"{where} policy_id 가 없거나 parent_id 와 다릅니다.")
        meta["policy_id"] = row["policy_id"]          # 정책 상세 조회(metadata.policy_id)에 쓴다.
        meta["applies_to_keys"] = region_keys(meta, where)
    else:
        if meta.get("region_scope") != "national":
            fail(f"{where} 안내서인데 region_scope 가 national 이 아닙니다: {meta.get('region_scope')!r}")
        if meta.get("section_id") != row.get("section_id") or meta.get("parent_id") != row.get("section_id"):
            fail(f"{where} section_id 가 메타데이터·parent_id 와 다릅니다.")
        meta["applies_to_keys"] = [NATIONAL_KEY]
    meta["release_status"] = manifest["status"]       # 공개 승인은 청크별 approval_status 가 아니라 매니페스트가 기준이다.
    meta["embedding_config_id"] = emb_config_id
    meta["load_id"] = load_id
    return {"page_content": row["text"], "metadata": meta}


def prepare(vectors_dir: Path, data_dir: Path) -> dict:
    """파일을 전부 다시 대조하고, 적재할 점(point) 목록을 만든다. DB에 접속하지 않는다."""
    for path in [data_dir / MANIFEST, vectors_dir / INFO] + [vectors_dir / n for n in OUTPUT_FILES] \
            + [data_dir / n for _, n in INPUTS]:
        if not path.is_file():
            fail(f"파일이 없습니다: {path}")
    manifest = json.loads((data_dir / MANIFEST).read_text(encoding="utf-8"))
    info = json.loads((vectors_dir / INFO).read_text(encoding="utf-8"))
    emb = info.get("embedding", {})
    version = manifest.get("data_version")

    if manifest.get("status") != "approved":
        fail(f"매니페스트가 승인 상태가 아닙니다: status={manifest.get('status')!r}")
    if info.get("data_version") != version:
        fail("벡터를 만든 데이터 버전이 매니페스트와 다릅니다.")
    manifest_sha = sha256_file(data_dir / MANIFEST)
    if info.get("manifest_sha256") != manifest_sha:
        fail("매니페스트가 벡터를 만들 때의 것과 다릅니다 (해시 불일치).")
    if info.get("sample") or info.get("n_rows") != info.get("n_rows_total"):
        fail("시험 실행(--limit) 결과입니다. 전체 실행 결과만 적재할 수 있습니다.")
    for name in OUTPUT_FILES:
        if sha256_file(vectors_dir / name) != info.get("outputs", {}).get(name):
            fail(f"{name} 해시가 실행 기록과 다릅니다. 파일이 바뀌었거나 손상됐습니다.")

    expected = {"model": MODEL, "revision": REVISION, "dim": DIM, "normalize": True, "preprocess": "newline_to_space",
                "dtype": "torch.float32", "prompt": None, "max_seq_length": 8192, "batch_size": 16,
                "distance": "cosine"}
    wrong = {k: emb.get(k) for k, v in expected.items() if emb.get(k) != v}
    key = {k: emb.get(k) for k in ("model", "revision", "dim", "normalize", "preprocess", "dtype", "max_seq_length")}
    if wrong or emb.get("config_id") != short_hash(key):
        fail(f"임베딩 설정이 약속한 값과 다릅니다: {json.dumps(wrong, ensure_ascii=False)} config_id={emb.get('config_id')!r}")

    input_sha = {}
    for _, name in INPUTS:
        input_sha[name] = sha256_file(data_dir / name)
        if not (input_sha[name] == info["inputs"][name]["sha256"] == manifest_hash(manifest, name)):
            fail(f"{name} 해시가 매니페스트 또는 실행 기록과 다릅니다.")

    # 이 값이 같으면 "같은 입력·같은 설정·같은 모양의 적재 작업"이다. --resume 판단에 쓴다.
    load_id = short_hash({"load_schema_version": LOAD_SCHEMA_VERSION, "data_version": version,
                          "embedding_config_id": emb["config_id"], "manifest_sha256": manifest_sha,
                          "inputs": input_sha, "outputs": info["outputs"]})

    with open(vectors_dir / "chunk_map.csv", encoding="utf-8", newline="") as f:
        cmap = list(csv.DictReader(f))
    vectors = np.load(vectors_dir / "vectors.npy", allow_pickle=False)
    if vectors.ndim != 2 or vectors.shape[1] != DIM or vectors.dtype != np.float32:
        fail(f"벡터 모양·자료형이 다릅니다: {vectors.shape} {vectors.dtype}")
    if not np.isfinite(vectors).all():
        fail("벡터에 NaN 또는 Inf 가 있습니다.")
    norms = np.linalg.norm(vectors, axis=1)
    if float(np.abs(norms - 1).max()) >= 1e-3:
        fail(f"벡터가 정규화되어 있지 않습니다: {norms.min():.6f} ~ {norms.max():.6f}")

    ids: list[str] = []
    payloads: list[dict] = []
    i = 0
    for record_type, name in INPUTS:
        with open(data_dir / name, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                where = f"{name}:{line_no}"
                row = json.loads(line)
                text, meta = row.get("text"), row.get("metadata")
                if not isinstance(text, str) or not text.strip() or not isinstance(meta, dict):
                    fail(f"{where} 본문 또는 메타데이터가 비어 있습니다.")
                if row.get("data_version") != version or meta.get("record_type") != record_type:
                    fail(f"{where} data_version 또는 record_type 이 다릅니다.")
                if row.get("id") != str(uuid.uuid5(uuid.NAMESPACE_URL, row.get("chunk_id") or "")):
                    fail(f"{where} id 가 chunk_id 에서 만든 UUID 와 다릅니다.")
                if i >= len(cmap):
                    fail("청크가 대응표보다 많습니다.")
                m = cmap[i]
                if int(m["row"]) != i or m["chunk_id"] != row["chunk_id"] or m["point_id"] != row["id"] \
                        or m["record_type"] != record_type or m["text_sha256"] != sha256_text(text) \
                        or m["embed_input_sha256"] != sha256_text(text.replace("\n", " ")):
                    fail(f"{where} 대응표 {i}번째 줄과 맞지 않습니다. 벡터와 청크의 순서가 어긋났습니다.")
                ids.append(row["id"])
                payloads.append(build_payload(row, record_type, manifest, emb["config_id"], load_id, where))
                i += 1
    if not (len(ids) == len(cmap) == vectors.shape[0] == info["n_rows"]):
        fail(f"개수가 맞지 않습니다: 청크 {len(ids)}, 대응표 {len(cmap)}, 벡터 {vectors.shape[0]}, 기록 {info['n_rows']}")
    if len(set(ids)) != len(ids):
        fail("ID가 중복됩니다.")
    for p in payloads:
        json.dumps(p, allow_nan=False)   # NaN 등 JSON 으로 못 보내는 값이 있으면 여기서 멈춘다.

    suffix = version.rsplit("_", 1)[-1]
    if len(suffix) != 12 or any(c not in "0123456789abcdef" for c in suffix):
        fail(f"data_version 끝의 버전 해시를 읽지 못했습니다: {version!r}")
    return {"collection": COLLECTION_PREFIX + suffix, "data_version": version, "load_id": load_id,
            "embedding_config_id": emb["config_id"], "ids": ids, "payloads": payloads, "vectors": vectors,
            "manifest_sha256": manifest_sha, "inputs": input_sha, "outputs": info["outputs"]}


# ───────────────────────── 2. Qdrant 접속 (읽기와 쓰기를 구분한다) ─────────────────────────

class Qdrant:
    def __init__(self, url: str, read_only: bool) -> None:
        self.url = url.rstrip("/")
        self.read_only = read_only
        self.api_key = os.getenv("QDRANT_API_KEY") or None

    def _call(self, method: str, path: str, body: dict | None = None):
        # 읽기 전용일 때는 조회 요청만 통과시킨다. 호출하는 쪽이 실수해도 여기서 막힌다.
        if self.read_only and not (method == "GET" or (method == "POST" and READ_ONLY_POST.fullmatch(path))):
            fail(f"내부 오류: 읽기 전용 실행에서 쓰기 요청을 시도했습니다 ({method} {path}).")
        data = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.load(resp)
                return body.get("result", body)   # 서버 정보(/)처럼 result 로 싸이지 않은 응답도 있다.
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            fail(f"Qdrant 요청 실패 ({method} {path}): HTTP {e.code} {detail}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            fail(f"Qdrant 에 접속하지 못했습니다 ({self.url}): {e}")

    def get(self, path: str):
        return self._call("GET", path)

    def read(self, path: str, body: dict):
        """조회용 POST (count / scroll / query). 데이터를 바꾸지 않는다."""
        return self._call("POST", path, body)

    def write(self, method: str, path: str, body: dict):
        return self._call(method, path, body)   # 읽기 전용이면 _call 에서 막힌다.


def col(name: str, tail: str = "") -> str:
    return f"/collections/{quote(name, safe='')}{tail}"


def match(key: str, value: str) -> dict:
    return {"must": [{"key": key, "match": {"value": value}}]}


def config_problems(info: dict) -> list[str]:
    params = info["config"]["params"]
    vec = params.get("vectors") or {}
    out = []
    if vec.get("size") != DIM or vec.get("distance") != DISTANCE:
        out.append(f"벡터 설정 {vec!r} (기대: 이름 없는 벡터 {DIM} {DISTANCE})")
    if params.get("sparse_vectors"):
        out.append("sparse 벡터가 설정되어 있음")
    if params.get("on_disk_payload") is not True:
        out.append(f"on_disk_payload={params.get('on_disk_payload')!r}")
    return out


def scroll_all(q: Qdrant, name: str, with_payload, with_vector: bool):
    offset = None
    while True:
        body = {"limit": SCROLL_BATCH, "with_payload": with_payload, "with_vector": with_vector}
        if offset is not None:
            body["offset"] = offset
        page = q.read(col(name, "/points/scroll"), body)
        yield from page["points"]
        offset = page.get("next_page_offset")
        if offset is None:
            return


# ───────────────────────── 3. 적재 ─────────────────────────

def check_resume(q: Qdrant, prep: dict) -> None:
    """이미 있는 컬렉션이 "이번 작업이 하다 만 것"인지 확인한다. 아니면 멈춘다."""
    name = prep["collection"]
    problems = config_problems(q.get(col(name)))
    if problems:
        fail(f"--resume 불가: 기존 컬렉션 설정이 다릅니다: {'; '.join(problems)}")
    expected = set(prep["ids"])
    n = foreign = other = 0
    for p in scroll_all(q, name, ["metadata.load_id", "metadata.data_version", "metadata.embedding_config_id"], False):
        n += 1
        meta = (p.get("payload") or {}).get("metadata") or {}
        if p["id"] not in expected:
            foreign += 1
        elif (meta.get("load_id"), meta.get("data_version"), meta.get("embedding_config_id")) != \
                (prep["load_id"], prep["data_version"], prep["embedding_config_id"]):
            other += 1
    if foreign or other:
        fail(f"--resume 불가: 기존 {n:,}개 중 이번 자료에 없는 ID {foreign:,}개, 다른 적재 작업의 것 {other:,}개. "
             "이 스크립트는 삭제하지 않습니다. 컬렉션을 직접 확인하세요.")
    print(f"이어하기 확인: 기존 {n:,}개는 모두 이번 작업(load_id {prep['load_id']})의 것입니다. 전체를 다시 넣습니다.")


def load(q: Qdrant, prep: dict, resume: bool) -> None:
    name = prep["collection"]
    exists = q.get(col(name, "/exists"))["exists"]
    if exists and not resume:
        fail(f"컬렉션 {name} 이 이미 있습니다. 덮어쓰거나 지우지 않고 멈춥니다. "
             "적재된 것을 검사하려면 --verify-only, 도중에 끊긴 적재를 잇려면 --execute --resume 을 쓰세요.")
    if exists:
        check_resume(q, prep)
    else:
        # 3차와 같은 설정: 이름 없는 벡터 1024·Cosine, payload 는 디스크. 나머지는 Qdrant 기본값.
        q.write("PUT", col(name), {"vectors": {"size": DIM, "distance": DISTANCE}, "on_disk_payload": True})
        print(f"컬렉션 생성: {name}")
    for field in INDEX_FIELDS:   # 적재 전에 색인을 만든다. 이미 있으면 그대로 둔다.
        q.write("PUT", col(name, "/index?wait=true"), {"field_name": field, "field_schema": "keyword"})
    print(f"색인 {len(INDEX_FIELDS)}개 준비 완료")

    ids, payloads, vectors = prep["ids"], prep["payloads"], prep["vectors"]
    for start in range(0, len(ids), UPSERT_BATCH):
        end = min(start + UPSERT_BATCH, len(ids))
        points = [{"id": ids[i], "vector": vectors[i].tolist(), "payload": payloads[i]} for i in range(start, end)]
        res = q.write("PUT", col(name, "/points?wait=true"), {"points": points})
        if (res or {}).get("status") != "completed":
            fail(f"{start}~{end}번째 적재가 완료 응답을 받지 못했습니다: {res!r}")
        print(f"  적재 {end:,} / {len(ids):,}")


# ───────────────────────── 4. 적재 후 검증 (읽기 전용) ─────────────────────────

def vector_cosine(db_vector, local: np.ndarray) -> float | None:
    """DB 벡터와 내 파일 벡터의 코사인. 비교할 수 없는 벡터(모양 다름, NaN, 0벡터)는 None."""
    if not isinstance(db_vector, list):
        return None
    try:
        v = np.asarray(db_vector, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if v.shape != (DIM,) or not np.isfinite(v).all():
        return None
    norm = float(np.linalg.norm(v)) * float(np.linalg.norm(local))
    if not np.isfinite(norm) or norm <= 0:
        return None
    cos = float(np.dot(v, local) / norm)
    return cos if np.isfinite(cos) else None


def spread(n: int, count: int) -> list[int]:
    return sorted({round(i * (n - 1) / max(count - 1, 1)) for i in range(min(count, n))})


def verify(q: Qdrant, prep: dict, samples: int) -> None:
    name = prep["collection"]
    ids, payloads, vectors = prep["ids"], prep["payloads"], prep["vectors"]
    metas = [p["metadata"] for p in payloads]
    row_of = {pid: i for i, pid in enumerate(ids)}
    n = len(ids)

    # 적재 직후에는 Qdrant가 내부 정리 중이라 잠깐 yellow 일 수 있다. 오류(red)가 아니므로 기다린다.
    info = q.get(col(name))
    waited = 0
    while info.get("status") == "yellow" and waited < STATUS_WAIT_SEC:
        time.sleep(2)
        waited += 2
        info = q.get(col(name))
    problems = config_problems(info)
    check(not problems, "컬렉션 설정 (1024·Cosine·payload 디스크)", "; ".join(problems))
    status = str(info.get("status"))
    if status == "yellow":
        record("WARN", "컬렉션 상태", f"yellow — {STATUS_WAIT_SEC}초 기다려도 내부 정리 중. 잠시 뒤 --verify-only 로 다시 확인")
    else:
        check(status == "green", "컬렉션 상태", status)

    def count(flt: dict | None) -> int:
        body = {"exact": True}
        if flt:
            body["filter"] = flt
        return q.read(col(name, "/points/count"), body)["count"]

    check(count(None) == n, "전체 개수", f"{count(None):,} / 기대 {n:,}")

    # 전수 대조: ID 집합, 내용(payload) 전체, 벡터 수치
    seen: set[str] = set()
    foreign = bad_payload = bad_vector = 0
    min_cos, worst = 1.0, ""
    for p in scroll_all(q, name, True, True):
        i = row_of.get(p["id"])
        if i is None or p["id"] in seen:
            foreign += 1
            continue
        seen.add(p["id"])
        if p.get("payload") != payloads[i]:
            bad_payload += 1
        cos = vector_cosine(p.get("vector"), vectors[i])
        if cos is None or cos < MIN_COSINE:
            bad_vector += 1
        if cos is None:              # 모양이 다르거나 0벡터·NaN 처럼 비교 자체가 안 되는 벡터
            min_cos, worst = float("-inf"), metas[i]["chunk_id"]
        elif cos < min_cos:
            min_cos, worst = cos, metas[i]["chunk_id"]
    check(foreign == 0 and len(seen) == n, "ID 집합 일치", f"빠진 것 {n - len(seen):,}개, 모르는 것 {foreign:,}개")
    check(bad_payload == 0, "내용(본문+메타데이터) 전수 일치", f"불일치 {bad_payload:,}개")
    check(bad_vector == 0, "벡터 전수 수치 비교 (코사인)",
          f"최소 {min_cos:.6f}" + (f", 기준 미달·비교 불가 {bad_vector:,}개 (예: {worst})" if bad_vector else ""))

    # 색인
    schema = info.get("payload_schema") or {}
    missing = [f for f in INDEX_FIELDS if (schema.get(f) or {}).get("data_type") != "keyword"]
    check(not missing, f"색인 {len(INDEX_FIELDS)}개 (keyword)", "없음: " + ", ".join(missing) if missing else "")

    def has_value(meta: dict, key: str) -> bool:
        return meta.get(key) not in (None, [], "")
    diff = {}
    for f in INDEX_FIELDS:
        want = sum(has_value(m, f.split(".", 1)[1]) for m in metas)
        got = (schema.get(f) or {}).get("points")
        if got != want:
            diff[f] = f"{got} / 기대 {want}"
    record("PASS" if not diff else "WARN", "색인에 잡힌 개수", json.dumps(diff, ensure_ascii=False) if diff else "")

    # 조건별 개수 (정확 계산): 검색 코드가 쓸 조건이 실제로 맞게 걸리는지
    wrong = {}

    def expect(label: str, flt: dict, want: int) -> None:
        got = count(flt)
        if got != want:
            wrong[label] = f"{got} / 기대 {want}"

    for rt in ("policy", "guideline"):
        expect(f"record_type={rt}", match("metadata.record_type", rt), sum(m["record_type"] == rt for m in metas))
    expect("release_status=approved", match("metadata.release_status", "approved"),
           sum(m["release_status"] == "approved" for m in metas))
    expect("data_version", match("metadata.data_version", prep["data_version"]), n)
    expect("지역 미상(빈 키)", {"must": [{"is_empty": {"key": "metadata.applies_to_keys"}}]},
           sum(not m["applies_to_keys"] for m in metas))
    for status in sorted({m.get("scope_status") for m in metas if m.get("scope_status")}):
        expect(f"scope_status={status}", match("metadata.scope_status", status),
               sum(m.get("scope_status") == status for m in metas))
    key_count: dict[str, int] = {}
    for m in metas:
        for k in m["applies_to_keys"]:
            key_count[k] = key_count.get(k, 0) + 1
    for k, want in key_count.items():
        expect(f"지역 키 {k}", match("metadata.applies_to_keys", k), want)
    check(not wrong, f"조건별 개수 (지역 키 {len(key_count):,}종 전부, national 포함)",
          json.dumps(dict(list(wrong.items())[:5]), ensure_ascii=False) if wrong else "")

    # 정책 상세 조회: metadata.policy_id 로 그 정책의 청크가 빠짐없이 나오는지
    by_policy: dict[str, set[str]] = {}
    for pid, m in zip(ids, metas):
        if m["record_type"] == "policy":
            by_policy.setdefault(m["policy_id"], set()).add(pid)
    policy_ids = sorted(by_policy)
    bad = 0
    for j in spread(len(policy_ids), samples):
        page = q.read(col(name, "/points/scroll"), {"filter": match("metadata.policy_id", policy_ids[j]),
                                                    "limit": 100, "with_payload": False, "with_vector": False})
        if {p["id"] for p in page["points"]} != by_policy[policy_ids[j]]:
            bad += 1
    check(bad == 0, "정책 번호로 상세 조회", f"{min(samples, len(policy_ids))}개 정책 중 불일치 {bad}개")

    # 자기 자신 검색: 그 청크의 벡터로 조건을 걸어 찾으면 자기 자신이 최고점으로 나와야 한다.
    bad = 0
    picks = spread(n, samples)
    for i in picks:
        keys = metas[i]["applies_to_keys"]
        flt = match("metadata.applies_to_keys", keys[0]) if keys else match("metadata.record_type", metas[i]["record_type"])
        hits = q.read(col(name, "/points/query"), {"query": vectors[i].tolist(), "filter": flt, "limit": 20,
                                                   "with_payload": False, "params": {"exact": True}})["points"]
        mine = [h for h in hits if h["id"] == ids[i]]
        if not mine or mine[0]["score"] < MIN_COSINE or hits[0]["score"] > mine[0]["score"] + 1e-4:
            bad += 1
    check(bad == 0, "조건 검색에서 자기 자신이 최고점", f"{len(picks)}개 중 실패 {bad}개")


# ───────────────────────── 5. 실행 ─────────────────────────

def print_plan(prep: dict, url: str) -> None:
    metas = [p["metadata"] for p in prep["payloads"]]
    sizes = sorted(len(json.dumps(p, ensure_ascii=False).encode("utf-8")) for p in prep["payloads"])
    keys = {k for m in metas for k in m["applies_to_keys"]}
    print("\n── 적재 계획 ──")
    print(f"대상 서버      : {url}")
    print(f"새 컬렉션      : {prep['collection']}")
    print(f"데이터 버전    : {prep['data_version']}")
    print(f"적재 작업 식별 : load_id {prep['load_id']} (모양 버전 {LOAD_SCHEMA_VERSION}, 임베딩 설정 {prep['embedding_config_id']})")
    print(f"넣을 개수      : {len(metas):,} (정책 {sum(m['record_type'] == 'policy' for m in metas):,}"
          f" + 안내서 {sum(m['record_type'] == 'guideline' for m in metas):,})")
    print(f"지역 키        : 시군구 키 {len(keys) - 1:,}종 + national / 지역 미상 청크 {sum(not m['applies_to_keys'] for m in metas):,}개")
    print(f"한 개의 크기   : 중간 {sizes[len(sizes) // 2]:,}바이트, 최대 {sizes[-1]:,}바이트 (벡터 제외)")
    print(f"벡터 설정      : {DIM}차원 {DISTANCE}, payload 디스크 저장")
    print("색인           : " + ", ".join(f.split(".", 1)[1] for f in INDEX_FIELDS))


def check_report_path(report: Path, vectors_dir: Path, data_dir: Path) -> None:
    """검증 기록이 입력 파일이나 스크립트를 덮어쓰지 못하게 한다."""
    protected = [data_dir / MANIFEST, vectors_dir / INFO, Path(__file__)] \
        + [vectors_dir / n for n in OUTPUT_FILES] + [data_dir / n for _, n in INPUTS]
    protected = {p.resolve() for p in protected}
    tmp = report.with_name(report.name + ".tmp")
    if report.suffix.lower() != ".json":
        fail(f"--report 는 .json 파일이어야 합니다: {report}")
    if report.resolve() in protected or tmp.resolve() in protected:
        fail(f"--report 경로가 입력 파일 또는 스크립트와 같습니다: {report}")
    if report.is_dir() or not report.resolve().parent.is_dir():
        fail(f"--report 를 쓸 폴더가 없거나 경로가 폴더입니다: {report}")
    if tmp.exists():
        fail(f"임시 파일이 이미 있습니다. 확인 후 다른 경로를 쓰세요: {tmp}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="v3 벡터를 Qdrant 새 컬렉션에 적재 (기본은 계획 확인만)")
    ap.add_argument("--vectors-dir", type=Path, required=True, help="vectors.npy, chunk_map.csv, embedding_info.json 이 있는 폴더")
    ap.add_argument("--data-dir", type=Path, required=True, help="청크 파일 2개와 release_manifest.json 이 있는 폴더")
    ap.add_argument("--qdrant-url", default="http://localhost:6333")
    ap.add_argument("--execute", action="store_true", help="실제로 컬렉션을 만들고 적재한다. 없으면 아무것도 쓰지 않는다")
    ap.add_argument("--resume", action="store_true", help="--execute 와 함께. 끊긴 적재를 같은 작업으로 확인한 뒤 전체를 다시 넣는다")
    ap.add_argument("--verify-only", action="store_true", help="적재된 컬렉션을 검증만 한다 (읽기 전용)")
    ap.add_argument("--allow-remote", action="store_true", help="내 PC가 아닌 서버에 접속하는 것을 허용한다")
    ap.add_argument("--samples", type=int, default=40, help="표본 검사(상세 조회·자기 검색)에 쓸 개수")
    ap.add_argument("--report", type=Path, default=None, help="검증 결과를 JSON 으로 남길 경로")
    args = ap.parse_args()

    if args.verify_only and (args.execute or args.resume):
        fail("--verify-only 는 --execute·--resume 과 함께 쓸 수 없습니다.")
    if args.resume and not args.execute:
        fail("--resume 은 --execute 와 함께 써야 합니다.")
    if args.samples < 1:
        fail("--samples 는 1 이상이어야 합니다.")
    host = urlparse(args.qdrant_url).hostname
    if host not in LOCAL_HOSTS and not args.allow_remote:
        fail(f"대상 서버가 내 PC가 아닙니다 ({host}). 의도한 것이면 --allow-remote 를 붙이세요.")

    if args.report:
        check_report_path(args.report, args.vectors_dir, args.data_dir)   # DB 작업 전에 확인한다.

    prep = prepare(args.vectors_dir, args.data_dir)
    print(f"파일 검사 통과: 승인된 {prep['data_version']} 의 청크 {len(prep['ids']):,}개와 벡터가 서로 맞습니다.")
    print_plan(prep, args.qdrant_url)

    q = Qdrant(args.qdrant_url, read_only=not args.execute)
    version = (q.get("/") or {}).get("version")
    exists = q.get(col(prep["collection"], "/exists"))["exists"]
    print(f"Qdrant 버전    : {version}")
    print(f"컬렉션 존재    : {'있음' if exists else '없음'}\n")

    if not args.execute and not args.verify_only:
        print("계획 확인만 했습니다. DB에는 아무것도 쓰지 않았습니다.")
        print("실제로 적재하려면 같은 명령에 --execute 를 붙이세요." if not exists else
              "같은 이름의 컬렉션이 이미 있습니다. 검사는 --verify-only 로 하세요.")
        return
    if args.verify_only and not exists:
        fail(f"검증할 컬렉션 {prep['collection']} 이 없습니다.")

    if args.execute:
        load(q, prep, args.resume)
        q.read_only = True   # 여기부터는 검증이다. 쓰지 않는다.
    print("\n── 적재 후 검증 ──")
    verify(q, prep, args.samples)

    fails = sum(s == "FAIL" for s, _, _ in results)
    warns = sum(s == "WARN" for s, _, _ in results)
    print(f"\n검사 {len(results)}개: FAIL {fails}, WARN {warns}")
    if args.report:
        report = {"collection": prep["collection"], "qdrant_url": args.qdrant_url, "qdrant_version": version,
                  "data_version": prep["data_version"], "load_id": prep["load_id"],
                  "load_schema_version": LOAD_SCHEMA_VERSION, "embedding_config_id": prep["embedding_config_id"],
                  "manifest_sha256": prep["manifest_sha256"], "inputs": prep["inputs"], "outputs": prep["outputs"],
                  "n_points": len(prep["ids"]), "mode": "execute" if args.execute else "verify-only",
                  "script_sha256": sha256_file(Path(__file__)), "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "checks": [{"status": s, "name": nm, "detail": d} for s, nm, d in results], "fail": fails, "warn": warns}
        tmp = args.report.with_name(args.report.name + ".tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, args.report)
        print(f"검증 기록: {args.report}")
    if fails:
        print("결론: 이 컬렉션을 쓰면 안 됩니다. FAIL 항목을 먼저 해결하세요. (스크립트는 컬렉션을 지우지 않습니다)")
        raise SystemExit(1)
    print(f"결론: {prep['collection']} 적재가 정상입니다. 서비스 전환은 하지 않았습니다.")


if __name__ == "__main__":
    main()
