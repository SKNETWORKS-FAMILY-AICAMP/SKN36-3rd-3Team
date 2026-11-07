"""중앙부처 복지서비스 목록 수집기.

사용:
  uv run python scripts/collect_welfare.py --check  # 저장된 목록만 검사 (API 0회)
  uv run python scripts/collect_welfare.py          # 원본 목록 없을 때 신규 수집
  uv run python scripts/collect_welfare.py --overwrite  # 기존 목록 백업 후 재수집

데이터: 프로젝트/data/raw/welfare/welfare_list.json 및 welfare_list.csv
기존 파일은 --overwrite 없이 덮어쓰지 않습니다.
"""

import argparse
import csv
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

from _welfare_api import (
    DATA_DIR,
    LIST_URL,
    WelfareAPIError,
    load_api_key,
    load_services,
    safe_get_xml,
)


def atomic_write(path: Path, data: bytes) -> None:
    """임시 파일에 먼저 기록 후 교체하여 중간 실패에 대비."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="복지서비스 목록 조회 / 검증")
    parser.add_argument("--check", action="store_true", help="기존 JSON 확인 (API 호출 0회)")
    parser.add_argument("--overwrite", action="store_true", help="기존 목록 파일 백업 후 재수집")
    parser.add_argument("--max-pages", type=int, default=100, help="안전장치: 최대 목록 페이지 (기본 100)")
    args = parser.parse_args()
    if args.check:
        rows = load_services()
        print(f"목록 검사 성공: {len(rows)}건, 중복 ID 없음, API 호출 0회")
        return
    if args.max_pages < 1:
        raise WelfareAPIError("--max-pages는 1 이상이어야 합니다.")

    json_path = DATA_DIR / "welfare_list.json"
    csv_path = DATA_DIR / "welfare_list.csv"
    if (json_path.exists() or csv_path.exists()) and not args.overwrite:
        raise WelfareAPIError(
            "기존 welfare_list.json/csv가 있습니다. 기존 원본을 보호하기 위해 중단했습니다. "
            "데이터 검사는 --check, 재수집은 --overwrite를 사용하세요."
        )

    key = load_api_key()
    rows = []
    count = None
    page = 1
    with requests.Session() as session:
        while page <= args.max_pages:
            _, root = safe_get_xml(
                session,
                LIST_URL,
                {
                    "serviceKey": key,
                    "callTp": "L",
                    "pageNo": page,
                    "numOfRows": 100,
                    "srchKeyCode": "001",
                },
            )
            try:
                total_count = int(root.findtext(".//totalCount", ""))
            except (TypeError, ValueError):
                raise WelfareAPIError("응답에서 totalCount 값을 확인할 수 없습니다.") from None
            if total_count < 1:
                raise WelfareAPIError("API 목록 건수가 0입니다. 빈 데이터로 덮어쓰지 않습니다.")
            if count is None:
                count = total_count
            elif total_count != count:
                raise WelfareAPIError("조회 도중 전체 서비스 건수가 바뀌었습니다. 재수집을 검토하세요.")

            services = root.findall(".//servList")
            if not services:
                raise WelfareAPIError("예상보다 일찍 빈 페이지가 반환됐습니다. 저장을 중단합니다.")
            rows.extend({child.tag: child.text for child in service} for service in services)
            print(f"목록 {page}페이지 수집: {len(rows)}/{count}건")
            if len(rows) >= count:
                break
            page += 1
            time.sleep(0.5)
        else:
            raise WelfareAPIError("--max-pages 제한에 도달하여 저장하지 않았습니다.")

    ids = [str(item.get("servId") or "").strip() for item in rows]
    if len(rows) != count or not all(ids) or len(set(ids)) != len(ids):
        raise WelfareAPIError("수집 건수/servId 중복 검증 실패. 기존 원본을 수정하지 않습니다.")

    fields = list(dict.fromkeys(key for item in rows for key in item))
    from io import StringIO
    sio = StringIO(newline="")
    writer = csv.DictWriter(sio, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = sio.getvalue().encode("utf-8-sig")
    json_bytes = (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.overwrite:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for path in (json_path, csv_path):
            if path.exists():
                backup = path.with_name(f"{path.name}.backup_{stamp}")
                if backup.exists():
                    raise WelfareAPIError("백업 경로가 이미 있어 파일을 보존하기 위해 중단합니다.")
                backup.write_bytes(path.read_bytes())
                print("기존 데이터 백업:", backup)

    atomic_write(json_path, json_bytes)
    atomic_write(csv_path, csv_bytes)
    print(f"완료: 목록 {len(rows)}건")
    print("JSON 저장:", json_path)
    print("CSV 저장:", csv_path)


if __name__ == "__main__":
    try:
        main()
    except WelfareAPIError as exc:
        raise SystemExit(str(exc)) from None
