# 지자체 복지정책 데이터 전처리 개선 결과

## 2026-11-26 광주 상세 정책 추가

- 원본: `전남광주통합특별시_복지서비스.zip` (2026-11-25 수신, 목록 555건, 정상 상세 515건).
- 광주 5개 구 47건, 시 단위 근거가 있는 21건, 교육청 2건 총 70건을 추가했다. 지원 범위와 신청 자격은 검토 대상이다.
- 통합 정책 4,497건, 고령층 검색 후보 2,197건, 정책 청크 2,485개. 광주 추가분은 후보 40건, 청크 49개다.
- 아래는 11월 25일 병합 기준선 기록이다. 최신 건수는 `quality_report.json`과 `data/rag/nationwide_v2/metadata_validation_report.json`을 참고한다.
- 재현: 11월 25일 기준선(`0c76ae4`)의 산출물을 준비한 뒤 `python scripts/add_gwangju_welfare.py ZIP경로`를 실행한다.

## 1. 작업 개요

- 작업일: 2026-11-25
- 기존 15개 지역 정책: 4,278건
- 기존 전남 선별 정책: 149건
- 최종 통합 정책: 4,427건
- 지역 분류 그룹: 16개
- 중복 정책 ID: 0건

기존 전남·광주 분리 기준을 유지하였으며,
전남 선별 데이터는 jeonnam 라벨로 통합하였다.
광주 및 신규 전남 전체 정책은 포함하지 않았다.

## 2. 주요 개선 사항

### 경기도 데이터 복구
- 누락된 상세정보 485건 추가
- 경기도 전체 정책 692건 확보

### 문의처 오류 수정
- 조회수(inqNum)를 문의처로 사용하던 오류 제거
- XML 원본 문의처 그룹 구조 보존
- 전화번호 정규화 모듈 추가
- 하이픈 없는 전화번호 및 축약 번호 처리 개선
- 검증되지 않은 연락처와 확정 연락처 구분

### 지역 필터 개선
- 기존 일부 지역 중심 필터 개선
- 통합 대상 16개 지역 그룹 보존
- 기존 jeonnam 라벨 유지
- 불확실한 지원 지역은 검토 대상으로 관리

### 노인 관련성 분류 개선
- API 생애주기 노년 태그 활용
- 노년 단독 태그와 복수 생애주기 태그 구분
- 기존 15개 지역 기준 416건 재분류
- 전체 정책 보존

## 3. 최종 노인 관련성 분류

| 분류 | 정책 수 |
|---|---:|
| direct | 899 |
| indirect | 1258 |
| review | 1257 |
| exclude_candidate | 1013 |
| 전체 | 4427 |

direct와 indirect를 합한 RAG 검색 후보는
총 2,157건이다.

## 4. 문의처 검증 상태

| 상태 | 정책 수 |
|---|---:|
| source_group_confirmed | 582 |
| legacy_candidate_review | 3666 |
| unknown | 179 |

source_group_confirmed는 원본 XML에 기록된
문의처임을 확인했다는 의미이다.

검증되지 않은 전화번호 후보는 확정 문의처로
사용하지 않는다.

## 5. 최종 데이터 파일

| 파일명 | 용도 |
|---|---|
| policies_all.jsonl | 전체 정책 보존 |
| policies_elderly_candidates.jsonl | RAG 검색 후보 |
| policies_review.jsonl | 관리자 검토 대상 |
| field_quality_report.csv | 필드별 품질 검사 |
| quality_report.json | 전체 검증 결과 |

## 6. 수정 및 추가된 코드

- run_pipeline.py
- collect_local_welfare.py
- normalize_policies.py
- region_selection.py
- elderly_filter.py
- contact_fields.py (신규)
- contact_phone_normalizer.py (신규)
- test_welfare_contact_region.py (신규)

## 7. 테스트 결과

기존 문의처 및 지역 관련 자동 테스트 8개 통과.

## 8. RAG 활용 방법

policies_elderly_candidates.jsonl을
노인복지 검색 후보 데이터로 활용한다.

전체 정책과 검토 대상은 별도로 보존한다.

노인 관련성 분류는 실제 신청 자격을
확정하는 분류가 아니므로 답변 생성 시
지원 대상 및 선정 기준을 추가 확인해야 한다.

## 9. 남은 과제

- 미검증 문의처 원본 추가 확보
- 미확보 문의처 확인
- 신청 방법 결측 정보 검토
- 지역 검색 범위 검증
- 광주 및 신규 전남 전체 정책 추가 여부 결정
- 전화번호 및 노년 분류 추가 회귀 테스트
- 최종 통합 과정의 재현 가능한 스크립트 작성
- 청킹 및 임베딩 재실행
- Qdrant 및 Neo4j 재적재
- RAG 검색 성능 평가
