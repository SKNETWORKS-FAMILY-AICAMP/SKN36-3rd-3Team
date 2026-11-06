"""Paginated JSON/XML API transport. No scraping; credentials never persisted."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
import xml.etree.ElementTree as ET


class CollectionError(ValueError):
    """Safe error message without credential-bearing URLs."""


def at_path(value, path):
    for key in path.split('.') if path else []:
        if not isinstance(value, dict) or key not in value:
            raise CollectionError('Configured response path was not found')
        value = value[key]
    return value


def xml_value(element):
    if not list(element):
        return element.text or ''
    result = {}
    for child in element:
        key = child.tag.rsplit('}', 1)[-1]
        value = xml_value(child)
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return result


def parse_response(raw, config):
    if config.get('format', 'json') == 'xml':
        root = ET.fromstring(raw)
        value = xml_value(root)
    else:
        value = json.loads(raw)
    # Application-level errors can be HTTP 200. A success path is mandatory.
    code = at_path(value, config['success_path'])
    if str(code) not in [str(x) for x in config['success_values']]:
        raise CollectionError('API returned a non-success application code')
    records = at_path(value, config['records_path'])
    if records in (None, ''):
        records = []
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise CollectionError('Configured records path must contain records')
    total = at_path(value, config['total_path'])
    try:
        total = int(total)
    except (ValueError, TypeError) as exc:
        raise CollectionError('Invalid total count') from exc
    if total < 0:
        raise CollectionError('Invalid total count')
    return records, total


def request_page(endpoint, params, *, opener=urlopen, sleeper=time.sleep, retries=2, timeout=20):
    url = endpoint + '?' + urlencode(params)
    for attempt in range(retries + 1):
        try:
            with opener(url, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if not retryable or attempt == retries:
                raise CollectionError(f'API HTTP failure ({exc.code})') from None
        except (URLError, TimeoutError, OSError):
            if attempt == retries:
                raise CollectionError('API network failure after bounded retries') from None
        sleeper(2 ** attempt)
    raise CollectionError('Unreachable request state')


def validate_config(config):
    required = ['endpoint', 'key_param', 'page_param', 'size_param', 'records_path',
                'total_path', 'success_path', 'success_values', 'field_map', 'source_url']
    if any(not config.get(k) for k in required):
        raise CollectionError('API config is incomplete; verify the official operation specification')
    parsed = urlsplit(config['endpoint'])
    if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        raise CollectionError('Endpoint must be an HTTPS URL without query or credentials')
    if config.get('page_size', 100) <= 0 or config.get('max_pages', 1000) <= 0:
        raise CollectionError('Page size and limit must be positive')
    if config.get('format', 'json') not in {'json', 'xml'}:
        raise CollectionError('Unsupported response format')
    if not {'id', 'title'}.issubset(config['field_map']):
        raise CollectionError('Field map must include id and title')


def collect(source, config, key, output, *, requester=request_page, now=None):
    validate_config(config)
    collected_at = now or datetime.now(timezone.utc).isoformat()
    destination = Path(output) / source
    page_size = int(config.get('page_size', 100))
    start = int(config.get('start_page', 1))
    all_records, seen_pages = [], set()
    total = None
    for page in range(start, start + int(config.get('max_pages', 1000))):
        params = dict(config.get('params', {}))
        params.update({config['key_param']: key, config['page_param']: page,
                       config['size_param']: page_size})
        raw = requester(config['endpoint'], params)
        records, current_total = parse_response(raw, config)
        if total is not None and current_total != total:
            raise CollectionError('Total changed during collection; retry a fresh snapshot')
        total = current_total
        if not records and len(all_records) < total:
            raise CollectionError('Pagination ended before the declared total')
        fingerprint = hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if records and fingerprint in seen_pages:
            raise CollectionError('Repeated API page; pagination is not advancing')
        seen_pages.add(fingerprint)
        all_records.extend(records)
        if len(all_records) >= total:
            break
    else:
        raise CollectionError('Maximum pages reached before completion')
    if len(all_records) != total:
        raise CollectionError('Record count does not match declared total')
    # Store normalized raw envelopes, never request params, key or raw error pages.
    envelope = {'source': source, 'collected_at': collected_at,
                'source_url': config['source_url'], 'field_map': config['field_map'],
                'records': all_records, 'count': len(all_records)}
    serialized = json.dumps(envelope, ensure_ascii=False, indent=2)
    if key and key in serialized:
        raise CollectionError('API response contains the credential; refusing to save')
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / 'snapshot.json'
    # Identical data keeps the prior collection time and bytes (idempotent).
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if all(previous.get(k) == v for k, v in envelope.items() if k != 'collected_at'):
            return path
    temporary = path.with_suffix('.tmp')
    temporary.write_text(serialized + '\n', encoding='utf-8')
    temporary.replace(path)
    return path


def run_collector(source, prefix, argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=f'Collect {source} using an approved official API operation')
    parser.add_argument('--config', default=os.environ.get(prefix + '_API_CONFIG'))
    parser.add_argument('--output', default='data/raw')
    args = parser.parse_args(argv)
    key = os.environ.get(prefix + '_API_KEY')
    if not key:
        print(f'SKIPPED: {prefix}_API_KEY is unset; use existing raw/manual files.')
        return 0
    if not args.config or not Path(args.config).is_file():
        parser.exit(2, 'API config is missing. Copy the example and verify official operation fields.\n')
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
        path = collect(source, config, key, args.output)
    except (CollectionError, ValueError, KeyError, ET.ParseError, OSError):
        parser.exit(2, 'Collection failed. Check config, connectivity and API approval; no credentials are logged.\n')
    print(f'Saved: {path}')
    return 0
