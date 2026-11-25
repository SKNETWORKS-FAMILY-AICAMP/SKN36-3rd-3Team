"""Preserve XML contact groups; flattened legacy values are candidates only."""
import json
import re
from .contact_phone_normalizer import extract_improved_contacts

GROUPS = ('inqplCtadrList', 'inqplHmpgReldList', 'baslawList', 'basfrmList')
PHONE = re.compile(r'(?:0\d{1,2}[- ]\d{3,4}[- ]\d{4}|1[5-8]\d{2}[- ]\d{4})\Z')
SHORT = re.compile(r'1\d{2,3}\Z')


def xml_related_groups(root):
    return {group: [{child.tag: (child.text or '').strip() or None
                     for child in node} for node in root.iter(group)]
            for group in GROUPS}


def as_list(value):
    if value is None: return []
    if isinstance(value, list): return value
    if isinstance(value, dict): return [value]
    if not isinstance(value, str): return [value]
    value = value.strip()
    if not value or value.lower() in {'nan', 'none', 'null', '<na>'}: return []
    if value.startswith(('[', '{')):
        try:
            obj = json.loads(value)
            return obj if isinstance(obj, list) else [obj]
        except (ValueError, TypeError): return []
    return [value]


def phone(value, structured=False):
    if not isinstance(value, str): return None
    value = value.strip()
    if PHONE.fullmatch(value) or (structured and SHORT.fullmatch(value)):
        return value
    return None


def normalize_contacts(row):
    groups = {g: as_list(row.get('detail_' + g, row.get(g))) for g in GROUPS}
    structured_present = 'detail_inqplCtadrList' in row or 'inqplCtadrList' in row
    structured = groups['inqplCtadrList']
    confirmed = []
    candidates = []
    if structured_present:
        for entry in structured:
            if not isinstance(entry, dict): continue
            number = phone(entry.get('wlfareInfoReldCn'), structured=True)
            if number:
                confirmed.append({'phone': number, 'name': entry.get('wlfareInfoReldNm'),
                                  'source': 'inqplCtadrList', 'verified_group': True})
    else:
        codes = as_list(row.get('detail_wlfareInfoDtlCd'))
        values = as_list(row.get('detail_wlfareInfoReldCn'))
        # Flattened arrays can have missing members. Never zip codes/names/values.
        if '010' in {str(c).strip() for c in codes}:
            for value in values:
                number = phone(value)
                if number and number not in candidates: candidates.append(number)

    phone_review = []

    if not structured_present:
        codes = as_list(
            row.get('detail_wlfareInfoDtlCd')
        )

        if '010' in {str(c).strip() for c in codes}:

            improved = extract_improved_contacts(
                row.get('detail_wlfareInfoReldCn')
            )

            candidates = list(dict.fromkeys(
                candidates + improved['phones']
            ))

            phone_review = improved['review']

    numbers = list(dict.fromkeys(x['phone'] for x in confirmed))
    return {
        'contact': ' / '.join(numbers) if numbers else None,
        'contact_details': confirmed,
        'contact_candidates': candidates,
        'contact_phone_review': phone_review,
        'contact_status': ('source_group_confirmed' if confirmed else
                           'legacy_candidate_review' if candidates else 'unknown'),
        'related_groups': groups,
        'related_metadata_raw': {k: row.get(k) for k in (
            'detail_wlfareInfoDtlCd', 'detail_wlfareInfoReldCn', 'detail_wlfareInfoReldNm')},
    }


def parse_view_count(value):
    text = str(value).strip() if value is not None else ''
    return int(text) if re.fullmatch(r'\d+', text) else None


def read_contact_overlays(zip_paths):
    """Read optional original XML archives. Duplicate IDs with conflicting XML fail."""
    import zipfile
    import xml.etree.ElementTree as ET
    from pathlib import PurePosixPath
    overlays = {}
    for path in zip_paths:
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                name = PurePosixPath(member).name
                if not re.fullmatch(r'WLF\d+\.xml', name): continue
                root = ET.fromstring(archive.read(member))
                sid = root.findtext('.//servId')
                if root.findtext('.//resultCode') not in {'0','00'} or sid != name[:-4]:
                    raise ValueError(f'Invalid detail XML: {member}')
                entry = {'date': root.findtext('.//lastModYmd'), 'groups': xml_related_groups(root)}
                if sid in overlays and overlays[sid] != entry:
                    raise ValueError(f'Conflicting original detail XML: {sid}')
                overlays[sid] = entry
    return overlays


def apply_contact_overlays(rows, overlays):
    """Overlay only exact ID + detail revision matches; never modify source files."""
    matched = 0
    for row in rows:
        entry = overlays.get(str(row.get('servId') or '').strip())
        if not entry: continue
        date = str(row.get('detail_lastModYmd') or '').strip()
        if not date or date != str(entry['date'] or '').strip(): continue
        if str(row.get('detail_fetched')).lower() not in {'true','1'}: continue
        row.update({'detail_' + key: value for key, value in entry['groups'].items()})
        matched += 1
    return matched
