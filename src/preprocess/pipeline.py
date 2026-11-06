from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from src.collect.common import at_path, xml_value


FIELDS = ('doc_id', 'source', 'doc_type', 'title', 'provider', 'sido', 'sigungu',
          'min_age', 'target', 'category', 'phone', 'address', 'lat', 'lon', 'url',
          'apply_period', 'base_date', 'collected_at', 'page', 'chunk_index',
          'source_path', 'original_id', 'content_hash', 'is_sample')
NULL_FIELDS = ('provider', 'sido', 'sigungu', 'min_age', 'url', 'apply_period',
               'base_date', 'collected_at', 'phone', 'address', 'lat', 'lon', 'page')


def clean(value):
    if value is None:
        return ''
    text = str(value)
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    # Remove formatting tags only, not comparisons such as 'age < 65'.
    text = re.sub(r'</?(?:p|br|div|span|li|ul|ol|b|strong|em)(?:\s[^>]*)?\s*/?>', '\n', text, flags=re.I)
    text = text.replace('\r', '\n')
    return '\n'.join(re.sub(r'[\t \u00a0]+', ' ', line).strip()
                     for line in text.splitlines() if line.strip()).strip()


def chunks(text, size=700, overlap=100):
    if not 500 <= size <= 800 or not 0 <= overlap < size:
        raise ValueError('Chunk size must be 500..800, with overlap smaller than size')
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind('\n', start + 500, end), text.rfind(' ', start + 500, end))
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            yield piece
        if end == len(text):
            break
        start = end - overlap


def optional(value):
    return clean(value) or None


def age(value):
    # Only an explicit structured numeric field is accepted. Never extract the
    # first age in a paragraph with exceptions and several service categories.
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 120:
        return value
    if isinstance(value, str) and value.isdigit() and 0 <= int(value) <= 120:
        return int(value)
    return None


def tags(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [clean(v) for v in value if clean(v)]
    return [v.strip() for v in clean(value).split(',') if v.strip()]


def validate(document):
    if set(document) != {'text', 'metadata'} or not isinstance(document['text'], str) or not document['text'].strip():
        raise ValueError('Invalid text/document envelope')
    meta = document['metadata']
    if any(k not in meta for k in FIELDS):
        raise ValueError('Missing metadata field')
    for key in ('doc_id', 'source', 'doc_type', 'title', 'source_path', 'original_id', 'content_hash'):
        if not isinstance(meta[key], str) or not meta[key]:
            raise ValueError('Invalid required metadata')
    if meta['min_age'] is not None and age(meta['min_age']) != meta['min_age']:
        raise ValueError('Invalid age')
    if not isinstance(meta['target'], list) or not all(isinstance(t, str) for t in meta['target']):
        raise ValueError('Invalid target')
    if not isinstance(meta['chunk_index'], int) or meta['chunk_index'] < 0:
        raise ValueError('Invalid chunk index')
    if meta['page'] is not None and (not isinstance(meta['page'], int) or meta['page'] < 1):
        raise ValueError('Invalid PDF page')
    if meta['url'] is not None and not re.match(r'^https?://', meta['url']):
        raise ValueError('Invalid source URL')
    return document


def normalize(record, source, source_path, *, size=700, overlap=100):
    if not 500 <= size <= 800:
        raise ValueError('Chunk size must be 500..800')
    title = optional(record.get('title'))
    body = clean(record.get('text'))
    if not title or not body:
        raise ValueError('Title and body are required')
    original_id = optional(record.get('id')) or hashlib.sha256((title + body).encode()).hexdigest()[:24]
    meta = {key: None for key in FIELDS}
    meta.update({
        'source': source, 'doc_type': record.get('doc_type', 'service'), 'title': title,
        'provider': optional(record.get('provider')), 'sido': optional(record.get('sido')),
        'sigungu': optional(record.get('sigungu')), 'min_age': age(record.get('min_age')),
        'target': tags(record.get('target')), 'category': optional(record.get('category')),
        'phone': optional(record.get('phone')), 'address': optional(record.get('address')),
        'url': optional(record.get('url')), 'apply_period': optional(record.get('apply_period')),
        'base_date': optional(record.get('base_date')), 'collected_at': optional(record.get('collected_at')),
        'page': record.get('page'), 'source_path': source_path, 'original_id': original_id,
        'is_sample': bool(record.get('is_sample', False)),
    })
    # Coordinates are copied only when explicitly WGS84; no CRS guessing.
    if record.get('crs') == 'EPSG:4326':
        try:
            lat, lon = float(record['lat']), float(record['lon'])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                meta.update(lat=lat, lon=lon)
        except (KeyError, TypeError, ValueError):
            pass
    for index, body_piece in enumerate(chunks(body, min(size, 719), overlap)):
        piece = f'{title[:80]}\n{body_piece}'
        current = dict(meta, chunk_index=index)
        identity = json.dumps([source, original_id, meta['page'], index], ensure_ascii=False)
        current['doc_id'] = hashlib.sha256(identity.encode()).hexdigest()
        current['content_hash'] = hashlib.sha256(piece.encode()).hexdigest()
        yield validate({'text': piece, 'metadata': current})


def mapped_record(item, field_map):
    result = {}
    for field, path in field_map.items():
        if path:
            try:
                result[field] = at_path(item, path)
            except ValueError:
                result[field] = None
    return result


def load_json(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or 'source' not in data or 'records' not in data:
        return []  # API list/auxiliary files are joined by the XML loader.
    if not isinstance(data['records'], list):
        raise ValueError('records must be a list')
    result = []
    for item in data['records']:
        record = mapped_record(item, data['field_map']) if data.get('field_map') else dict(item)
        if data['source'] == 'faq_129':
            question, answer = record.get('question'), record.get('answer')
            if question and answer:
                record['title'] = question
                record['text'] = f'질문: {question}\n답변: {answer}'
            record['doc_type'] = 'faq'
        if data['source'] == 'facility_api':
            record['doc_type'] = 'facility'
            if not record.get('text'):
                record['text'] = '\n'.join(str(record[k]) for k in ('title', 'address', 'phone') if record.get(k))
        record.setdefault('collected_at', data.get('collected_at'))
        record.setdefault('url', data.get('source_url'))
        record['is_sample'] = bool(data.get('is_sample', False) or record.get('is_sample', False))
        result.append((data['source'], record))
    return result


def load_xml(path, list_lookup, elderly_only=True):
    root = ET.fromstring(path.read_bytes())
    if root.tag != 'wantedDtl' or root.findtext('resultCode') != '0':
        raise ValueError('Not a successful central welfare detail XML')
    data = xml_value(root)
    if elderly_only and '노년' not in clean(data.get('lifeArray')) and '노인' not in clean(data.get('servNm')):
        return []
    sections = [('정책 개요', 'wlfareInfoOutlCn'), ('지원 대상·제외·예외', 'tgtrDtlCn'),
                ('선정 기준', 'slctCritCn'), ('지원 내용', 'alwServCn')]
    body = [label + '\n' + clean(data.get(key)) for label, key in sections if clean(data.get(key))]
    for node in root.findall('applmetList'):
        body.append(clean(node.findtext('servSeDetailNm')) + ': ' + clean(node.findtext('servSeDetailLink')))
    record = {'id': data.get('servId'), 'title': data.get('servNm'), 'text': '\n'.join(body),
              'provider': data.get('jurMnofNm'), 'phone': data.get('rprsCtadr'),
              'target': data.get('trgterIndvdlArray'), 'category': data.get('intrsThemaArray'),
              'base_date': data.get('crtrYr'),
              'url': list_lookup.get(data.get('servId'), {}).get('servDtlLink')}
    # Central agency and a PDF hosted in Gyeongnam do not prove regional scope.
    return [('central_welfare_api', record)]


def load_pdf(path, source_info, empty_pages=None):
    from pypdf import PdfReader
    reader = PdfReader(path)
    records = []
    for index, page in enumerate(reader.pages, 1):
        text = clean(page.extract_text())
        if text:
            info = dict(source_info)
            info.update(id=source_info.get('id', path.stem), title=source_info.get('title', path.stem),
                        text=text, doc_type='guide', page=index)
            records.append(('gyeongnam_pdf', info))
        elif empty_pages is not None:
            empty_pages.append(index)
    if not records:
        raise ValueError('PDF contains no extractable text; OCR/manual review required')
    return records


def run(input_dir, output_dir, *, manifest=None, size=700, overlap=100, elderly_only=True, include_samples=False):
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    if not input_dir.is_dir():
        raise ValueError('Input directory does not exist')
    sources = json.loads(Path(manifest).read_text(encoding='utf-8')) if manifest else {}
    lookup = {}
    for path in sorted(input_dir.rglob('welfare_list.json')):
        entries = json.loads(path.read_text(encoding='utf-8-sig'))
        lookup.update({item['servId']: item for item in entries})
    documents, failures, skipped, seen = [], [], [], {}
    empty_pdf_pages, excluded_samples = {}, 0
    for path in sorted(input_dir.rglob('*')):
        if path.suffix.lower() not in {'.json', '.xml', '.pdf'}:
            continue
        relative = path.relative_to(input_dir).as_posix()
        info = sources.get(relative, {})
        try:
            if path.suffix.lower() == '.xml':
                records = load_xml(path, lookup, elderly_only)
            elif path.suffix.lower() == '.pdf':
                empty = []
                records = load_pdf(path, info, empty)
                if empty:
                    empty_pdf_pages[relative] = empty
            else:
                records = load_json(path)
            if not records:
                skipped.append(relative)
            for source, record in records:
                # Manifest provenance is explicit; source-extracted values win.
                record = dict(info, **{k: v for k, v in record.items() if v is not None})
                if record.get('is_sample') and not include_samples:
                    excluded_samples += 1
                    continue
                for document in normalize(record, source, relative, size=size, overlap=overlap):
                    meta = document['metadata']
                    identity = meta['doc_id']
                    if identity in seen:
                        if seen[identity] != meta['content_hash']:
                            raise ValueError('Conflicting records share a stable ID')
                        continue
                    seen[identity] = meta['content_hash']
                    documents.append(document)
        except (ValueError, OSError, ImportError, ET.ParseError) as exc:
            failures.append({'file': relative, 'error': type(exc).__name__, 'reason': str(exc)[:150]})
    if failures:
        raise ValueError('Preprocessing aborted; existing output preserved: ' + json.dumps(failures, ensure_ascii=False))
    if not documents:
        raise ValueError('No documents produced; existing output preserved')
    documents.sort(key=lambda d: d['metadata']['doc_id'])
    counts = Counter(d['metadata']['source'] for d in documents)
    report = {'document_count': len(documents), 'source_counts': dict(counts),
              'record_count': len({(d['metadata']['source'], d['metadata']['original_id']) for d in documents}),
              'null_ratio': {key: sum(d['metadata'][key] is None for d in documents) / len(documents) for key in NULL_FIELDS},
              'skipped_files': skipped, 'errors': [], 'chunk_size': size, 'overlap': overlap,
              'pdf_empty_pages': empty_pdf_pages, 'excluded_sample_records': excluded_samples,
              'note': 'No embedding, LLM, eligibility determination, or current-policy verification performed.'}
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in [('documents.jsonl', ''.join(json.dumps(d, ensure_ascii=False, sort_keys=True) + '\n' for d in documents)),
                           ('report.json', json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')]:
        path = output_dir / filename
        temporary = path.with_suffix('.tmp')
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(path)
    return report
