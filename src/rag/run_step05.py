"""Build local welfare RAG documents from latest STEP4 selected JSONL.

Usage (project root):
    uv run python src/rag/run_step05.py
    uv run python src/rag/run_step05.py --input data/.../policies_elderly_selected.jsonl
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import tempfile
import sys

# Allow `python src/rag/run_step05.py` from the project root.
_src_dir = Path(__file__).resolve().parents[1]
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from rag.document_builder import build_policy_documents
from rag.document_validator import validate_documents


def find_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / "data").is_dir() and (p / "src").is_dir():
            return p
    # Running from standalone package: caller must provide input/output or place in project.
    return Path.cwd().resolve()


def find_latest_input(root: Path) -> Path:
    base = root / "data" / "processed" / "local_welfare" / "elderly_filtered"
    options = list(base.glob("run_*/policies_elderly_selected.jsonl"))
    if not options:
        raise FileNotFoundError(
            f"No STEP4 file found under {base}. Supply --input explicitly."
        )
    # Timestamp is embedded in the run directory name (works across copies).
    return max(options, key=lambda p: p.parent.name)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8-sig") as f:
        for lineno, line in enumerate(f, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"Line {lineno}: policy must be an object")
                rows.append(row)
    return rows


def save_jsonl_atomic(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def run(input_path: Path, output_path: Path) -> dict:
    originals = load_jsonl(input_path)
    documents = build_policy_documents(originals)
    report = validate_documents(documents)
    if len(documents) != len(originals):
        raise RuntimeError("Input/output row count mismatch")
    save_jsonl_atomic(output_path, documents)
    return {"input": str(input_path), "output": str(output_path), **report}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create STEP5 pre-chunk policy documents")
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = find_root()
    inp = args.input or find_latest_input(root)
    out = args.output or (root / "data" / "rag" / "documents" / "policy_documents.jsonl")
    print(json.dumps(run(inp, out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
