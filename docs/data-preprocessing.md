# M0~M2 데이터 파이프라인 MVP

Claude 기획 · Codex 구현 및 상호 리뷰. 작업 브랜치 `feature/data-pipeline`, dev 대상 PR만 생성하고 병합하지 않는다. 기존 #8~#11 작업을 보완하는 전달 규격·로더이며 기존 담당자의 업무 완료를 의미하지 않는다. UI #12는 별도 작업이다.

## 실행

Python 3.11 이상. 이 단계는 LLM·임베딩·벡터DB를 호출하지 않는다. 최소 실행 의존성은 기존 requirements.txt의 pypdf 하나이며, 검증 환경은 pypdf 6.21.4다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pypdf
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_data_pipeline.py -v
.\.venv\Scripts\python.exe -m src.preprocess --input data/raw --output data/processed
```

출력은 `data/processed/documents.jsonl`, `report.json`. 오류가 있거나 출력이 0개이면 실패하고 기존 documents.jsonl을 보존한다. 기존 원본·가공물은 새 커밋에 포함하지 않는다. 원본을 이미 추적하는 팀 저장소의 과거 파일은 삭제하지 않는다.

## M1 입력 경로

- 기존 중앙부처 상세 XML: `data/raw/api/*.xml`. `welfare_list.json`의 servId·servDtlLink와 연결한다. 코드 0의 성공 응답만 처리한다.
- 시설·지자체 API: `python -m src.collect.facility`, `python -m src.collect.welfare`. 키가 없으면 SKIPPED를 출력하고 기존 원본/수동입력 경로를 사용한다.
- FAQ: 이용조건을 확인하고 수동 저장한 JSON. 웹 크롤러는 구현하지 않았다.
- PDF: 기존 `data/raw/pdf/*.pdf` 및 수동 PDF. 텍스트를 추출할 수 없는 스캔본은 실패시켜 OCR·수동 검토로 넘긴다.

API 수집기는 HTTPS·페이지 수·총 건수·성공코드 확인, 20초 timeout, 재시도 2회, 반복 페이지 감지, 완료 후 원본 JSON 저장을 지원한다. 동일 데이터 재수집은 기존 snapshot과 수집일을 유지한다. 인증키와 요청 URL은 저장·오류 로그에 넣지 않는다.

**실호출 제한:** 시설·지자체 API의 승인키와 상세 오퍼레이션 명세를 확인하지 못했다. config 예제의 endpoint/요청키/응답경로/성공코드/필드 매핑은 의도적으로 비어 있다. 따라서 키만 넣는 즉시 실수집 가능한 상태는 아니며, 실제 API 연결 검증은 데이터 담당이 수행해야 한다. 이 MVP에서는 HTTP mock과 기존 원본·수동파일로 경로를 검증했다. API 목록조회만으로 상세 지원조건이 확보됐다고 보지 않는다.

1. `config/*-api.example.json`을 복사하여 승인받은 공식 명세의 실제 값을 입력한다.
2. 환경변수 `FACILITY_API_KEY`, `FACILITY_API_CONFIG` 또는 `WELFARE_API_KEY`, `WELFARE_API_CONFIG`를 설정한다. `.env` 파일은 이름 참고용이며 이 CLI가 자동 로딩하지 않는다.
3. 수집 실행 후 `snapshot.json`의 source, field_map, records, collected_at을 전처리한다.

dot 경로를 쓰는 field_map은 정규화된 `id,title,text,provider,sido,sigungu,min_age,target,category,phone,address,lat,lon,crs,url,apply_period,base_date`에 대응한다. 좌표는 원본 CRS가 EPSG:4326으로 확인된 경우에만 보존한다.

수동 JSON 예시(실제 정책이 아닌 합성 자료):

```json
{
  "source": "faq_129",
  "is_sample": true,
  "collected_at": null,
  "records": [{"id": "TEST-1", "question": "합성 질문", "answer": "합성 답변", "url": "https://example.invalid"}]
}
```

시설 source는 facility_api, 정책은 welfare_api, FAQ는 faq_129다. FAQ Q+A는 묶어서 유지하되 길면 동일한 분할기를 쓴다. 합성 데이터는 is_sample=true로 식별하며 기본 출력에서 제외한다. 테스트에서만 --include-samples로 포함할 수 있다. 작은 합성 fixture는 테스트 중 임시 폴더에만 생성한다.

## M2 규칙

- 출력 한 줄: `{ "text": "...", "metadata": { ... } }`.
- 공통 필드: doc_id, source, doc_type, title, provider, sido, sigungu, min_age, target, category, phone, address, lat, lon, url, apply_period, base_date, collected_at, page, chunk_index, source_path, original_id, content_hash, is_sample.
- doc_id는 출처·원본 ID·PDF 페이지·청크 번호의 SHA256이다. 같은 원문/설정이면 재실행 ID와 출력이 같다. 내용 변경은 별도 content_hash로 추적한다. 청킹 설정 변경은 후속 인덱싱 단계에서 기존 청크 교체가 필요하다.
- XML은 파싱 후 HTML 엔티티를 추가 해제한다. `&#13;`은 항목 경계로 보존한다. 개요·지원대상·제외/예외·선정기준·지원내용·신청단계를 텍스트에 남긴다.
- 모든 포맷에 본문 700자(설정 범위 500~800, 제목 포함 상한을 위해 본문 최대719자), 겹침 100자를 적용한다. 청크마다 제목 최대80자를 붙이며 전체 최대800자다. 짧은 레코드는 분할하지 않고 마지막 청크는 500자 미만일 수 있다. 줄/공백 경계를 우선하지만 표·긴 자격조건의 의미 경계 보존은 수동 확인이 필요하다.
- 동일 안정 ID+동일 내용은 중복 제거. ID가 같은데 내용이 다르면 충돌로 실패한다. 별도 출처의 같은 정책을 자동 삭제하지 않는다.
- 모르는 값은 null, target 미확인은 빈 배열. '전체'는 명시된 입력에만 사용. min_age는 명시적 숫자 필드만 복사하고 자연어의 첫 숫자로 추정하지 않는다.
- 중앙부처 XML은 lifeArray에 노년 또는 정책명에 노인이 있으면 포함하는 MVP 휴리스틱. `--all-ages`로 해제할 수 있다. 누락·과포함 가능성이 있어 정책 선별 최종 검토가 필요하다.
- PDF 포털명·파일명이나 본문의 일부 지역명으로 적용지역을 추정하지 않는다. `--manifest config/source-manifest.json`으로 파일 상대경로별 provider/url/sido/base_date 등 확인된 정보를 넣을 수 있다. 모르면 null이다.
- crtrYr는 연도 값 그대로 base_date에 기록한다. 실제 수집일·발행일·신청마감일을 생성하지 않는다. 기존 원본의 수집일은 확인되지 않아 null이다.

## 통계·한계

report.json에 출처별 청크 수, 원본 정책 수, 필드별 null 비율, 건너뛴 파일, PDF의 빈 텍스트 페이지, 제외된 합성 레코드 수, 설정값을 기록한다. 빈 페이지는 표지일 수도 스캔본일 수도 있으므로 OCR 필요 여부를 사람이 확인한다. 실제 실행 통계는 progress.md를 참고한다.

이 단계는 수집·정제 MVP이며 RAG 검색·Qdrant 적재·자격판정·UI 연결은 구현하지 않았다. 시설/지자체 실API, 129 실제 원문 수집, PDF OCR·표 복원, 서로 다른 책자 중복 정책 통합, 모든 정책의 현재 적용 여부와 이용조건은 미검증이다. PDF 5개에는 노인 이외 정책·행정 지침이 섞일 수 있어 데이터 담당의 선별이 필요하다.

참고: [시설 API 출처](https://www.data.go.kr/data/15056929/openapi.do), [지자체복지서비스 XML 출처](https://www.data.go.kr/tcs/dss/selectApiDataDetailView.do?publicDataPk=15108347). 실명·키·개인정보를 넣지 않는다.
