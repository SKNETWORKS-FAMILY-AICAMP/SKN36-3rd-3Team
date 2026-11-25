import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'welfare_preprocessing'))
from welfare_pipeline.contact_fields import normalize_contacts, xml_related_groups, apply_contact_overlays
from welfare_pipeline.normalize_policies import normalize_policy
from welfare_pipeline.region_selection import classify_region, PROVINCES


class ContactTests(unittest.TestCase):
    def test_view_count_is_not_phone(self):
        p = normalize_policy({'servId':'WLF1', 'inqNum':'2590', 'detail_inqNum':'2195'})
        self.assertEqual(p['view_count'], 2195)
        self.assertIsNone(p['contact'])

    def test_flattened_arrays_are_not_zipped(self):
        p = normalize_policy({'servId':'WLF1','detail_wlfareInfoDtlCd':'["010","030","040"]',
            'detail_wlfareInfoReldCn':'["031-760-2453","https://example.com/file"]',
            'detail_wlfareInfoReldNm':'["기관","법령","파일"]'})
        self.assertIsNone(p['contact'])
        self.assertEqual(p['contact_candidates'], ['031-760-2453'])
        self.assertEqual(p['contact_status'], 'legacy_candidate_review')
        self.assertEqual(p['contact_details'], [])

    def test_xml_parent_group_preserved(self):
        root = ET.fromstring('<root><inqplCtadrList><wlfareInfoDtlCd>010</wlfareInfoDtlCd>'
            '<wlfareInfoReldCn>061-530-5981</wlfareInfoReldCn><wlfareInfoReldNm>담당부서</wlfareInfoReldNm>'
            '</inqplCtadrList><basfrmList><wlfareInfoReldCn>02-123-4567</wlfareInfoReldCn></basfrmList></root>')
        p = normalize_policy({'servId':'WLF1', **{'detail_'+k:v for k,v in xml_related_groups(root).items()}})
        self.assertEqual(p['contact'], '061-530-5981')
        self.assertEqual(p['contact_details'][0]['name'], '담당부서')
        self.assertNotIn('02-123-4567', p['contact'])

    def test_overlay_requires_revision_match(self):
        rows = [{'servId':'WLF1','detail_lastModYmd':'20261125','detail_fetched':True}]
        data = {'WLF1':{'date':'20261124','groups':{'inqplCtadrList':[]}}}
        self.assertEqual(apply_contact_overlays(rows,data),0)
        self.assertNotIn('detail_inqplCtadrList',rows[0])


class RegionTests(unittest.TestCase):
    def test_all_named_regions_retained(self):
        for i, (region,label) in enumerate(PROVINCES.items()):
            if label == 'gwangju_jeonnam': continue
            p = normalize_policy({'servId':f'WLF{i}','ctpvNm':region,'requested_region':region,'sggNm':'테스트시'})
            out = classify_region(p,{})
            self.assertEqual(out['region_selection_status'],'included')
            self.assertEqual(out['region_selection_label'], label)
            self.assertFalse(out['region_scope_verified'])

    def test_combined_regions(self):
        for district,label in [('목포시','jeonnam'),('광산구','gwangju'),(None,'unknown')]:
            p=normalize_policy({'servId':'WLF1','ctpvNm':'전남광주통합특별시','sggNm':district})
            out=classify_region(p,{})
            self.assertEqual(out['region_selection_label'],label)
            self.assertEqual(out['region_selection_status'],'included')

    def test_conflicting_region_retained_for_review(self):
        p=normalize_policy({'servId':'WLF1','ctpvNm':'경기도','detail_ctpvNm':'부산광역시'})
        out=classify_region(p,{})
        self.assertEqual(out['region_selection_label'],'unknown')
        self.assertEqual(out['region_search_status'],'review_required')
        self.assertEqual(out['region_selection_status'],'included')

    def test_unverified_national_not_scope_verified(self):
        p=normalize_policy({'servId':'WLF1','ctpvNm':'전남광주통합특별시'})
        out=classify_region(p,{'WLF1':{'candidate_region':'national'}})
        self.assertEqual(out['region_search_status'],'review_required')
        self.assertFalse(out['region_selection_verified'])

if __name__=='__main__': unittest.main()
