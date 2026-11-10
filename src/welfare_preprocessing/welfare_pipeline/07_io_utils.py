"""공통 JSONL 입출력 / 실행 경로 / 필수 ID 검증."""
from pathlib import Path
from datetime import datetime
import json

def read_jsonl(path):
    path = Path(path)
    if not path.is_file(): raise FileNotFoundError(path)
    rows=[]
    with path.open(encoding='utf-8-sig') as f:
        for i,line in enumerate(f,1):
            if line.strip():
                try: rows.append(json.loads(line))
                except json.JSONDecodeError as e: raise ValueError(f'{path}:{i}: {e}') from e
    return rows

def write_jsonl(path, rows):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w',encoding='utf8') as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
    return path

def ensure_unique(rows, field='policy_id'):
    ids=[str(r.get(field) or '').strip() for r in rows]
    if any(not x for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError(f'{field} 값 공백/중복 발견')

def new_run_dir(parent):
    root=Path(parent);root.mkdir(parents=True,exist_ok=True)
    path=root/datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
    path.mkdir(exist_ok=False)
    return path

def find_project_root(cwd=None):
    cwd=Path(cwd or Path.cwd()).resolve()
    return next((p for p in [cwd,*cwd.parents] if (p/'data'/'raw'/'api').is_dir()),cwd)
