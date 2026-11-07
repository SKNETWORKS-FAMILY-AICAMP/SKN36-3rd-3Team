# SKN36 · Splitting 직전 데이터 통합 결과 보고서

**기준일:** 2026-11-07
**기준 자료:** `SKN36-Data-Extraction - 복사본.zip`, 팀 공유 `RAG_데이터_통합_및_문서구조_설계(1).md`
**목표 범위:** 원본 수집 후 파싱 → 정규화 → 데이터 품질검증 → 정책/근거 문서 구조화 및 연결 후보 관리. **RAG Splitting·Embedding 전까지**.

## A. 완료/미완료 판단

| 단계 | 이번 ZIP으로 수행 | 결과 |
|---|---|---|
| 중앙부처 복지서비스 목록 파싱 | 완료 | 461건, 고유 ID 461건 |
| 중앙부처 상세 XML 파싱·연결 | 완료 | 299개 파싱·서비스 ID 검증 통과 |
| 중앙부처 목록+상세 공통 정책 모델 정규화 | 완료 | `policies.jsonl` 461행 |
| 반복 신청절차·법령·서식 보존 | 완료 | `central_detail_parsed.jsonl` 299행 |
| 필수 필드/미수집 상태/중복 정책 ID 자동 검증 | 완료 | 상세 미수집 162건, ID 중복 0건 |
| 노인 정책 후보 자동 분류(검수 전) | 완료 | 후보 142건, 미분류/검수 필요 319건 |
| 지자체 API 실데이터 정규화 | **미수행** | ZIP에 원본이 없음; 스크립트는 입력 경로 자동 인식 지원 |
| VWorld 시설 실데이터 정규화 | **미수행** | ZIP에 원본이 없음; 스크립트는 입력 경로 자동 인식 지원 |
| PDF 5종 본문·표 추출 및 섹션 구조화 | **미수행** | ZIP에 원본이 없음; PDF 입력 시 실행 가능 |
| 정책↔PDF 연결 후보 생성 | **대기** | PDF 부재로 후보 0건, 빈 CSV 스키마 제공 |
| RAG splitting/청킹 | **범위 제외** | `policy_chunks.jsonl` 등 미생성 |
| Embedding/VectorDB | **범위 제외** | Qdrant·Chroma·PostgreSQL 미적재 |

## B. 원본 데이터 정합성

- ZIP 내부 중앙부처 목록 JSON 461개 정책의 `servId`가 모두 고유함.
- 상세 XML 299개가 모두 XML 파싱 가능하고 API 응답 성공코드(`resultCode=0`)를 포함함.
- 상세 XML 299개 파일명이 각 XML 본문의 `servId`와 일치하고, 목록에도 그 ID가 있음.
- 원문 URL 461건의 형식 검사에서 유효하지 않은 URL은 0건 확인됨 (실제 웹 연결성 테스트는 수행하지 않음).
- 상세 XML이 없는 162개 목록 항목은 유지하되 지원 대상·선정 기준·지원 내용·신청방법을 **추정해서 채우지 않음**.
- 299개 상세정보의 주요 검색 관련 필드는 구조적으로 파싱됐지만, 정책 기준금액과 실제 신청조건을 원문·법령과 일일이 대조한 것은 아님.
- API 자료의 제공 범위를 지역 `national`로 임의 확정하지 않고 `region_scope=unknown`, 검수 상태 `pending` 처리함.
- 노인 관련성 142건은 **키워드/생애주기 기준의 검토 후보**이지 정책의 확정 포함 범위나 지원 자격이 아님.

## C. 구현한 핵심 규칙

1. **원본 보존**: 입력 `data/raw/`는 읽기만 한다. 출력은 `data/staging/`, `data/processed/`, `data/validation/`.
2. **정보 원천 구분**: 중앙부처는 `central:WLF...`, 지자체는 `local:WLF...`, VWorld는 `vworld:LT...` 식별자를 부여한다. 원래 ID도 보존.
3. **목록+상세 병합**: 중앙부처의 `tgtrDtlCn`, `slctCritCn`, `alwServCn`, `applmetList`와 지자체의 `detail_sprtTrgtCn` 등 별도 매핑.
4. **반복 필드 보존**: XML `<applmetList>` 반복 요소를 리스트로 유지해 신청·심사·결정 순서가 사라지지 않도록 한다.
5. **누락/일정 처리**: 자격요건 미확보는 `null`; 종료일 `99991231`은 `end_date=null`, `end_date_status=open_or_placeholder`로 별도 기록한다.
6. **지역 신뢰성**: 시군구가 비었다고 시도 전체 사업으로 추정하지 않는다. `region_scope=unknown`, `region_validation_status=pending`.
7. **PDF**: 실제 입력이 있을 때 PDF 목차/북마크가 있으면 해당 페이지 범위로 논리적 섹션, 없으면 페이지 단위 잠정 구조를 만든다. 모든 섹션은 검수 대기이며 **RAG 청크가 아니다**.
8. **연결 후보**: 문서에 정책명이 등장해도 연결을 자동 승인하지 않는다. PDF가 있을 때 후보만 `policy_source_links.csv`에 기록하고 검수 대기.
9. **시설**: 시설명·주소·좌표를 정책 정보와 별도의 `facilities.jsonl`로 관리한다. 시설을 특정 정책 수행기관이라고 추정하지 않는다.

## D. Splitting 전에 반드시 확인할 것

- [ ] 지자체 복지서비스 목록/상세 원본과 시설 원본을 **동일한 로컬 작업 브랜치**에 확보한다.
- [ ] PDF 5종을 확보하고 텍스트/표/페이지 추출이 정상인지 점검한다.
- [ ] 분할 전의 `guideline_sections.jsonl`이 실제 사업·장·절 경계를 올바르게 보존하는지 일부 또는 전체 샘플 검수한다.
- [ ] 정책별 지역 적용 범위를 원문으로 확인한다. `unknown` 상태를 자동으로 전국/시도 정책으로 바꾸지 않는다.
- [ ] `detail_fetched=false` 162건의 미수집 상태를 유지하거나 상세자료를 추가 수집한다.
- [ ] 표·금액·연령·신청기한처럼 답변 오류의 위험이 높은 정보는 PDF 원본 페이지와 대조한다.
- [ ] 정책↔PDF 연결 후보는 관련 사업·적용 대상·기준연도를 확인하고 `approved/rejected`로 검수한다.
- [ ] `quality_report.json`, `missing_fields.csv`, `region_review_queue.csv`를 확인한다.

## E. 다음 단계의 경계

아직 생성하지 않은 결과물은 `policy_chunks.jsonl`, `guideline_chunks.jsonl`, 임베딩 벡터, 벡터 DB 색인이야. 이 산출물이 생성되기 **직전**의 입력은 검수된 `policies.jsonl` + 검수된 `guideline_sections.jsonl` + 승인된 `policy_source_links.csv`야.

지금 확보된 ZIP만으로는 **중앙부처 정책의 정규화 단계는 완료**했지만 **팀 전체 데이터 통합 및 PDF 논리적 구조화의 완료 조건은 아직 충족하지 못한 상태**야.
