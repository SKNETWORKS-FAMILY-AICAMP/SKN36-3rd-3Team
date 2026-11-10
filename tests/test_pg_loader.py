from pathlib import Path
import tempfile
import uuid
import json
from scripts.load_postgres import load_and_validate


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')


def test_pr25_pr26_mapping_uuid_and_parent_check():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        base=root/'data/rag'
        write(root/'data/processed/local_welfare/elderly_filtered/run_20261109_000000/policies_elderly_selected.jsonl',
              [{'policy_id':'WLF001','title':'시험 정책','elderly_candidate_category':'direct'}])
        write(base/'documents/policy_documents.jsonl',
              [{'policy_id':'local:WLF001','text':'사업명: 시험 정책','metadata':{'record_type':'policy','title':'시험 정책'}}])
        write(base/'documents/source_documents.jsonl',[{'document_id':'doc1','title':'테스트 PDF'}])
        write(base/'documents/guideline_documents.jsonl',
              [{'section_id':'sec1','text':'목차: 테스트','metadata':{'document_id':'doc1'}}])
        for strat,prefix in [('fixed','A_fixed'),('structure','B_structure')]:
            for kind,name,pr in [('policy','policy_chunks','local:WLF001'),('guideline','guideline_chunks','sec1')]:
                cid=f'{kind}::{pr}::{strat}::0001'
                item={'id':str(uuid.uuid5(uuid.NAMESPACE_URL,cid)),'chunk_id':cid,'text':'내용',
                      'metadata':{'record_type':kind,'chunk_strategy':strat,'parent_id':pr,'chunk_id':cid}}
                item['policy_id' if kind=='policy' else 'section_id']=pr
                write(base/f'chunks/{prefix}/{name}.jsonl',[item])
        rows,report=load_and_validate(root)
        assert len(rows['policies'])==1
        assert report['rag_chunks_total']==4
