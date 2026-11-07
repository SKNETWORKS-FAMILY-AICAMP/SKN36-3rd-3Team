# 노인 복지 맞춤형 RAG 챗봇 — 데이터 통합 및 문서 구조 설계

> 버전: v0.1 | 작성일: 2026-11-07  
> 범위: 첨부된 지자체 복지서비스 API 수집 파일, VWorld 노인복지시설 데이터, 2026년 보건복지부 PDF 5종  
> 목표: **PDF와 API JSON을 물리적으로 무작정 합치지 않고**, 공통 정책 모델과 출처 연결 테이블을 구축해 신뢰 가능한 지역별 RAG 검색 지원

## 1. 핵심 결론

- **지자체 복지서비스 API** → `policies` 테이블의 중심 데이터. 지역·대상·선정기준·급여·신청방법은 정형 컬럼으로 저장.
- **보건복지부 PDF** → `source_documents` 및 `guideline_chunks`로 보존. 정책의 제도적 배경·자격·예외·신청 절차를 설명하는 **근거 문서**로 활용.
- **VWorld 노인복지시설** → `facilities` 별도 테이블. 정책과 혼합하지 않고 관련 서비스나 지역을 통해 연결.
- **정책↔PDF 연결** → 정책명이 유사하다고 자동 확정하지 않음. `policy_source_links`에 관련성, 매칭 방식, 신뢰도, 검수 여부를 기록.
- **RAG** → API 정책 검색문서 + PDF 근거 청크를 Qdrant에 각각 색인하고, PostgreSQL의 공통 ID/지역 코드로 연결하는 **하이브리드 검색**.

## 2. 실제 확보 자료 및 품질 점검

### 2.1 API·시설 파일

| 출처 | 실제 파일 | 확인된 건수 | 주의 사항 |
|---|---|---:|---|
| 서울 지자체 서비스 | `welfare_seoul_full_20261107_103452.csv` | 397 | 상세정보 수집 완료 |
| 경기 지자체 서비스 | `welfare_gyeonggi_full_20261107_103452.csv` | 692 | **485건 상세정보 미수집** (`detail_fetched=False`) |
| 전북 지자체 서비스 | `welfare_jeonbuk_full_20261107_103452.csv` | 396 | 상세정보 수집 완료 |
| 전체 지자체 서비스 | 위 3개 통합 | **1,485** | `servId` 기준 고유 1,485건; 상세 수집 1,000건 |
| VWorld 노인복지시설 | 지역별 `*_elderly_welfare.json` | 서울 4 / 경기 43 / 전북 57 / 전남 60 | 현재 수집 결과이며 시설 전체 모집단을 보장하지 않음 |

- 지자체 API ZIP에는 CSV 외에 `welfare_detail_cache.jsonl`, `welfare_detail_errors.csv`가 있음. **JSONL 캐시는 상세 응답 원본/재처리용**, CSV는 정규화 입력으로 사용.
- `welfare_detail_errors.csv`에 48개 행이 있으나, 이것을 `detail_fetched=False` 485건과 동일한 개념으로 해석하면 안 됨. 목록은 확보했지만 상세 데이터 미수집인 경기 485건을 **우선 재호출**해야 함.
- 전남은 **VWorld 시설 데이터는 있지만 첨부 지자체 서비스 API에는 없음**. 지역별 정책 검색 범위를 명시하거나 추가 수집해야 함.
- 노인 정책 외 다자녀·장애인·청년 등도 포함되어 있음. `노인` 키워드만으로 무조건 제외하지 말고 고령자에게 적용 가능한 저소득·의료·장애 관련 서비스도 선별 검토.

### 2.2 PDF 5종

| 원본 PDF | 중점 활용 | 처리 방식 |
|---|---|---|
| `2026년 기초연금 사업안내.pdf` | 수급권자 범위, 신청, 선정·소득·재산 조사, 연금액, 지급 | 제도·장·절 기반으로 분할; 기준수치/예외는 표와 본문 함께 보존 |
| `2026_노인보건복지사업안내(1권).pdf` | 노인일자리, 경로당, 노인맞춤돌봄, 치매 등 | **사업(예: 3-1)** 중심 문서 분할 |
| `2026_노인보건복지사업안내(2권).pdf` | 노인주거·의료·재가복지, 장기요양 | 시설 유형/대상/입소절차별 분할 |
| `2026 나에게 힘이 되는 복지서비스_표지합본 최종.pdf` | 복지서비스 전반을 이용자 친화적으로 요약 | 서비스명·주제별 분할; 노령층 외 연관 사업 선별 |
| `2026 나에게 힘이 되는 복지서비스_분권(노령층).pdf` | 노령층 대상 35개 서비스 안내 | **서비스 1개 = 논리적 문서 1개** 원칙 |

**중복 주의:** 종합본과 노령층 분권의 상당 부분이 내용상 중복될 수 있음. 두 PDF 원본은 모두 보존하되 검색 색인에서는 유사/중복 청크를 그룹화하고 우선 출처를 정해야 함. 기초연금처럼 요약 안내와 상세 지침이 동시에 있는 경우에는 둘을 같은 정책에 연결하되 전문 지침을 우선 근거로 사용.

## 3. 통합 방법: 공통 스키마 + 연결 ID

### 3.1 API → `policies` 정규화

| 통합 필드 | 실제 API 원본 필드 | 처리 규칙 |
|---|---|---|
| `policy_id` | `servId` | 원본 ID 보존, PK |
| `title` | `servNm` | 문자열 정규화, 원본 별도 보존 |
| `summary` | `servDgst` 또는 `detail_servDgst` | 상세값 우선, 없으면 목록값 |
| `sido_name` | `ctpvNm` / `detail_ctpvNm` | 표준 지역명으로 변환 |
| `sigungu_name` | `sggNm` / `detail_sggNm` | 지역명이 있는 경우만 |
| `region_scope` | 원본 지역 정보로 추론 | `national/sido/sigungu/unknown` 중 확인된 범위만 부여 |
| `target_text` | `detail_sprtTrgtCn` | 누락이면 `null`, 추정 금지 |
| `selection_criteria_text` | `detail_slctCritCn` | 누락이면 `null` |
| `benefit_text` | `detail_alwServCn` | 원문 유지 |
| `application_text` | `detail_aplyMtdCn` | 원문 유지 |
| `start_date`, `end_date` | `detail_enfcBgngYmd`, `detail_enfcEndYmd` | 날짜 파싱, 불확실 시 null |
| `department` | `detail_bizChrDeptNm` / `bizChrDeptNm` | 원문 보존 |
| `contact` | `detail_inqNum` / `inqNum` | 문자열 보존 |
| `source_url` | `servDtlLink` | 가능한 한 완전한 URL 보존·유효성 검사 |
| `updated_at_source` | `detail_lastModYmd` / `lastModYmd` | 원본 수정일 |
| `detail_fetched` | `detail_fetched` | 상세 수집 성공 여부; `False`면 불완전 레코드로 표시 |

**중요:** 상세정보가 없는 경우 `summary`로 자격 조건을 보충해 만들어내면 안 됨. `age_min`, 소득 조건 등의 기계 판정 필드는 **별도 추출 필드**로 두고 근거문장/검증 상태까지 함께 저장.

### 3.2 PDF → `source_documents` + `guideline_sections` + `guideline_chunks`

PDF는 API의 `servId`가 없으므로 별도의 식별자를 생성.

```json
{
  "document_id": "mohw_basic_pension_2026",
  "title": "2026년 기초연금 사업안내",
  "publisher": "보건복지부",
  "publication_year": 2026,
  "document_type": "official_guideline",
  "file_name": "2026년 기초연금 사업안내.pdf",
  "source_file_hash": "<SHA256>",
  "version_status": "current_as_collected"
}
```

PDF 1개의 논리적 사업 섹션 구조 예시:

```json
{
  "section_id": "mohw_basic_pension_2026::application_method",
  "document_id": "mohw_basic_pension_2026",
  "program_name": "기초연금",
  "section_title": "신청방법 및 신청기간",
  "page_start": null,
  "page_end": null,
  "text": "<PDF에서 실제 추출한 원문>",
  "extraction_method": "pymupdf",
  "review_status": "pending"
}
```

- `page_start/end`는 **PDF 파일 페이지 번호 기준**으로 확정. 책자에 인쇄된 페이지 숫자와 다를 수 있으므로 둘을 따로 보관할 수 있음.
- 표(선정기준·급여액)는 텍스트가 뒤섞일 수 있음. **표를 행·열 구조로 별도 추출**하고 PDF 원본과 대조.
- 본문 전체를 500자씩 자르는 것보다 `장 → 사업 → 대상/내용/신청/예외` 기준으로 논리적 분할 후 긴 섹션만 추가 청킹.
- 각 청크에 `document_id`, `section_id`, `chunk_id`, `page_start/end`, `publication_year`, `source_text`를 부여.

### 3.3 API 정책과 PDF 문서 연결 — `policy_source_links`

**서로 다른 출처의 문서를 하나의 레코드로 덮어쓰지 말고 링크 테이블로 연결**한다.

| 필드 | 의미 |
|---|---|
| `policy_id` | 지자체 API `servId` 또는 별도 생성된 국가사업 ID |
| `section_id` | PDF의 사업/절 식별자 |
| `relation_type` | `same_program` / `general_guideline` / `related` / `conflicting` |
| `match_method` | `exact_alias` / `keyword_candidate` / `semantic_candidate` / `manual` |
| `match_confidence` | 후보 점수. 확정 판단과 분리 |
| `review_status` | `pending` / `approved` / `rejected` |
| `review_note` | 연결 근거 및 판단 이력 |

매칭 절차:

1. **정책명 정규화**: 공백·괄호 표기·연도·별칭 정리 (`기초연금제도` ↔ `기초연금`).
2. **정확 매칭 우선**: 표준 사업명/별칭/담당부처/지원대상·사업목적 등을 같이 확인.
3. **유사도 기반 후보 생성**: 검색모델로 3~5개 후보를 만들되 확정하지 않음.
4. **의미 검증**: 정책 주체, 사업 대상, 혜택 종류, 적용 지역, 기준연도 충돌 여부 검사.
5. **검수 후 링크 확정**: `review_status=approved`인 링크만 답변의 확정 근거로 활용.
6. **관련 문서 부재 허용**: 매칭되는 PDF가 없으면 API 정책만으로 인덱싱하되 `source_coverage=api_only` 표시.

#### 연결 예시 (개념 예시, 확정 매칭 아님)

```text
정책: 기초연금 (정규화된 국가사업 엔터티)
 ├─ [요약] 2026 나에게 힘이 되는 복지서비스_분권(노령층).pdf / 기초연금제도
 └─ [전문] 2026년 기초연금 사업안내.pdf / 신청방법·선정기준·지급액
```

> 지자체 API에 동일 사업이 있다는 사실은 별도 확인이 필요함. 위 예시는 PDF 간 **개념적 연결 형태**를 설명하기 위한 것임.

### 3.4 VWorld → `facilities` (정책과 분리)

| 통합 필드 | 실제 VWorld 필드 |
|---|---|
| `facility_id` | `_feature_id` |
| `name` | `fac_nam` |
| `facility_type` | `cat_nam` |
| `address_road` | `fac_n_add` |
| `address_lot` | `fac_o_add` |
| `phone` | `fac_tel` |
| `latitude`, `longitude` | 동일 이름 |
| `sido_name` | `region` |

- `facility_id` 기준 중복 제거. 과거 주소(예: `여주군`)는 최신 행정구역 코드와 매핑 필요.
- 시설과 복지정책의 **실제 신청·수행 기관 관계는 원본 근거가 있을 때만 연결**. 같은 시군구라는 이유만으로 특정 정책의 운영기관이라고 단정하지 않음.
- 공간 검색은 SQL/PostGIS(또는 좌표 기반 거리 계산), 시설 설명 검색만 선택적으로 벡터 활용.

## 4. RAG용 문서 생성 규칙

### 4.1 API에서 만들 `policy_chunks.jsonl`

정책당 기본 검색 문서 1개를 만들고, 내용이 길면 `지원대상/선정기준`, `지원내용`, `신청방법` 단위로 추가 분할.

```json
{
  "chunk_id": "policy::WLF00000001::overview",
  "record_type": "policy",
  "policy_id": "WLF00000001",
  "text": "사업명: <원문>\n지역: <시도·시군구>\n지원대상: <원문>\n선정기준: <원문>\n지원내용: <원문>\n신청방법: <원문>",
  "metadata": {
    "sido_name": "경기도",
    "sigungu_name": "<실제 시군구명>",
    "region_scope": "sigungu",
    "source_type": "local_welfare_api",
    "detail_fetched": true
  }
}
```

`WLF00000001`은 **스키마 설명용 가상 ID**. 실제 생성 시 원본 `servId`를 사용.

### 4.2 PDF에서 만들 `guideline_chunks.jsonl`

```json
{
  "chunk_id": "guideline::mohw_basic_pension_2026::section_01::chunk_01",
  "record_type": "guideline",
  "document_id": "mohw_basic_pension_2026",
  "section_id": "mohw_basic_pension_2026::section_01",
  "program_name": "기초연금",
  "text": "<실제 PDF 원문>",
  "metadata": {
    "page_start": 1,
    "page_end": 2,
    "year": 2026,
    "document_type": "official_guideline"
  }
}
```

페이지 숫자는 예시이며 실제 처리에서 확정해야 함. **각 벡터의 원문 출처 및 페이지를 항상 보존**.

### 4.3 중복·충돌 관리

- **완전 중복**: 문서 해시/정규화 문장 해시로 식별. 원본은 유지, 색인은 중복 억제.
- **부분 중복**: 같은 사업의 일반 요약 vs 전문 지침은 둘 다 유지하고 동일 사업에 링크.
- **기준 불일치**: `conflicts.jsonl`에 `field`, `source_a`, `source_b`, `year`, `resolution_status` 기록.
- **우선순위**: 같은 연도·동일 제도라면 구체적 공식 사업지침을 우선 참고하되, 개별 지자체 사업의 실제 신청 자격은 지자체 원문과 적용 지역을 우선 확인. 어느 쪽도 임의로 덮어쓰지 않음.
- **날짜 필터**: 시행기간이 종료됐거나 검증되지 않은 사업은 답변에서 상태·확인 필요 표시.

## 5. 권장 PostgreSQL 논리 테이블

```text
regions (region_code, sido_name, sigungu_name, aliases)
    ├─ policies (policy_id, region_code, eligibility..., source_url, detail_fetched)
    └─ facilities (facility_id, region_code, name, address, lat, lon...)

source_documents (document_id, title, year, file_hash, source_type...)
    └─ guideline_sections (section_id, document_id, program_name, pages, text...)
          └─ guideline_chunks (chunk_id, section_id, text, embedding_status...)

policy_source_links (policy_id, section_id, relation_type, review_status...)
policy_chunks (chunk_id, policy_id, text, embedding_status...)
ingestion_runs (run_id, source, started_at, processed_rows, errors...)
```

- `regions`의 행정구역 코드는 가능하면 **법정동/행정구역 코드에 맞춘 검증된 코드** 사용; 이름만으로 동명이인 지역을 판별하지 않음.
- Qdrant 컬렉션 예: `policy_chunks_v1`, `guideline_chunks_v1`.
- Qdrant payload에는 `policy_id`/`document_id`/`section_id`/`region_code`/`year`를 보존해 PostgreSQL의 원본 정보를 다시 조회할 수 있도록 설계.

## 6. 최종 저장 폴더·파일 구조

```text
elderly-welfare-rag/
├── README.md
├── .env.example
├── requirements.txt
├── configs/
│   ├── source_registry.yaml          # 파일별 출처·연도·업데이트 정보
│   ├── column_mapping.yaml          # API/VWorld 컬럼 → 공통 필드
│   ├── region_aliases.yaml          # 전북/전라북도 등 지역명 정규화
│   └── policy_aliases.yaml          # 기초연금제도/기초연금 등 사업명 별칭
│
├── data/
│   ├── raw/                         # 원본 절대 수정 금지
│   │   ├── local_welfare/
│   │   │   ├── welfare_*_full_*.csv
│   │   │   ├── welfare_detail_cache.jsonl
│   │   │   └── welfare_detail_errors.csv
│   │   ├── vworld/
│   │   │   ├── *_elderly_welfare.json
│   │   │   └── *_elderly_welfare_geojson.json
│   │   └── pdf/
│   │       ├── 2026년 기초연금 사업안내.pdf
│   │       ├── 2026_노인보건복지사업안내(1권).pdf
│   │       ├── 2026_노인보건복지사업안내(2권).pdf
│   │       ├── 2026 나에게 힘이 되는 복지서비스_표지합본 최종.pdf
│   │       └── 2026 나에게 힘이 되는 복지서비스_분권(노령층).pdf
│   │
│   ├── staging/                     # 1차 파싱 및 원문 보존
│   │   ├── local_welfare_merged.jsonl
│   │   ├── vworld_merged.jsonl
│   │   ├── pdf_pages.jsonl
│   │   └── pdf_tables.jsonl
│   │
│   ├── processed/                   # 검증된 통합 데이터
│   │   ├── policies.jsonl
│   │   ├── facilities.jsonl
│   │   ├── source_documents.jsonl
│   │   ├── guideline_sections.jsonl
│   │   ├── policy_source_links.csv
│   │   └── policy_aliases.json
│   │
│   ├── rag/                         # 임베딩 투입 대상
│   │   ├── policy_chunks.jsonl
│   │   ├── guideline_chunks.jsonl
│   │   └── index_manifest.json
│   │
│   └── validation/
│       ├── missing_detail_policies.csv
│       ├── duplicates.csv
│       ├── link_review_queue.csv
│       ├── conflicts.jsonl
│       └── quality_report.json
│
├── scripts/
│   ├── 01_inspect_sources.py
│   ├── 02_normalize_local_welfare.py
│   ├── 03_normalize_vworld.py
│   ├── 04_extract_pdf.py
│   ├── 05_split_pdf_sections.py
│   ├── 06_match_policies_to_pdf.py
│   ├── 07_validate_integrated_data.py
│   ├── 08_build_rag_chunks.py
│   ├── 09_load_postgres.py
│   └── 10_index_qdrant.py
│
├── src/
│   ├── db/                          # PostgreSQL 스키마·쿼리
│   ├── retrieval/                   # 지역 필터 + hybrid search
│   ├── generation/                  # LLM 응답 + 출처 출력
│   └── api/                         # FastAPI endpoints
│
└── tests/
    ├── test_schema.py
    ├── test_region_filter.py
    ├── test_policy_pdf_matching.py
    └── test_rag_citations.py
```

> 위 폴더 구조는 **향후 구현할 목표 구조**이며, 현재 첨부된 ZIP/PDF에서 이미 존재하는 파일과 앞으로 생성할 파일을 함께 표시했다. `scripts/`, `src/`, `tests/` 등은 아직 작성된 코드가 아님.

## 7. ETL 및 색인 실행 순서

```text
원본 ZIP / PDF
    │
    ├─ 지자체 API CSV / JSONL ──→ 컬럼 매핑 · 지역 정규화 ──→ policies.jsonl
    │                                                          │
    ├─ VWorld JSON ────────────→ 주소 정규화 ───────────────→ facilities.jsonl
    │
    └─ PDF 5종 ───────────────→ 텍스트/표 추출 ──→ 사업·절 분할 ──→ guideline_sections.jsonl
                                                               │
policies.jsonl + guideline_sections.jsonl ──→ 정책명 후보 매칭 · 검수
                                                               │
                                                     policy_source_links.csv
                                                               │
                              ┌────────────────────────────────┴───────────────┐
                              ▼                                                ▼
                      정책 텍스트 생성                                   PDF 청크 생성
                      policy_chunks.jsonl                              guideline_chunks.jsonl
                              │                                                │
                              └──────────── Qdrant 각각 색인 ──────────────────┘
                                                │
                                    FastAPI + PostgreSQL 연동
                                                │
                                사용자 지역·상황별 근거 있는 응답
```

## 8. 챗봇 검색 흐름

사용자 질의 예시: `수원시에 사는 72세 독거노인인데 생활비 지원을 받고 싶어요.`

1. 질의에서 `지역=경기 수원시`, `나이=72`, `가구=독거`, `관심=생계` 추출.
2. `policies`에서 지역 범위를 고려해 후보 검색: 수원시 대상 + 경기도 전체 대상 + 전국 공통 사업(해당 데이터가 있을 때만).
3. `policy_chunks_v1`에서 의미 검색; 상세정보가 없는 정책은 근거 수준을 낮추거나 추가 확인 표시.
4. 연결이 승인된 `guideline_chunks_v1`에서 대상·기준·신청 절차·예외 정보를 확보.
5. 자격 정보는 **충족/미충족/정보 부족**으로 구분. 소득·재산 등 누락 조건은 자동 확정 금지.
6. 사용자가 주변 기관을 원하면 `facilities`를 위치로 검색. 해당 시설이 정책 시행기관인지는 별도 확인.
7. 답변에는 정책명, 대상·혜택, 신청방법, **API 링크 또는 PDF 문서명·페이지**, 확인이 필요한 조건을 제시.

## 9. 우선순위 및 완료 기준

### P0 — 데이터 통합 전 필수

- [ ] 경기의 `detail_fetched=False` **485건** 상세 데이터 재수집/실패 사유 기록
- [ ] 전남 지자체 정책 API 수집 여부 결정 또는 현 수집 범위를 사용자에게 명시
- [ ] 지역명/시군구 코드 표준화, 시행기간·수정일 파싱 검증
- [ ] PDF 표/수치/예외 조건의 파싱 정확도 샘플 검수
- [ ] PDF 종합본·노령층 분권 중복 관계 확인

### P1 — 통합 산출물

- [ ] `policies.jsonl` 생성 (`policy_id` 고유성 검사)
- [ ] `facilities.jsonl` 생성 (중복 좌표·과거 주소 검사)
- [ ] `source_documents.jsonl`, `guideline_sections.jsonl` 생성 (페이지 추적 가능)
- [ ] `policy_source_links.csv` 생성 (자동후보/검수완료 구분)
- [ ] `policy_chunks.jsonl`, `guideline_chunks.jsonl` 생성

### P2 — RAG 검증

- [ ] 지역 필터가 다른 시군구 정책을 잘못 추천하지 않는지 테스트
- [ ] 2026년 기준 선정조건·예외·신청절차를 원문과 대조
- [ ] 출처 없는 수치/신청자격을 생성하지 않는지 확인
- [ ] 검색된 PDF 페이지 및 API 링크를 통해 사용자가 근거를 확인할 수 있는지 확인
- [ ] 미수집·기한종료·데이터 없음에 대한 안내 문구 테스트

## 10. 설계 의사결정 정리

| 질문 | 결정 |
|---|---|
| PDF와 API JSON을 하나의 JSON으로 합칠까? | **아니요.** 각각 정규화하고 공통 ID·링크 테이블로 연결 |
| 같은 사업이 API와 PDF에 동시에 있으면? | 원문 모두 보존, 승인된 `policy_source_links`로 연결 |
| 모든 PDF를 바로 임베딩할까? | 사업/절 분할·표 검수·중복 정리 후 인덱싱 |
| 지역별 RAG DB를 따로 만들까? | 우선 **공용 컬렉션 + `region_code` metadata 필터** |
| 시설정보를 정책 문서에 복사해 넣을까? | 아니요. 시설은 별도 테이블로 검색하고 필요 시 조합 |
| Neo4j도 바로 도입할까? | 첫 버전은 PostgreSQL + Qdrant로 시작; 복잡한 관계탐색이 필요할 때 도입 |
| PDF와 API의 기준이 다르면? | 연도·범위·출처를 비교하고 충돌로 기록, 임의 병합 금지 |

---

**최소 구현 범위(MVP):** 서울·경기·전북 API 정책 + PDF 5종을 정규화하고, VWorld 시설은 별도 검색 기능으로 유지. `policies.jsonl` → `policy_source_links.csv` → `policy_chunks.jsonl` 순서로 완성한 후 Qdrant에 색인한다.
