"""Safety checks across raw merge, normalization, selection, retrieval and ingestion."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.welfare_preprocessing.welfare_pipeline import normalize_policies, region_selection, elderly_filter
from src.rag.document_builder import build_policy_document
from scripts.load_postgres import load_and_validate
from scripts.diff_local_welfare_snapshots import compare
from src.welfare_preprocessing.welfare_pipeline.io_utils import write_jsonl
from backend.src.services.policy_service import _region_matches, _guideline_item
from backend.src.schemas.policies import RegionSelection
from scripts.build_local_welfare_candidate import validate_input, STAGING

ROOT = Path(__file__).resolve().parents[1]
def test_pr36_validated_input_has_unique_ids():
    rows, manifest = validate_input(ROOT, ROOT / STAGING / 'merged_policies_raw.jsonl', ROOT / STAGING / 'validation_report.json')
    assert len(rows) == len({r['servId'] for r in rows}) == 4278
    assert all(r['detail_fetched'] for r in rows)
    assert manifest['sha256']
    assert manifest['line_ending'] == 'git_normalized_crlf_to_lf'
    assert manifest['data_version'] == manifest['report_sha256'][:16]


def test_reject_tampered_staging_input(tmp_path):
    from shutil import copyfile
    (tmp_path / STAGING).mkdir(parents=True)
    source = tmp_path / STAGING / 'merged_policies_raw.jsonl'
    report = tmp_path / STAGING / 'validation_report.json'
    copyfile(ROOT / STAGING / 'merged_policies_raw.jsonl', source)
    copyfile(ROOT / STAGING / 'validation_report.json', report)
    with source.open('a', encoding='utf-8') as f:
        f.write('{}\n')
    with pytest.raises(ValueError, match='SHA-256'):
        validate_input(tmp_path, source, report)


def test_view_count_never_becomes_contact_in_document():
    raw = {'servId':'WLF100', 'servNm':'노인 지원', 'inqNum':'5447',
           'detail_inqNum':'2966', 'requested_region':'경기도', 'detail_fetched':True}
    p = normalize_policies.normalize_policy(raw)
    assert p['contact'] is None and 'contact' not in p['field_sources']
    selected = elderly_filter.classify_elderly(region_selection.classify_region(p, {}))
    doc = build_policy_document(selected)
    assert doc['metadata']['contact'] is None
    assert '문의처:' not in doc['text']


@pytest.mark.parametrize('region', [
    '서울특별시','경기도','부산광역시','대구광역시','인천광역시','광주광역시',
    '대전광역시','울산광역시','세종특별자치시','강원특별자치도',
    '충청북도','충청남도','전북특별자치도','전라남도','경상북도',
    '경상남도','제주특별자치도',
])
def test_supported_regions_preserved_as_unverified_candidates(region):
    p = normalize_policies.normalize_policy({'servId':'test', 'ctpvNm':region, 'requested_region':region})
    selected = region_selection.classify_region(p, {})
    assert selected['region_selection_status'] == 'included'
    assert selected['region_selection_verified'] is False


def test_region_conflict_quarantined():
    p = normalize_policies.normalize_policy({'servId':'test','ctpvNm':'경기도','detail_ctpvNm':'서울특별시','requested_region':'경기도'})
    selected = region_selection.classify_region(p, {})

    # 지역 충돌 정책은 전체 데이터에 보존
    assert selected['region_selection_status'] == 'included'

    # 불확실한 지역은 검토 대상으로 분류
    assert selected['region_selection_label'] == 'unknown'
    assert selected['region_search_status'] == 'review_required'
    assert selected['region_selection_verified'] is False


def test_life_stage_noyun_is_direct_but_exclusion_stays_review():
    assert elderly_filter.classify_elderly({'life_stage_tags':['노년']})['elderly_candidate_category'] == 'direct'
    assert elderly_filter.classify_elderly({'life_stage_tags':['노년'], 'target_text':'65세 미만'})['elderly_candidate_category'] == 'review'


def test_legacy_loader_rejects_unverified_phone_mapping():
    with pytest.raises(ValueError, match='inqNum은 조회수'):
        load_and_validate(ROOT)


def test_district_requires_exact_match_or_explicit_province_scope():
    wanted = RegionSelection(kind='region', sido_name='경기도', sigungu_name='수원시')
    assert not _region_matches({'sido_name':'경기도','region_scope':'unknown'}, wanted)
    assert _region_matches({'sido_name':'경기도','region_scope':'sido'}, wanted)
    assert _region_matches({'sido_name':'경기도','sigungu_name':'수원시','region_scope':'sigungu'}, wanted)
    assert not _region_matches({'sido_name':'경기도','sigungu_name':'용인시','region_scope':'sigungu'}, wanted)


def test_guideline_requires_explicit_approval():
    assert _guideline_item({'document_id':'d'}).approval == 'pending'
    assert _guideline_item({'document_id':'d','approval_status':'approved'}).approval == 'approved'


def test_change_review_ignores_view_count_and_preserves_removal_for_review(tmp_path):
    before, after = tmp_path / 'before.jsonl', tmp_path / 'after.jsonl'
    write_jsonl(before, [
        {'servId':'a','requested_region':'경기도','detail_fetched':True,'detail_servNm':'대상포진','inqNum':'1'},
        {'servId':'b','requested_region':'경기도','detail_fetched':True,'detail_servNm':'제도 종료'},
    ])
    write_jsonl(after, [
        {'servId':'a','requested_region':'경기도','detail_fetched':True,'detail_servNm':'대상포진 변경','inqNum':'999'},
        {'servId':'c','requested_region':'경기도','detail_fetched':True,'detail_servNm':'새 정책'},
    ])
    assert [(x['policy_id'],x['change_type']) for x in compare(before, after)] == [
        ('a','updated'),('b','missing_in_snapshot_review_before_retirement'),('c','new')]
    assert compare(before, before) == []


def test_partial_region_cannot_be_mistaken_for_removed_policy(tmp_path):
    before, after = tmp_path / 'before.jsonl', tmp_path / 'after.jsonl'
    write_jsonl(before,[{'servId':'a','ctpvNm':'경기도'}])
    write_jsonl(after,[{'servId':'b','ctpvNm':'서울특별시','detail_fetched':True}])
    with pytest.raises(ValueError, match='수집 지역'):
        compare(before, after)


@pytest.mark.parametrize('region', ['경기도','서울특별시','부산광역시','전북특별자치도','제주특별자치도'])
@pytest.mark.parametrize('views', ['0','1','129','5447','999999'])
@pytest.mark.parametrize('target,expected', [
    ('노년', 'direct'), ('기초생활보장', 'indirect'),
    ('영유아', 'exclude_candidate'), ('대상 확인 필요', 'review'),
])
def test_100_cross_stage_variations_never_turn_views_into_phone(region, views, target, expected):
    p = normalize_policies.normalize_policy({'servId':'WLF100', 'servNm':target,
        'ctpvNm':region, 'requested_region':region, 'inqNum':views, 'detail_inqNum':views})
    p = region_selection.classify_region(p, {})
    p = elderly_filter.classify_elderly(p)
    assert p['region_selection_status'] == 'included'
    assert p['elderly_candidate_category'] == expected
    assert p['contact'] is None
    if expected in {'direct','indirect'}:
        doc = build_policy_document(p)
        assert doc['metadata']['contact'] is None and '문의처:' not in doc['text']


def test_conflicting_region_preserved_but_not_searchable(tmp_path):
    import csv
    from src.welfare_preprocessing.welfare_pipeline.io_utils import (
        read_jsonl, write_jsonl
    )

    raw = {
        'servId': 'WLF_TEST_CONFLICT',
        'servNm': '노인 복지 지원',
        'ctpvNm': '경기도',
        'detail_ctpvNm': '서울특별시',
        'requested_region': '경기도'
    }

    policy = normalize_policies.normalize_policy(raw)

    input_path = tmp_path / 'normalized.jsonl'
    candidate_path = tmp_path / 'candidates.csv'

    write_jsonl(input_path, [policy])

    with candidate_path.open('w', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['policy_id', 'candidate_region'])

    result = region_selection.run(
        input_path,
        candidate_path,
        tmp_path / 'output'
    )

    output = Path(result['run_dir'])

    all_rows = read_jsonl(
        output / 'policies_all_with_selection.jsonl'
    )

    search_rows = read_jsonl(
        output / 'policies_region_search_candidates.jsonl'
    )

    quarantined = read_jsonl(
        output / 'policies_region_quarantined.jsonl'
    )

    assert len(all_rows) == 1
    assert len(search_rows) == 0
    assert len(quarantined) == 1

    assert quarantined[0]['policy_id'] == 'WLF_TEST_CONFLICT'
