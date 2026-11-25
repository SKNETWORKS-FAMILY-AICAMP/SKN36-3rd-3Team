"""Check configured MOHW welfare guides and related notices."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
from time import sleep
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup
import pymupdf
import requests


ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9), "KST")
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
SECTION_HEADING = re.compile(r"^(?:[Ⅰ-Ⅻ][.．]\s*|\d{1,2}[.．]\s*|\d{1,2}\s+|[가-하]\.\s*|[□■]\s*)[가-힣]")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class CheckError(Exception):
    def __init__(
        self, stage: str, kind: str, url: str, message: str, *, status=None, attempts=None
    ) -> None:
        super().__init__(message)
        self.details = {
            "stage": stage, "type": kind, "url": url, "message": message,
            "http_status": status, "attempts": attempts,
        }


@dataclass(frozen=True)
class ListedPost:
    post_id: str
    url: str
    title: str
    day: date

    @property
    def key(self) -> tuple[str, str]:
        return board_id_from_url(self.url), self.post_id


@dataclass(frozen=True)
class Attachment:
    name: str
    url: str
    size_label: str | None = None


class Board:
    def __init__(self, session: requests.Session) -> None:
        self.session = session

    def get(self, url: str, stage: str, *, params=None) -> bytes:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in {"www.mohw.go.kr", "mohw.go.kr"}:
            raise CheckError(stage, "unexpected_url", url, "보건복지부 HTTPS 주소를 확인하세요.")
        for attempt in (1, 2):
            delay = 2
            status = None
            try:
                with self.session.get(
                    url, params=params, timeout=(10, 30), allow_redirects=False
                ) as response:
                    if response.ok and response.status_code == 200:
                        return response.content
                    status = response.status_code
                    can_retry = status in RETRYABLE_STATUS
                    kind, message = "http_error", f"HTTP {status}"
                    if response.headers.get("Retry-After"):
                        retry_after = response.headers["Retry-After"]
                        can_retry = can_retry and retry_after.isdigit() and int(retry_after) <= 30
                        if can_retry:
                            delay = max(delay, int(retry_after))
            except requests.Timeout as exc:
                can_retry = True
                kind, message = "timeout", type(exc).__name__
            except requests.ConnectionError as exc:
                can_retry = not isinstance(
                    exc, (requests.exceptions.SSLError, requests.exceptions.ProxyError)
                )
                kind, message = "connection_error", type(exc).__name__
            except requests.RequestException as exc:
                can_retry = False
                kind, message = "request_error", type(exc).__name__
            if attempt == 2 or not can_retry:
                raise CheckError(stage, kind, url, message, status=status, attempts=attempt)
            sleep(delay)
        raise AssertionError("unreachable")

    def search(self, url: str, term: str, earliest: date) -> list[ListedPost]:
        page = 1
        results: dict[tuple[str, str], ListedPost] = {}
        previous_day = date.max
        expected_total = None
        while True:
            query = {"keyField": "TITLE", "keyWord": term, "nPage": page}
            html = BeautifulSoup(self.get(url, "board_list", params=query), "html.parser")
            info = html.select_one(".board_info")
            table = html.select_one("table.tstyle_list")
            page_info = re.search(
                r"(전체|총\s*게시물)\s*([\d,]+)\s*(?:건\s*)?페이지\s*(\d+)\s*/\s*(\d+)",
                info.get_text(" ", strip=True) if info else "",
            )
            if table is None or not page_info or int(page_info[3]) != page:
                raise CheckError("board_list", "invalid_list", url, f"{term!r} {page}페이지 목록 확인 실패")
            rows = table.select('tbody tr:has(td[data-label="제목"])')
            total = int(page_info[2].replace(",", ""))
            if page == 1 and not rows and total == 0 and "해당 내용이 없습니다" in table.get_text():
                return []
            if expected_total is None:
                expected_total = total
            page_size = 10 if page_info[1] == "전체" else 15
            page_count = (total + page_size - 1) // page_size
            expected_rows = min(page_size, total - (page - 1) * page_size)
            if total != expected_total or page_count != int(page_info[4]) or not rows or len(rows) != expected_rows:
                raise CheckError("board_list", "incomplete_list", url, f"{term!r} {page}페이지 항목 수가 맞지 않습니다.")
            for row in rows:
                anchor = row.select_one('td[data-label="제목"] a[href]')
                date_cell = row.select_one('td[data-label="등록일"]')
                try:
                    if anchor is None or date_cell is None:
                        raise ValueError("missing title or date")
                    post_url = urljoin(url, anchor["href"])
                    post_id = post_id_from_url(post_url)
                    published = date.fromisoformat(date_cell.get_text(strip=True))
                except ValueError as exc:
                    raise CheckError("board_list", "invalid_row", url, f"{term!r} {page}페이지 게시물 정보 오류") from exc
                post = ListedPost(post_id, post_url, anchor.get_text(" ", strip=True), published)
                if post.key in results:
                    raise CheckError("board_list", "repeated_post", url, f"{term!r} 중복 게시물 {post_id}")
                if published > previous_day:
                    raise CheckError("board_list", "unexpected_order", url, f"{term!r} 등록일 정렬을 확인할 수 없습니다.")
                results[post.key] = post
                previous_day = published
            if page >= page_count or previous_day < earliest:
                return list(results.values())
            page += 1

    def details(self, url: str) -> tuple[datetime, list[Attachment]]:
        html = BeautifulSoup(self.get(url, "post_detail"), "html.parser")
        date_field = html.select_one("li.date span")
        try:
            date_text = date_field.get_text(" ", strip=True) if date_field else ""
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?", date_text):
                raise ValueError
            published = parse_time(date_text)
        except ValueError as exc:
            raise CheckError("post_detail", "invalid_post", url, "게시 시각을 읽지 못했습니다.") from exc
        attachments = []
        for link in html.select("a[href*='boardDownload.es']"):
            item = link.find_parent("li")
            if item is None:
                continue
            label = re.match(
                r"^(.+?\.pdf)(?:\s*\(\s*([\d.,]+\s*[KMG]?B)\s*/|\s|\(|$)",
                item.get_text(" ", strip=True), re.IGNORECASE,
            )
            if label:
                attachments.append(Attachment(label[1], urljoin(url, link["href"]), label[2]))
        return published, attachments

    def pdf(self, attachment: Attachment) -> bytes:
        content = self.get(attachment.url, "pdf_download")
        try:
            if not content.startswith(b"%PDF-"):
                raise ValueError("PDF signature missing")
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                if pdf.needs_pass or len(pdf) == 0:
                    raise ValueError("empty or locked PDF")
        except (ValueError, RuntimeError) as exc:
            raise CheckError("pdf_download", "invalid_pdf", attachment.url, "정상적인 PDF로 열 수 없습니다.") from exc
        return content


def post_id_from_url(url: str) -> str:
    params = parse_qs(urlsplit(url).query)
    post_id = params.get("list_no", [""])[0]
    if not post_id.isascii() or not post_id.isdigit():
        raise ValueError("게시물 번호가 없는 URL입니다.")
    return post_id


def board_id_from_url(url: str) -> str:
    params = parse_qs(urlsplit(url).query)
    return params.get("bid", params.get("mid", [""]))[0]


def names_volume(text: str, volume: int) -> bool:
    roman = {1: "I", 2: "II"}[volume]
    pattern = rf"(?<!\d){volume}(?:권|책)|\((?:{volume}|{roman})\)|\[(?:{volume}|{roman})\]"
    return bool(re.search(pattern, compact(text), re.IGNORECASE))


def guide_attachment(document: dict, attachments: list[Attachment], post: ListedPost) -> Attachment:
    volume = document.get("volume")
    choices = [item for item in attachments if not any(
        compact(term) in compact(item.name) for term in document.get("exclude_attachment_terms", [])
    )]
    if volume:
        numbered = [item for item in choices if names_volume(item.name, volume)]
        explicit_title = names_volume(post.title, volume)
        if numbered or not explicit_title or len(choices) != 1 or any(
            names_volume(item.name, 3 - volume) for item in choices
        ):
            choices = numbered
    for term in document.get("preferred_attachment_terms", []):
        preferred = [item for item in choices if compact(term) in compact(item.name)]
        if len(choices) > 1 and preferred:
            choices = preferred
    if len(choices) != 1:
        raise CheckError(
            "post_detail", "ambiguous_pdf", post.url,
            f"{document.get('label', document['document_id'])} PDF를 하나로 식별할 수 없습니다.",
        )
    return choices[0]


def post_kind(title: str, source: dict) -> str | None:
    normalized = compact(title)
    canonical = compact(source["title"]) in normalized
    related_title = any(compact(term) in normalized for term in source.get("related_title_terms", []))
    shorter_title = any(compact(term) in normalized for term in source.get("title_aliases", []))
    if "[고시]" in normalized:
        notice_term = "기초연금" if source["source_id"] == "basic_pension" else compact(source["title"])
        if notice_term in normalized or shorter_title:
            return "notice"
    if (canonical or related_title or shorter_title) and any(
        term in normalized for term in ("정오표", "오탈자", "정정")
    ):
        return "erratum"
    if canonical:
        if any(term in normalized for term in ("활용안내", "설명서", "발간안내")):
            return "related_guide"
        return "guide"
    if related_title or (shorter_title and any(term in normalized for term in ("개정", "수정"))):
        return "related_guide"
    return None


def extract_pages(content: bytes) -> tuple[list[str], list[str | None], list[int]]:
    texts, headings, unreadable = [], [], []
    with pymupdf.open(stream=content, filetype="pdf") as pdf:
        for page in pdf:
            lines = []
            for block in page.get_text("blocks", sort=True):
                if block[6] != 0:
                    continue
                text = block[4].strip()
                in_margins = block[3] <= 36 or block[1] >= page.rect.height - 36
                if in_margins and re.fullmatch(r"[\s·\-\d|]+", text):
                    continue
                lines.extend(line.strip() for line in text.splitlines() if line.strip())
            joined = compact("".join(lines))
            if not joined:
                unreadable.append(page.number + 1)
            texts.append(joined)
            headings.append(next((
                line for line in lines
                if len(line) <= 100
                and (SECTION_HEADING.match(line) or line.startswith("주요 개정 사항"))
            ), None))
    return texts, headings, unreadable


def compare_pdfs(before: bytes, after: bytes) -> dict:
    old, old_titles, old_unreadable = extract_pages(before)
    new, new_titles, new_unreadable = extract_pages(after)
    changes = []
    matcher = SequenceMatcher(a=old, b=new, autojunk=False)
    for kind, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if kind == "equal":
            continue
        titles = new_titles[new_start:new_end] + old_titles[old_start:old_end]
        changes.append({
            "section_title": next((heading for heading in titles if heading), None),
            "change_type": {"insert": "added", "delete": "removed", "replace": "modified"}[kind],
            "old_pdf_pages": list(range(old_start + 1, old_end + 1)),
            "new_pdf_pages": list(range(new_start + 1, new_end + 1)),
        })
    return {
        "method": "page_text_alignment",
        "old_page_count": len(old),
        "new_page_count": len(new),
        "changed_sections": changes,
        "old_pages_without_text": old_unreadable,
        "new_pages_without_text": new_unreadable,
        "review_required": True,
    }


def notice_details(content: bytes, source_id: str) -> dict:
    with pymupdf.open(stream=content, filetype="pdf") as pdf:
        text = compact("".join(page.get_text() for page in pdf))
    match = re.search(r"(20\d{2})년(\d{1,2})월(\d{1,2})일부터시행", text)
    effective = date(*(int(part) for part in match.groups())).isoformat() if match else None
    article = re.search(r"(제\d+조(?:의\d+)?)\([^()]{4,60}\)", text)
    review = "공식 개정 내용과 현행 챗봇 답변 대조"
    if source_id == "basic_pension" and "수급희망이력관리" in text and "수급가능성" in text:
        review = "기초연금 수급희망 이력관리와 신청 안내 관련 답변 확인"
    return {
        "effective_date": effective,
        "article_hint": article[1] if article else None,
        "review_reason": review,
    }

@dataclass
class TrackedDocument:
    config: dict
    state: dict
    content: bytes
    digest: str
    post_url: str
    post_id: str
    published: datetime | None = None

    @property
    def id(self) -> str:
        return self.config["document_id"]


def check_source(
    board: Board, source: dict, state: dict, cutoff: datetime, work: Path, run_key: str,
    *, historical: bool,
) -> dict:
    source_id = source["source_id"]
    source_state = next((item for item in state["sources"] if item["source_id"] == source_id), None)
    if source_state is None:
        source_state = {"source_id": source_id, "last_success_at": None, "documents": []}
        state["sources"].append(source_state)
    previous = {item["document_id"]: item for item in source_state["documents"]}
    last_success = parse_time(source_state["last_success_at"]) if source_state["last_success_at"] else None
    checked_attachments = source_state.setdefault("checked_attachments", {})
    known = set(state["known_candidate_ids"])
    result = {
        "source_id": source_id, "title": source["title"], "window_start": None,
        "window_end": cutoff.isoformat(), "checked_post_ids": [], "checked_posts": [], "attachments": [],
        "errors": [], "candidates": [], "related_notices": [],
    }
    document_ids = [item["document_id"] for item in source["documents"]]
    post_details: dict[tuple[str, str], tuple[datetime, list[Attachment]]] = {}

    def add_error(error: CheckError, scope: str, post_id=None, document_id=None) -> None:
        result["errors"].append({"scope": scope, "post_id": post_id, "document_id": document_id, **error.details})

    def get_details(post: ListedPost) -> tuple[datetime, list[Attachment]]:
        if post.key not in post_details:
            post_details[post.key] = board.details(post.url)
        return post_details[post.key]

    def record_checked(post: ListedPost) -> None:
        entry = {"board_id": post.key[0], "post_id": post.post_id}
        if entry not in result["checked_posts"]:
            result["checked_posts"].append(entry)
        if post.post_id not in result["checked_post_ids"]:
            result["checked_post_ids"].append(post.post_id)

    def store_pdf(post_id: str, digest: str, content: bytes) -> str:
        relative = Path("downloads") / run_key / f"{post_id}-{digest[:12]}.pdf"
        path = work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return relative.as_posix()

    def fingerprint(attachment: Attachment, kind: str, baseline_hash=None) -> dict:
        return {
            "kind": kind, "url": attachment.url, "name": attachment.name,
            "size_label": attachment.size_label, "baseline_sha256": baseline_hash,
        }

    def cached_attachment(key: str, legacy_key: str, current: dict) -> dict | None:
        cached = checked_attachments.get(key)
        if cached is not None:
            return cached if cached["fingerprint"] == current else None
        legacy = checked_attachments.get(legacy_key)
        if legacy is not None and legacy["fingerprint"] == current:
            checked_attachments[key] = checked_attachments.pop(legacy_key)
            return legacy
        return None

    def record_candidate(candidate: dict, group: str, *, downloaded: bool) -> None:
        report_entry = {"source_id": source_id, **candidate}
        candidate_id = candidate["candidate_id"]
        report_entry.update(is_new=candidate_id not in known, downloaded_this_run=downloaded)
        for key in ("download_path", "comparison_path"):
            if report_entry.get(key) and not (work / report_entry[key]).is_file():
                report_entry.pop(key)
        result[group].append(report_entry)
        known.add(candidate_id)

    def check_guide(
        document: TrackedDocument, post: ListedPost, published: datetime, attachment: Attachment,
    ) -> None:
        original = post.key == (board_id_from_url(document.post_url), document.post_id)
        current = fingerprint(attachment, "guide", document.digest)
        legacy_key = post.post_id if len(document_ids) == 1 else f"{post.post_id}:{document.id}"
        cache_key = f"{post.key[0]}:{post.post_id}:guide:{document.id}"
        cached = cached_attachment(cache_key, legacy_key, current)
        reused = cached is not None
        if reused:
            digest = cached["sha256"]
            comparison = cached["comparison"]
        else:
            content = board.pdf(attachment)
            digest = sha256(content).hexdigest()
            comparison = None

        if historical and original and digest != document.digest and not document.config.get("baseline_is_local_variant"):
            raise CheckError(
                "pdf_download", "historical_attachment_unverified", attachment.url,
                "확인한 기준판 첨부의 해시가 다릅니다. 테스트 종료 시각 당시의 첨부를 확인할 수 없습니다.",
            )

        version = {
            "document_id": document.id, "board_id": post.key[0], "post_id": post.post_id, "post_url": post.url,
            "published_at": published.isoformat(), "attachment_url": attachment.url, "sha256": digest,
        }
        result["attachments"].append({
            **version, "previous_sha256": document.digest, "observed_sha256": digest,
            "status": "unchanged" if digest == document.digest else "differs_from_baseline",
            "downloaded_this_run": not reused,
        })
        if not reused:
            if digest != document.digest:
                try:
                    comparison = compare_pdfs(document.content, content)
                except (ValueError, RuntimeError) as exc:
                    raise CheckError(
                        "pdf_compare", "text_extraction_failed", attachment.url,
                        "신구 PDF의 텍스트를 비교하지 못했습니다.",
                    ) from exc
                pair = sha256(f"{document.digest}:{digest}".encode()).hexdigest()[:24]
                relative = Path("comparisons") / f"{document.id}-{pair}" / "comparison.json"
                comparison.update(baseline_sha256=document.digest, candidate_sha256=digest)
                write_json(work / relative, comparison)
                comparison.update(
                    download_path=store_pdf(post.post_id, digest, content),
                    comparison_path=relative.as_posix(),
                )
            checked_attachments[cache_key] = {
                "fingerprint": current, "sha256": digest, "comparison": comparison,
            }
        if comparison is None:
            return
        if original and document.config.get("baseline_is_local_variant"):
            change_type = "baseline_attachment_differs"
        else:
            change_type = "attachment_replaced" if original else "revised_guide"
        record_candidate({
            **version, **comparison, "candidate_id": f"{document.id}-{digest}",
            "change_type": change_type, "baseline_sha256": document.digest,
        }, "candidates", downloaded=not reused)
        observed = document.state.get("latest_observed_version")
        if not observed or published >= parse_time(observed["published_at"]):
            document.state["latest_observed_version"] = version

    def check_related(post: ListedPost, published: datetime, attachments: list[Attachment], kind: str) -> None:
        candidate = {
            "document_id": document_ids[0] if len(document_ids) == 1 else None,
            "document_ids": document_ids, "board_id": post.key[0], "post_id": post.post_id, "title": post.title,
            "post_url": post.url, "published_at": published.isoformat(),
            "attachment_url": None, "sha256": None,
            "change_type": "related_notice" if kind == "notice" else kind,
            "review_required": True, "review_reason": "공식 게시물과 현행 챗봇 답변 대조",
        }
        checked_files = []
        failed = False
        legacy_record = checked_attachments.get(post.post_id)
        legacy_match = False
        for attachment in attachments:
            current = fingerprint(attachment, kind)
            cache_key = f"{post.key[0]}:{post.post_id}:{kind}:{attachment.url}"
            cached = cached_attachment(cache_key, post.post_id, current)
            if cached is not None:
                details = cached["details"]
                legacy_match = legacy_match or (cached is legacy_record)
            else:
                try:
                    content = board.pdf(attachment)
                except CheckError as exc:
                    add_error(exc, kind, post.post_id)
                    failed = True
                    continue
                digest = sha256(content).hexdigest()
                details = {"attachment_url": attachment.url, "sha256": digest}
                if kind == "notice":
                    try:
                        details.update(notice_details(content, source_id))
                    except (ValueError, RuntimeError) as exc:
                        message = f"고시 개정 내용을 추출하지 못했습니다. ({type(exc).__name__})"
                        add_error(CheckError("notice_review", "text_extraction_failed", attachment.url, message), kind, post.post_id)
                        failed = True
                        continue
                details["download_path"] = store_pdf(post.post_id, digest, content)
                checked_attachments[cache_key] = {"fingerprint": current, "details": details}
            checked_file = {
                **details, "attachment_name": attachment.name, "size_label": attachment.size_label,
                "downloaded_this_run": cached is None,
            }
            if checked_file.get("download_path") and not (work / checked_file["download_path"]).is_file():
                checked_file.pop("download_path")
            checked_files.append(checked_file)
        if failed:
            return
        if checked_files:
            primary = next((item for item in checked_files if "개정안" in compact(item["attachment_name"])), checked_files[0])
            candidate.update(primary)
        candidate["attachments"] = checked_files
        prefix = kind if source_id == "basic_pension" else f"{source_id}-{kind}"
        signatures = sorted(item["sha256"] for item in checked_files)
        digest = candidate["sha256"] or "post"
        if len(signatures) > 1:
            digest = sha256("\n".join(signatures).encode()).hexdigest()
        candidate["candidate_id"] = f"{prefix}-{post.key[0]}-{post.post_id}-{digest}"
        if len(signatures) == 1 and legacy_match and f"{prefix}-{post.post_id}-{digest}" in known:
            known.add(candidate["candidate_id"])
        group = "candidates" if kind == "erratum" else "related_notices"
        record_candidate(candidate, group, downloaded=any(item["downloaded_this_run"] for item in checked_files))

    def check_baseline(config: dict) -> TrackedDocument | None:
        document_id = config["document_id"]
        saved = previous.get(document_id)
        if saved is None:
            saved = {"document_id": document_id, "applied_version": {}, "latest_observed_version": None}
            source_state["documents"].append(saved)
        applied = saved["applied_version"]
        url = applied.get("post_url") or config["baseline_post_url"]
        path = ROOT / config["baseline_path"]
        post_id = post_id_from_url(url)
        try:
            content = path.read_bytes()
        except OSError as exc:
            add_error(CheckError("baseline", "baseline_read_failed", str(path), str(exc)), "guide", post_id, document_id)
            return None
        digest = sha256(content).hexdigest()
        if applied.get("sha256") and applied["sha256"] != digest:
            message = "기준판 파일이 상태 파일에 기록된 반영판 해시와 일치하지 않습니다."
            add_error(CheckError("baseline", "baseline_hash_mismatch", str(path), message), "guide", post_id, document_id)
            return None
        document = TrackedDocument(config, saved, content, digest, url, post_id)
        if applied.get("published_at"):
            saved_date = parse_time(applied["published_at"])
            if saved_date <= cutoff:
                document.published = saved_date
        post = ListedPost(post_id, url, source["title"], cutoff.date())
        try:
            published, files = get_details(post)
            if cutoff < published:
                raise CheckError("baseline", "before_baseline", url, "종료 시각이 기준판 게시 시각보다 이릅니다.")
            document.published = published
            attachment = guide_attachment(config, files, post)
            saved["applied_version"] = {
                "post_url": url, "published_at": published.isoformat(),
                "attachment_url": applied.get("attachment_url") or attachment.url, "sha256": digest,
            }
            check_guide(document, post, published, attachment)
            record_checked(post)
        except CheckError as exc:
            add_error(exc, "guide", post_id, document_id)
        return document

    def check_listings(tracked: list[TrackedDocument], earliest: datetime) -> None:
        posts = {}
        searches = [source, *source.get("related_searches", [])]
        for search in searches:
            for term in search["search_terms"]:
                try:
                    found = board.search(search["board_url"], term, earliest.date())
                except CheckError as exc:
                    add_error(exc, "board" if search is source else "related_board")
                    continue
                for post in found:
                    if search is source:
                        kind = post_kind(post.title, source)
                    else:
                        kind = "notice" if any(
                            compact(term) in compact(post.title) for term in search["title_terms"]
                        ) else None
                    if kind and earliest.date() <= post.day <= cutoff.date():
                        posts.setdefault(post.key, (post, kind))

        original_urls = {config["baseline_post_url"] for config in source["documents"]}
        original_urls.update(doc.post_url for doc in tracked)
        original_keys = {(board_id_from_url(url), post_id_from_url(url)) for url in original_urls}
        for key in original_keys:
            posts.pop(key, None)

        previous_targets = {}
        for doc in tracked:
            observed = doc.state.get("latest_observed_version")
            if observed:
                observed_at = parse_time(observed["published_at"])
                if observed_at <= cutoff:
                    post = ListedPost(observed["post_id"], observed["post_url"], source["title"], observed_at.date())
                    if post.key not in original_keys:
                        previous_targets.setdefault(post.key, set()).add(doc.id)
                        posts.setdefault(post.key, (post, "guide"))

        for post, kind in sorted(posts.values(), key=lambda item: item[0].day):
            try:
                published, attachments = get_details(post)
                if published.date() != post.day:
                    raise CheckError("post_detail", "inconsistent_date", post.url, "목록과 상세 게시일이 다릅니다.")
                old_tracked_post = post.key in previous_targets
                if published > cutoff or (not old_tracked_post and published < earliest):
                    continue
                record_checked(post)
                if kind != "guide":
                    check_related(post, published, attachments, kind)
                    continue
                eligible = [doc for doc in tracked if doc.published and published >= doc.published]
                if not eligible:
                    continue
                if len(document_ids) > 1:
                    target_ids = {
                        doc.id for doc in eligible
                        if names_volume(post.title, doc.config["volume"])
                        or any(names_volume(item.name, doc.config["volume"]) for item in attachments)
                    }
                    target_ids.update(previous_targets.get(post.key, set()))
                    eligible = [doc for doc in eligible if doc.id in target_ids]
                    if not eligible:
                        raise CheckError("post_detail", "ambiguous_volume", post.url, "개정 게시물의 권을 식별할 수 없습니다.")
                for doc in eligible:
                    try:
                        check_guide(doc, post, published, guide_attachment(doc.config, attachments, post))
                    except CheckError as exc:
                        add_error(exc, "guide", post.post_id, doc.id)
            except CheckError as exc:
                add_error(exc, kind, post.post_id)

    if last_success and cutoff < last_success:
        message = "종료 시각이 마지막 성공 시점보다 이릅니다. 과거 테스트에는 별도 상태 파일을 사용하세요."
        add_error(CheckError("baseline", "cutoff_before_last_success", source["board_url"], message), "board")
    else:
        tracked = [doc for config in source["documents"] if (doc := check_baseline(config))]
        published_dates = [doc.published for doc in tracked if doc.published is not None]
        if published_dates:
            earliest = min(published_dates)
            if last_success:
                prior_day = last_success.date() - timedelta(days=1)
                earliest = max(earliest, datetime.combine(prior_day, time.min, tzinfo=KST))
            result["window_start"] = earliest.isoformat()
            check_listings(tracked, earliest)

    result["documents"] = []
    for config in source["documents"]:
        document_id = config["document_id"]
        changed = any(
            item["is_new"] and (item["document_id"] == document_id or document_id in item.get("document_ids", []))
            for item in result["candidates"]
        )
        failed = any(
            error["scope"] in {"board", "guide", "erratum"} and error["document_id"] in (None, document_id)
            for error in result["errors"]
        )
        status = "changed" if changed else "check_failed" if failed else "unchanged"
        result["documents"].append({"document_id": document_id, "label": config.get("label", document_id), "pdf_status": status})

    pdf_statuses = {item["pdf_status"] for item in result["documents"]}
    result["pdf_status"] = "changed" if "changed" in pdf_statuses else "check_failed" if "check_failed" in pdf_statuses else "unchanged"
    new_notice = any(item["is_new"] for item in result["related_notices"])
    notice_failed = result["window_start"] is None or any(
        error["scope"] in {"board", "related_board", "notice", "related_guide"} for error in result["errors"]
    )
    result["related_notice_status"] = "found" if new_notice else "check_failed" if notice_failed else "nothing_new"
    if result["errors"]:
        verified = result["attachments"] or result["related_notices"] or result["candidates"]
        result["status"] = "partial" if verified else "check_failed"
    else:
        result["status"] = "changed" if result["pdf_status"] == "changed" or new_notice else "unchanged"
        source_state["last_success_at"] = cutoff.isoformat()
    state["known_candidate_ids"] = sorted(known)
    return result


def summary_text(report: dict) -> str:
    pdf_labels = {"changed": "변경 발견", "unchanged": "변경 없음", "check_failed": "확인 실패"}
    related_labels = {"found": "발견 · 관리자 검토 필요", "nothing_new": "새 게시물 없음", "check_failed": "확인 실패"}
    lines = []
    for result in report["sources"]:
        source_id = result["source_id"]
        candidates = [entry for entry in report["candidates"] if entry["source_id"] == source_id]
        notices = [entry for entry in report["related_notices"] if entry["source_id"] == source_id]
        related_label = "관련 설명서" if source_id == "welfare_services_guide" else "관련 고시"
        lines.extend([
            f"## {result['title']} 점검", "",
            f"- 조회 범위 · {result['window_start'] or '확인 실패'} ~ {result['window_end']}",
            f"- PDF · {pdf_labels[result['pdf_status']]}",
            f"- {related_label} · {related_labels[result['related_notice_status']]}",
        ])
        if len(result["documents"]) > 1:
            for document in result["documents"]:
                lines.append(f"  - {document['label']} PDF · {pdf_labels[document['pdf_status']]}")
        previous_candidates = sum(not entry["is_new"] for entry in candidates)
        if previous_candidates:
            lines.append(f"- 이전 실행에서 발견한 PDF 후보 · {previous_candidates}건")
        for entry in candidates + notices:
            if not entry["is_new"]:
                continue
            default_title = "공식 첨부와 로컬 기준판 차이" if entry["change_type"] == "baseline_attachment_differs" else "PDF 변경 후보"
            title = entry.get("title") or default_title
            details = []
            if entry.get("article_hint"):
                details.append(entry["article_hint"])
            if entry.get("effective_date"):
                details.append(f"{entry['effective_date']} 시행")
            if entry.get("review_reason"):
                details.append(entry["review_reason"])
            if "new_page_count" in entry:
                details.append(f"{entry['old_page_count']} → {entry['new_page_count']}쪽")
                details.append(f"텍스트 변경 후보 {len(entry['changed_sections'])}개 구간")
            lines.append(" · ".join([f"- [{title}]({entry['post_url']})", *details]))
        for error in result["errors"]:
            lines.append(f"- 점검 실패 · {error['stage']} · {error['message']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="보건복지부 복지 사업안내와 관련 게시물을 점검합니다.")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/pdf-check-sources.json")
    parser.add_argument("--source", action="append", help="점검할 출처 ID. 생략하면 설정에 있는 모든 출처를 점검합니다.")
    parser.add_argument("--state-in", type=Path, help="이전 점검 상태 JSON")
    parser.add_argument("--state-out", type=Path, required=True, help="다음 점검에 사용할 상태 JSON")
    parser.add_argument("--report", type=Path, required=True, help="이번 점검 보고서 JSON")
    parser.add_argument("--summary", type=Path, help="점검 요약 Markdown")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "data/staging/pdf-check")
    parser.add_argument("--as-of", help="과거 테스트의 종료 시각. 시간대 생략 시 KST.")
    args = parser.parse_args()
    started = datetime.now(KST)

    try:
        output_paths = [path.resolve() for path in (args.state_out, args.report, args.summary) if path]
        if len(set(output_paths)) != len(output_paths):
            raise ValueError("상태, 보고서, 요약 파일은 다른 경로를 사용하세요.")
        if args.state_in and args.state_in.resolve() in output_paths[1:]:
            raise ValueError("이전 상태 파일을 보고서나 요약 경로로 사용할 수 없습니다.")
        cutoff = parse_time(args.as_of) if args.as_of else started
        if cutoff > started:
            raise ValueError("테스트 종료 시각은 실제 실행 시각 이후일 수 없습니다.")
        state = read_json(args.state_in) if args.state_in else {"sources": [], "known_candidate_ids": []}
        configured = read_json(args.config)["sources"]
        requested = set(args.source or ())
        sources = [item for item in configured if not requested or item["source_id"] in requested]
        if not sources or requested - {item["source_id"] for item in sources}:
            raise ValueError("점검할 출처 ID를 출처 설정에서 확인하세요.")
        baseline_paths = {
            (ROOT / document["baseline_path"]).resolve()
            for source in configured for document in source["documents"]
        }
        if args.config.resolve() in output_paths or baseline_paths.intersection(output_paths):
            raise ValueError("출처 설정과 기준판 PDF는 결과 파일 경로로 사용할 수 없습니다.")
        run_key = started.strftime("%Y%m%dT%H%M%S%f")
        with requests.Session() as session:
            board = Board(session)
            checked = [
                check_source(board, source, state, cutoff, args.work_dir, run_key, historical=bool(args.as_of))
                for source in sources
            ]
        results = {item["status"] for item in checked}
        has_errors = any(item["errors"] for item in checked)
        if has_errors:
            status = "check_failed" if results == {"check_failed"} else "partial"
        else:
            status = "changed" if "changed" in results else "unchanged"
        trigger = "historical" if args.as_of else os.environ.get("GITHUB_EVENT_NAME", "manual")
        scheduled = started.replace(day=1, hour=9, minute=10, second=0, microsecond=0)
        report = {
            "run_id": os.environ.get("GITHUB_RUN_ID", run_key),
            "run_attempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
            "trigger": trigger,
            "scheduled_at": scheduled.isoformat() if trigger == "schedule" else None,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(KST).isoformat(),
            "status": status,
            "sources": [
                {key: value for key, value in item.items() if key not in {"candidates", "related_notices"}}
                for item in checked
            ],
            "candidates": [entry for item in checked for entry in item["candidates"]],
            "related_notices": [entry for item in checked for entry in item["related_notices"]],
        }
        write_json(args.report, report)
        summary = summary_text(report)
        if args.summary:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(summary, encoding="utf-8")
        write_json(args.state_out, state)
        print(summary, end="")
        return 2 if has_errors else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"PDF 점검 실행 실패 · {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
