"""지자체 복지서비스 목록·상세조회 API: 페이지/ID별 캐시, 한도 관리.
기존 수집 파일은 덮어쓰지 않음. API 응답 변경 시 --endpoint 확인 필요.
"""
import os,json,math,time,xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
import requests
from .io_utils import write_jsonl

BASE='https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations'
LIST_URL=BASE+'/LcgvWelfarelist'
DETAIL_URL=BASE+'/LcgvWelfaredetailed'
class CollectionPaused(Exception):pass

class WelfareCollector:
    def __init__(self,api_key,work_dir,max_calls=100,delay=0.4,page_size=100):
        if not api_key:raise ValueError('DATA_GO_KR_API_KEY 환경변수가 필요합니다')
        self.key=api_key;self.root=Path(work_dir);self.root.mkdir(parents=True,exist_ok=True)
        self.page_dir=self.root/'list_pages';self.page_dir.mkdir(exist_ok=True)
        self.detail_dir=self.root/'details';self.detail_dir.mkdir(exist_ok=True)
        self.max_calls=max_calls;self.calls=0;self.delay=delay;self.page_size=page_size;self.session=requests.Session()
    def get(self,url,params,label):
        if self.calls>=self.max_calls:raise CollectionPaused(f'실행당 API 요청 한도 {self.max_calls}회 도달')
        self.calls+=1
        try:
            r=self.session.get(url,params={'serviceKey':self.key,**params},timeout=40)
            if r.status_code==429:raise CollectionPaused('HTTP 429')
            r.raise_for_status();root=ET.fromstring(r.content)
            code=root.findtext('.//resultCode')
            if code!='0':raise CollectionPaused(f'{label} code={code}: {root.findtext(".//resultMessage")}')
            time.sleep(self.delay);return root
        except CollectionPaused:raise
        except Exception as e:raise CollectionPaused(f'{label}: {e}') from e
    def list_region(self,region,slug):
        first=self.page_dir/f'{slug}_page_00001.json'
        if first.exists():data=json.loads(first.read_text(encoding='utf8'))
        else:
            data=self._fetch_page(region,1);first.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        if data['page_size']!=self.page_size or data['region']!=region:raise ValueError('기존 캐시 지역명/PAGE_SIZE 불일치')
        total=data['total'];pages=math.ceil(total/self.page_size)
        for n in range(2,pages+1):
            path=self.page_dir/f'{slug}_page_{n:05d}.json'
            if not path.exists():
                result=self._fetch_page(region,n);path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        rows=[]
        for n in range(1,pages+1):
            path=self.page_dir/f'{slug}_page_{n:05d}.json'
            if path.exists():rows+=json.loads(path.read_text(encoding='utf8'))['rows']
        byid={str(r['servId']):{**r,'requested_region':region} for r in rows if r.get('servId')}
        return list(byid.values()), {'expected':total,'saved':len(byid),'complete':len(byid)==total}
    def _fetch_page(self,region,n):
        root=self.get(LIST_URL,{'callTp':'L','ctpvNm':region,'pageNo':n,'numOfRows':self.page_size},f'{region} 페이지 {n}')
        rows=[{e.tag:e.text for e in node} for node in root.findall('servList')]
        total=int(root.findtext('totalCount','0'))
        if total and not rows:raise CollectionPaused(f'{region} 페이지 {n}: totalCount={total}이나 항목 없음')
        return {'region':region,'page':n,'page_size':self.page_size,'total':total,'rows':rows}
    def detail(self,sid):
        root=self.get(DETAIL_URL,{'callTp':'D','servId':sid},f'상세 {sid}')
        vals=defaultdict(list)
        for node in root.iter():
            if len(node)==0 and (node.text or '').strip() and node.tag not in ('resultCode','resultMessage'):
                vals[node.tag].append(node.text.strip())
        result={k:v[0] if len(v)==1 else json.dumps(v,ensure_ascii=False) for k,v in vals.items()};result['servId']=sid
        if len(result)<=1:raise CollectionPaused(f'{sid}: 상세내용 없음')
        return result
    def collect_details(self,rows):
        cache_path=self.detail_dir/'welfare_detail_cache.jsonl';cache={}
        if cache_path.exists():
            for line in cache_path.read_text(encoding='utf8').splitlines():
                if line.strip():
                    obj=json.loads(line)
                    if obj.get('servId'):cache[str(obj['servId'])]=obj
        for sid in dict.fromkeys(str(row['servId']) for row in rows if row.get('servId')):
            if sid in cache:continue
            try:result=self.detail(sid)
            except CollectionPaused:break
            cache[sid]=result
            with cache_path.open('a',encoding='utf8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
        return cache

def merge_list_detail(rows,cache):
    merged=[]
    for row in rows:
        sid=str(row.get('servId') or '').strip();detail=cache.get(sid)
        item=dict(row);item['detail_fetched']=detail is not None
        if detail:item.update({'detail_'+k:v for k,v in detail.items() if k!='servId'})
        merged.append(item)
    return merged
