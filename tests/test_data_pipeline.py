import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.collect.common import CollectionError, collect, parse_response, request_page, run_collector
from src.preprocess.pipeline import age, chunks, clean, load_pdf, load_xml, normalize, run, validate


def config():
    return dict(endpoint='https://example.invalid/api', key_param='serviceKey',
                page_param='pageNo', size_param='numOfRows', page_size=1,
                records_path='items', total_path='total', success_path='code',
                success_values=['00'], field_map={'id': 'id', 'title': 'name'},
                source_url='https://example.invalid/source')


def make_pdf(path, blank_page=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 10 200 Td (Synthetic test document: national support.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    if blank_page:
        writer.add_blank_page(width=300, height=300)
    with path.open('wb') as target:
        writer.write(target)


class PipelineTests(unittest.TestCase):
    def test_clean_double_entities_and_comparisons(self):
        self.assertEqual(clean('&amp;#9312; A&#13;B'), '① A\nB')
        self.assertIn('age < 65', clean('<p>age < 65</p>'))

    def test_chunk_boundaries_overlap_and_stability(self):
        text = '가' * 1800
        pieces = list(chunks(text))
        self.assertEqual([len(p) for p in pieces], [700, 700, 600])
        self.assertEqual(pieces[0][-100:], pieces[1][:100])
        self.assertEqual(list(chunks('짧은 문장')), ['짧은 문장'])
        with self.assertRaises(ValueError):
            list(chunks(text, 400))

    def test_unknown_is_not_all_or_zero(self):
        record = {'id': 'test', 'title': '테스트', 'text': '65세 조건과 60세 예외가 섞인 합성 테스트.'}
        doc = next(normalize(record, 'welfare_api', 'sample.json'))
        self.assertIsNone(doc['metadata']['min_age'])
        self.assertIsNone(doc['metadata']['sido'])
        self.assertEqual(doc['metadata']['target'], [])
        self.assertIsNone(age(True))
        self.assertIsNone(age('65세 이상'))
        self.assertEqual(age(65), 65)
        explicit = next(normalize(dict(record, sido='전국', target=['전체']), 'welfare_api', 'sample.json'))
        self.assertEqual(explicit['metadata']['target'], ['전체'])

    def test_stable_identity_and_content_hash(self):
        row = {'id': 'A', 'title': '테스트', 'text': '합성 자료'}
        a = list(normalize(row, 'welfare_api', 'a.json'))
        b = list(normalize(row, 'welfare_api', 'a.json'))
        self.assertEqual(a, b)
        changed = next(normalize(dict(row, text='변경된 합성 자료'), 'welfare_api', 'a.json'))
        self.assertEqual(a[0]['metadata']['doc_id'], changed['metadata']['doc_id'])
        self.assertNotEqual(a[0]['metadata']['content_hash'], changed['metadata']['content_hash'])

    def test_every_chunk_keeps_title_and_length_limit(self):
        docs = list(normalize({'id': 'long', 'title': '정책명' * 50, 'text': '가' * 2000}, 'welfare_api', 'a.json', size=800))
        self.assertGreater(len(docs), 1)
        self.assertTrue(all(d['text'].startswith('정책명') for d in docs))
        self.assertTrue(all(len(d['text']) <= 800 for d in docs))

    def test_mixed_pdf_records_empty_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp) / 'raw', Path(tmp) / 'out'
            raw.mkdir()
            make_pdf(raw / 'mixed.pdf', blank_page=True)
            report = run(raw, out)
            self.assertEqual(report['pdf_empty_pages'], {'mixed.pdf': [2]})

    def test_samples_are_excluded_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp) / 'raw', Path(tmp) / 'out'
            raw.mkdir()
            make_pdf(raw / 'manual.pdf')
            (raw / 'fake.json').write_text(json.dumps({'source': 'welfare_api', 'is_sample': True,
                'records': [{'id': 'test', 'title': '가짜', 'text': '합성'}]}), encoding='utf-8')
            report = run(raw, out)
            self.assertEqual(report['document_count'], 1)
            self.assertEqual(report['excluded_sample_records'], 1)
            report = run(raw, out, include_samples=True)
            self.assertEqual(report['document_count'], 2)

    def test_schema_rejects_empty_text_and_missing_metadata(self):
        with self.assertRaises(ValueError):
            list(normalize({'title': '제목', 'text': ''}, 'faq_129', 'f.json'))
        with self.assertRaises(ValueError):
            validate({'text': 'text', 'metadata': {}})

    def test_coordinate_crs_must_be_explicit(self):
        row = dict(id='F', title='합성시설', text='주소 테스트', lat=35, lon=128)
        self.assertIsNone(next(normalize(row, 'facility_api', 'f.json'))['metadata']['lat'])
        self.assertEqual(next(normalize(dict(row, crs='EPSG:4326'), 'facility_api', 'f.json'))['metadata']['lat'], 35)

    def test_pdf_region_is_not_inferred_from_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'gyeongnam-guide.pdf'
            make_pdf(path)
            source, row = load_pdf(path, {})[0]
            self.assertIn('Synthetic test', row['text'])
            doc = next(normalize(row, source, path.name))
            self.assertIsNone(doc['metadata']['sido'])
            self.assertEqual(doc['metadata']['page'], 1)
            explicit = load_pdf(path, {'sido': '전국'})[0][1]
            self.assertEqual(explicit['sido'], '전국')

    def test_xml_preserves_exceptions_without_inventing_age_or_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.xml'
            path.write_text('<wantedDtl><servId>T</servId><servNm>합성 노인 정책</servNm><lifeArray>노년</lifeArray><tgtrDtlCn>65세. 60세 예외.</tgtrDtlCn><crtrYr>2026</crtrYr><resultCode>0</resultCode></wantedDtl>', encoding='utf-8')
            source, row = load_xml(path, {})[0]
            doc = next(normalize(row, source, path.name))
            self.assertIn('60세 예외', doc['text'])
            self.assertIsNone(doc['metadata']['min_age'])
            self.assertEqual(doc['metadata']['base_date'], '2026')
            self.assertIsNone(doc['metadata']['collected_at'])

    def test_four_source_pipeline_idempotent_and_atomic_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, output = root / 'raw', root / 'out'
            raw.mkdir()
            for source in ('facility_api', 'welfare_api', 'faq_129'):
                item = {'id': source, 'title': '합성 제목', 'text': '실제 정책이 아닌 테스트 데이터', 'url': 'https://example.invalid'}
                if source == 'faq_129':
                    item.update(question='합성 질문?', answer='합성 답변')
                (raw / (source + '.json')).write_text(json.dumps({'source': source, 'is_sample': True, 'records': [item, item]}), encoding='utf-8')
            make_pdf(raw / 'manual.pdf')
            report = run(raw, output, include_samples=True)
            self.assertEqual(report['document_count'], 4)
            self.assertEqual(len(report['source_counts']), 4)
            first = (output / 'documents.jsonl').read_bytes()
            self.assertEqual(run(raw, output, include_samples=True), report)
            self.assertEqual((output / 'documents.jsonl').read_bytes(), first)
            (raw / 'broken.xml').write_text('<broken>', encoding='utf-8')
            with self.assertRaises(ValueError):
                run(raw, output)
            self.assertEqual((output / 'documents.jsonl').read_bytes(), first)


class CollectorTests(unittest.TestCase):
    def test_pagination_and_no_credential_persistence(self):
        def requester(endpoint, params):
            page = params['pageNo']
            return json.dumps({'code': '00', 'total': 2, 'items': [{'id': str(page), 'name': '合成'}]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = collect('facility_api', config(), 'SUPER_SECRET', tmp, requester=requester, now='2026-11-06T00:00:00+00:00')
            first = path.read_bytes()
            self.assertNotIn(b'SUPER_SECRET', first)
            self.assertEqual(json.loads(first)['count'], 2)
            collect('facility_api', config(), 'SUPER_SECRET', tmp, requester=requester, now='2026-11-07T00:00:00+00:00')
            self.assertEqual(path.read_bytes(), first)

    def test_repeated_page_or_application_error_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CollectionError):
                collect('welfare_api', config(), 'key', tmp, requester=lambda *_: b'{"code":"00","total":2,"items":[{"id":"same"}]}')
            self.assertFalse((Path(tmp) / 'welfare_api' / 'snapshot.json').exists())
        with self.assertRaises(CollectionError):
            parse_response(b'{"code":"ERROR","total":0,"items":[]}', config())

    def test_xml_single_record_and_empty_records(self):
        c = dict(config(), format='xml', records_path='items.item')
        rows, total = parse_response(b'<root><code>00</code><total>1</total><items><item><id>x</id></item></items></root>', c)
        self.assertEqual(rows, [{'id': 'x'}])
        self.assertEqual(total, 1)

    def test_network_timeout_and_retry_are_bounded_and_redacted(self):
        calls = []
        def opener(url, timeout):
            calls.append(timeout)
            raise TimeoutError(url)
        with self.assertRaises(CollectionError) as caught:
            request_page('https://example.invalid', {'key': 'SECRET'}, opener=opener, sleeper=lambda _: None)
        self.assertEqual(calls, [20, 20, 20])
        self.assertNotIn('SECRET', str(caught.exception))

    def test_missing_key_skips_network(self):
        with patch.dict('os.environ', {}, clear=True), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(run_collector('facility_api', 'FACILITY', []), 0)
            self.assertIn('SKIPPED', output.getvalue())


if __name__ == '__main__':
    unittest.main()
