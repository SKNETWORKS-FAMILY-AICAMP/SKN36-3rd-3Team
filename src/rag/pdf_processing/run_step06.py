"""Run STEP 6-1 (validate) and STEP 6-2 (build guideline RAG documents).

From project root, with PYTHONPATH=src:
    python -m rag.pdf_processing.run_step06
    python -m rag.pdf_processing.run_step06 --input data/preprocessed/guideline_sections_filtered.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .guideline_document_builder import build_guideline_documents
from .guideline_metadata_builder import source_document_records
from .section_validator import validate_sections, write_jsonl


def discover_input(root: Path) -> Path:
    candidates = [
        root / "data" / "preprocessed" / "guideline_sections_filtered.jsonl",
        root / "data" / "processed" / "guideline_sections_filtered.jsonl",
        root / "data" / "preprocessed" / "pdf" / "guideline_sections_filtered.jsonl",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError("Cannot find guideline_sections_filtered.jsonl. Pass --input <path>.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, help="Existing filtered section JSONL (does not re-extract PDF)")
    ap.add_argument("--output-dir", type=Path, default=Path("data/rag/documents"))
    ap.add_argument("--report-dir", type=Path, default=Path("data/rag/reports"))
    ap.add_argument("--image-root", type=Path, default=None, help="Root with images/ extracted from images.zip; optional")
    ap.add_argument("--allow-errors", action="store_true", help="Write only valid records despite invalid input rows")
    args = ap.parse_args()
    input_path = args.input or discover_input(Path.cwd())
    if not input_path.is_file():
        ap.error(f"Input not found: {input_path}")
    normalized, report = validate_sections(input_path, args.image_root)
    if report["errors_count"] and not args.allow_errors:
        args.report_dir.mkdir(parents=True, exist_ok=True)
        report_path = args.report_dir / "step06_validation_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"Validation failed ({report['errors_count']} errors). See {report_path}")
    documents = build_guideline_documents(normalized)
    if any(not d["text"].strip() for d in documents):
        raise SystemExit("Document generation produced an empty text")
    write_jsonl(args.output_dir / "guideline_sections_normalized.jsonl", normalized)
    write_jsonl(args.output_dir / "guideline_documents.jsonl", documents)
    write_jsonl(args.output_dir / "source_documents.jsonl", source_document_records())
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report["documents_created"] = len(documents)
    report["output_dir"] = str(args.output_dir)
    report_path = args.report_dir / "step06_validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"input": str(input_path), "sections": len(normalized),
                      "documents": len(documents), "errors": report["errors_count"],
                      "warnings": report["warnings_count"], "output_dir": str(args.output_dir),
                      "report": str(report_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
