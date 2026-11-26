import collections as C, csv, hashlib, json, pathlib
from rag.document_builder import build_policy_document, TEXT_FIELDS
from rag.chunking.fixed_chunker import chunk_fixed
P=pathlib.Path
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--inputs', type=P, required=True)
parser.add_argument('--output', type=P, required=True)
args = parser.parse_args()
CHANGE_FIELDS = {
    'region': {'sido_name', 'sigungu_name', 'region_scope', 'candidate_scope',
               'applies_to', 'scope_basis', 'scope_status'},
    'contact': {'contact', 'contact_status', 'contact_candidates', 'contact_details',
                'field_sources.contact'},
    'application': {'application_text', 'application_method_name', 'application_required',
                    'application_basis', 'approval_status'},
}
APPLICATION_FIELDS = ('application_text', 'application_method_name',
                      'application_required', 'application_basis')


def read(p):
    with P(p).open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def stage_age_conditions(metadata, policy_id):
    """Keep each source reference in the existing graph age-condition format."""
    evidence = metadata.get('age_evidence') or []
    bounds = {(entry['operator'], entry['value']) for entry in evidence}
    if len(bounds) == 1:
        operator, value = next(iter(bounds))
        if operator in ('>=', '>'):
            metadata['age_min'] = value + (operator == '>')
        else:
            metadata['age_max'] = value - (operator == '<')
    return [
        dict(field='age', operator=entry['operator'], value=entry['value'],
             raw_text=entry['raw_text'], source_field=entry['field'],
             source_id=policy_id, condition_group=None, review_status='needs_review')
        for entry in evidence
    ]


def index(rows):return {'local:'+r['policy_id'].split(':')[-1]:r for r in rows}
base=index(read(args.inputs / 'contact-all.jsonl'))
stage=index(read(args.inputs / 'team3-stage-checked.jsonl'))
assert len(base)==4427 and len(stage)==555 and len(base.keys()&stage.keys())==149
for policy_id, policy in stage.items():
    policy["contact_xml_match_status"] = "matched"
    policy["data_origin"] = "jeonnam_gwangju_combined_detail_xml"
    if policy_id in base:
        for field in ("legacy_contact_raw",):
            policy[field] = base[policy_id].get(field)

rows=base|stage
changes=[]
for name, allowed in CHANGE_FIELDS.items():
 path=args.inputs / f'{name}_changes.jsonl'
 for c in read(path):
  if c['field'] not in allowed:
   raise ValueError(f"{path}: {c['policy_id']} has disallowed field {c['field']}")
  changes.append(c)
seen=set()
for c in changes:
 i,f=c['policy_id'],c['field']
 assert (i,f) not in seen and c['basis']
 assert c['base_version']==('jeonnam_gwangju_zip_20261125' if i in stage else 'nationwide_2026_11_25_84d46d570a5b')
 seen.add((i,f)); p=rows[i]; *path,key=f.split('.')
 for k in path:p=p.setdefault(k,{})
 assert p.get(key)==c['old']
 p[key]=c['new']
issues=[]
for i,r in sorted(rows.items()):
 r['policy_id']=i
 r['approval_status']='pending'
 if r.get('scope_status')!='confirmed':
  if r.get('region_scope') not in (None,'unknown'):
   r.setdefault('candidate_scope',r['region_scope'])
  r['region_scope']='unknown'
 r.setdefault('scope_status','unknown')
 r.setdefault('applies_to',[])
 if r.get('field_sources',{}).get('contact') in {'inqNum','detail_inqNum'}:
  issues.append({'policy_id':i,'reason':'legacy contact provenance unverified'})
  r['field_sources']['contact']='unknown'
  r['contact']=None
  r['contact_status']='unknown'
 if r.get('contact_status')!='source_group_confirmed':
  assert not r.get('contact'),i
all_rows=[rows[i] for i in sorted(rows)]
elder_ids=set(index(read(args.inputs / 'contact-elder.jsonl')))
selected=[r for r in all_rows if (r['elderly_candidate_category'] in {'direct','indirect'} if r['policy_id'] in stage else r['policy_id'] in elder_ids)]
old_graph=index(read(args.inputs / 'v3-policy_graph_entities.jsonl'))
documents=[]; inputs=[]; chunks=[]; graphs=[]
age_repaired=set()
age_needs_review=set()
for r in selected:
 doc=build_policy_document(r)
 i=r['policy_id'];m=doc['metadata']
 for k in ('sido_name','sigungu_name','region_scope','candidate_scope','scope_status','applies_to','scope_basis','application_required','application_basis'):
  m[k]=r.get(k)
 m['region_status']='confirmed' if r['scope_status']=='confirmed' else 'needs_review'
 age_conditions=[]
 if i in stage and m.get('age_evidence') and m['age_min'] is None and m['age_max'] is None:
  age_conditions=stage_age_conditions(m,i)
  age_repaired.add(i)
  if m['age_min'] is None and m['age_max'] is None:
   age_needs_review.add(i)
 textlines=[]
 for label,key in TEXT_FIELDS:
  value=' '.join(v for v in (m['sido_name'],m['sigungu_name']) if v) if key is None else r.get(key)
  if isinstance(value,str) and value.strip():textlines.append(f'{label}: {value.strip()}')
 doc['text']='\n'.join(textlines)
 documents.append(doc);inputs.append({**r,**{k:m[k] for k in ('age_min','age_max','age_evidence','age_review_status','need_tags','need_evidence','need_review_status','region_status')}})
 chunks.extend(chunk_fixed(doc,chunk_size=800,overlap=150))
 conditions=[dict(field=k,operator=None,value=None,raw_text=r[k],source_id=i,condition_group=None,review_status='needs_review') for k in ('target_text','selection_criteria_text') if r.get(k)]
 if age_conditions:
  conditions.extend(age_conditions)
 else:
  for k,op in [('age_min','>='),('age_max','<=')]:
   if m.get(k) is not None:conditions.append(dict(field='age',operator=op,value=m[k],raw_text=m.get('age_evidence'),source_id=i,condition_group=None,review_status='needs_review'))
 prior=old_graph.get(i,{}) if i not in stage else {}
 region=dict(
     sido_name=m['sido_name'], sigungu_name=m['sigungu_name'],
     scope=m['region_scope'], candidate_scope=m['candidate_scope'],
     applies_to=r['applies_to'], scope_status=r['scope_status'], scope_basis=r.get('scope_basis'),
     region_status=m['region_status'], review_status='needs_review')
 application={k:r.get(k) for k in APPLICATION_FIELDS}
 graphs.append(dict(policy_id=i,title=r['title'],eligibility_conditions=prior.get('eligibility_conditions',conditions),need_tags=m['need_tags'],need_evidence=m['need_evidence'],regions=[region],application=application,agencies=[dict(name=m['department'],role='responsible_department',contact=m['contact'],source_id=i,review_status='needs_review')] if m.get('department') else [],related_policy_ids=prior.get('related_policy_ids',[]),evidence_refs=[{k:m[k] for k in ('source_id','source_url','source_type')}],approval_status='pending'))
pdf_docs=read(args.inputs / 'v3-guideline_documents.jsonl');pdf_chunks=read(args.inputs / 'v3-guideline_chunks.jsonl')
for r in pdf_docs+pdf_chunks:
 r['approval_status']='pending';r['metadata']['approval_status']='pending'
def canonical(r):
 c={k:v for k,v in r.items() if k!='data_version'}
 if 'metadata' in c:c['metadata']={k:v for k,v in c['metadata'].items() if k!='data_version'}
 return (json.dumps(c,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
h=hashlib.sha256()
for data,key in [(chunks,'chunk_id'),(pdf_chunks,'chunk_id'),(graphs,'policy_id')]:
 assert len({r[key] for r in data})==len(data)
 for r in sorted(data,key=lambda r:r[key]):h.update(canonical(r))
version='nationwide_2026_11_26_'+h.hexdigest()[:12]
assert len(all_rows)==4833 and len(pdf_docs)==1189 and len(pdf_chunks)==2738
assert all(not r['metadata'].get('contact') or r['metadata']['contact_status']=='source_group_confirmed' for r in chunks)
output=args.output
if output.exists() and (not output.is_dir() or any(output.iterdir())):
 raise FileExistsError(f"Generation output must be a new or empty directory: {output}")
final='data/processed/local_welfare/nationwide/final_v3/'
rag='data/rag/nationwide_v3/'
files={final+'policies_all.jsonl':all_rows,final+'policies_elderly_candidates.jsonl':selected,rag+'policy_metadata_input.jsonl':inputs,rag+'policy_documents.jsonl':documents,rag+'policy_chunks.jsonl':chunks,rag+'policy_graph_entities.jsonl':graphs,rag+'guideline_documents.jsonl':pdf_docs,rag+'guideline_chunks.jsonl':pdf_chunks}
def write(path,data):
 p=output/path
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(data,encoding='utf-8',newline='\n')
 return hashlib.sha256(p.read_bytes()).hexdigest()
hashes={}
for path,data in files.items():
 for r in data:
  r['data_version']=version
  if 'metadata' in r:r['metadata']['data_version']=version
 hashes[path]=write(path,''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in data))
history=index(read(args.inputs / 'contact-all.jsonl'))
write(final+'history/jeonnam_legacy149_previous.jsonl',''.join(json.dumps(history[i],ensure_ascii=False)+'\n' for i in sorted(history.keys()&stage.keys())))
def j(o):return json.dumps(o,ensure_ascii=False,indent=2)+'\n'
age_missing = {doc['policy_id'] for doc,graph in zip(documents,graphs,strict=True)
               if doc['metadata'].get('age_evidence')
               and not any(condition['field']=='age' for condition in graph['eligibility_conditions'])}
region_empty = {r['policy_id'] for r in all_rows
                if r.get('sigungu_name') and r['sigungu_name'] != '-' and '교육' not in r['sigungu_name']
                and not r['applies_to']}
region_exception_path = args.inputs / 'region_scope_unresolved.csv'
with region_exception_path.open(encoding='utf-8-sig', newline='') as stream:
 exceptions = {record['policy_id']:record['reason'] for record in csv.DictReader(stream)}
assert exceptions.keys() <= region_empty and all(exceptions.values())
contact_lines = [(chunk['policy_id'], line.split(':',1)[1].strip())
                 for chunk in chunks for line in chunk['text'].splitlines() if line.startswith('문의처:')]
region_keys = {'scope':'region_scope', 'sido_name':'sido_name', 'sigungu_name':'sigungu_name',
                'candidate_scope':'candidate_scope', 'applies_to':'applies_to',
                'scope_status':'scope_status', 'scope_basis':'scope_basis'}
checks = dict(
    registered_sigungu_without_applies_to=len(region_empty),
    documented_region_scope_exceptions=len(exceptions),
    unexplained_region_scope_gaps=len(region_empty-exceptions.keys()),
    candidate_or_confirmed_without_basis=sum(
        r['scope_status'] in {'candidate','confirmed'} and not r.get('scope_basis') for r in all_rows),
    invalid_sigungu=sum(
        r.get('sigungu_name') and (r['sigungu_name']=='-' or '교육' in r['sigungu_name']) or False
        for r in all_rows),
    graph_region_mismatches=sum(
        any(key not in region or region[key]!=rows[graph['policy_id']].get(field)
            for key,field in region_keys.items()) for graph in graphs for region in graph['regions']),
    age_evidence_without_graph_age=len(age_missing),
    age_policies_with_added_conditions=len(age_repaired),
    age_policies_with_unmerged_evidence=len(age_needs_review),
    overlong_chunks=sum(len(chunk['text'])>800 for chunk in chunks+pdf_chunks),
    contact_lines=len(contact_lines),
    contact_line_mismatches=sum(phone!=str(rows[pid].get('contact') or '').strip()
                                for pid,phone in contact_lines),
    graph_application_mismatches=sum(
        graph.get('application')!={k:rows[graph['policy_id']].get(k) for k in APPLICATION_FIELDS}
        for graph in graphs),
)
report=dict(data_version=version,counts={P(k).stem:len(v) for k,v in files.items()},contact_status=dict(C.Counter(r.get('contact_status') for r in all_rows)),missing={k:sum(not r.get(k) for r in all_rows) for k in ('contact','application_text','application_method_name','sido_name','sigungu_name')},adopted_changes=len(changes),checks=checks,issues=issues)
name=rag+'metadata_validation_report.json';hashes[name]=write(name,j(report))
manifest=dict(data_version=version,status='not_approved',approved_by=None,approved_at=None,public_fields={'policy':'title summary target_text selection_criteria_text benefit_text application_text application_method_name application_required source_url contact department'.split(),'guideline':'text title chapter section page_start page_end source_url publisher publication_year'.split()},derived_public_fields={'application_required':'원문 근거가 확인된 가공값 (application_basis 필수)'},excluded_policy_ids=[],excluded_section_ids=[],files=hashes,check_report='metadata_validation_report.json')
write(rag+'release_manifest.json',j(manifest))
write(rag+'REPRODUCE.md','''# v3 검토본 재생성\n\n- 기준 정책, 그래프, PDF는 커밋 0c76ae4에서 읽었습니다. 기본 생성 코드는 dev 604c161입니다.\n- 통합시 기준본은 상세 515건과 추가 XML 40건을 정규화한 뒤 기본값을 적용한 555건입니다.\n- 통합시 기본값 적용본 SHA-256: ac13990912c6ec80d9ffde08f42006d4fad9375315c6a749f570696fb9b67e28\n- 원본 ZIP SHA-256: ac304e6af7ab21e0e6d683c8a20ae41a45fbe65c7995881b1cbf2da702152814\n- 기존 PDF 문서와 청크 경계를 유지하고 승인 상태 및 버전을 다시 기록했습니다.\n- 루트 README.md의 명령으로 패키지에 포함된 기준 입력을 사용해 재생성합니다.\n''')
print(version,report)
