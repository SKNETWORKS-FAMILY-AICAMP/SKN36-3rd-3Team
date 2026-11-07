"""Inspect generated pre-splitting data without printing secrets or making external calls."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = p.parse_args()
    root=args.root.resolve()
    report=root / "data/validation/quality_report.json"
    if not report.exists():
        raise SystemExit("품질 보고서가 없습니다: prepare_pre_splitting.py를 먼저 실행하세요")
    r=json.loads(report.read_text(encoding="utf-8"))
    for k in ("policy_count", "central_list_count", "central_valid_xml", "central_missing_xml", "local_input_found", "facilities_input_found", "facility_count", "unique_policy_ids", "duplicate_policy_id_count", "source_issue_count"):
        print(f"{k}: {r.get(k)}")
    print("pdf:", r.get("pdf",{}))
    if r["unique_policy_ids"] != r["policy_count"]:
        raise SystemExit("정책 ID 중복: 수동 검토 필요")
    print("상태: RAG Splitting 이전 자료 준비 (PDF·지역·정책 연결 검수 상태는 따로 확인)")

if __name__ == "__main__":
    main()
