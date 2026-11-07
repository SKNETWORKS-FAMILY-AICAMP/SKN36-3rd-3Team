"""중앙부처 복지서비스 상세 XML 수집기 (기존 원본 보존 / 이어받기).

사용:
  uv run python scripts/collect_welfare_details.py --check      # API 0회
  uv run python scripts/collect_welfare_details.py --max-calls 5 # 처음에는 5건 이하로 시험
  uv run python scripts/collect_welfare_details.py               # 호출 상한 기본 95회

데이터 위치: 프로젝트/data/raw/welfare/details/WLF*.xml
기존 정상·비정상 XML을 모두 덮어쓰지 않습니다. 비정상 파일은 점검 후 수동 처리.
"""

import argparse
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from _welfare_api import (
    DATA_DIR,
    DETAIL_URL,
    WelfareAPIError,
    load_api_key,
    load_services,
    safe_get_xml,
    validate_detail_xml,
)

DETAIL_DIR = DATA_DIR / "details"
LOG_DIR = DATA_DIR / "collection_logs"
DEFAULT_MAX_CALLS = 95
WAIT_SECONDS = 2.0


def check_existing(services: list[dict]) -> tuple[int, list[str]]:
    valid, invalid = 0, []
    for item in services:
        sid = str(item["servId"])
        path = DETAIL_DIR / f"{sid}.xml"
        if not path.exists():
            continue
        try:
            validate_detail_xml(path.read_bytes(), sid)
            valid += 1
        except (ValueError, OSError) as exc:
            invalid.append(sid)
    return valid, invalid


def store_xml_safely(path: Path, content: bytes) -> None:
    """기존 파일이 있으면 결코 덮어쓰지 않고 새로운 파일만 기록."""
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_bytes(content)
        # 파일이 이미 있는 경우, 경고 후 기존 원본을 그대로 보존한다.
        if path.exists():
            raise WelfareAPIError("저장할 위치에 기존 XML이 존재하여 덮어쓰기를 중단했습니다.")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="중앙부처 상세 XML 안전 이어받기")
    parser.add_argument("--check", action="store_true", help="API 호출 없이 기존 XML 점검")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                        help=f"한 번 실행할 최대 상세 API 호출 횟수 (기본 {DEFAULT_MAX_CALLS})")
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 100:
        raise WelfareAPIError("--max-calls는 1~100만 입력할 수 있습니다.")

    services = load_services()
    valid, invalid = check_existing(services)
    print(f"목록 {len(services)}건 / 정상 상세 XML {valid}건 / 비정상 XML {len(invalid)}건 / 미확보 {len(services)-valid}건")
    if invalid:
        print("검증 실패한 기존 파일 ID (원본 보존):", ", ".join(invalid[:15]))
        if len(invalid) > 15:
            print(f"... 외 {len(invalid)-15}건")
    if args.check:
        print("--check 완료: API 호출 0회, 원본 변경 없음")
        return

    key = load_api_key()
    calls, successful, skipped_invalid = 0, 0, 0
    issues = []
    started_at = datetime.now(timezone.utc)
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"이번 실행 호출 상한: {args.max_calls}회 (당일 타 스크립트 사용량은 별도 확인 필요)")
    try:
        with requests.Session() as session:
            for idx, item in enumerate(services, 1):
                sid = str(item["servId"])
                path = DETAIL_DIR / f"{sid}.xml"
                if path.exists():
                    try:
                        validate_detail_xml(path.read_bytes(), sid)
                    except (ValueError, OSError) as exc:
                        skipped_invalid += 1
                        issues.append({"servId": sid, "reason": "invalid_existing_xml", "detail": type(exc).__name__})
                    continue
                if calls >= args.max_calls:
                    print("호출 상한에 도달하여 안전하게 중단")
                    break

                calls += 1
                try:
                    raw, _ = safe_get_xml(
                        session, DETAIL_URL,
                        {"serviceKey": key, "callTp": "D", "servId": sid},
                    )
                    validate_detail_xml(raw, sid)
                    store_xml_safely(path, raw)
                    successful += 1
                    print(f"[{idx}/{len(services)}] 상세 저장: {sid} (이번 실행 {calls}회 호출)")
                    time.sleep(WAIT_SECONDS)
                except (WelfareAPIError, ValueError) as exc:
                    # 실패 사유는 서비스 ID와 안전한 유형만 기록. 키·요청 URL은 저장하지 않음.
                    reason = str(exc) if isinstance(exc, WelfareAPIError) else type(exc).__name__
                    issues.append({"servId": sid, "reason": reason})
                    print(f"[{idx}/{len(services)}] 수집 중단: {sid} / {reason}")
                    break
    except KeyboardInterrupt:
        print("사용자 중단: 수집 완료된 XML은 그대로 유지합니다.")
    finally:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = started_at.strftime("%Y%m%d_%H%M%S_%f")
        log_path = LOG_DIR / f"detail_run_{stamp}.json"
        log_path.write_text(
            json.dumps({
                "time_utc": started_at.isoformat(),
                "requests_this_run": calls,
                "new_files": successful,
                "invalid_existing_skipped": skipped_invalid,
                "issues": issues,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"이번 실행 신규 XML: {successful}건 / 요청: {calls}회 / 로그: {log_path}")


if __name__ == "__main__":
    try:
        main()
    except WelfareAPIError as exc:
        raise SystemExit(str(exc)) from None
