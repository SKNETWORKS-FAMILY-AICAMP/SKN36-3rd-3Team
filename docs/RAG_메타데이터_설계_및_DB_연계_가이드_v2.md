# RAG 메타데이터 설계 및 DB 연계 가이드 v2

## 1. 데이터 구성

검토 버전은 `nationwide_2026_11_26_6efc3b7671b3`입니다. 전체 정책 4,833건 중 노인 후보 2,243건을 정책 문서와 그래프로 구성했습니다. 정책 청크는 2,551개이고, PDF 안내서 문서 1,189개에서 온 청크는 2,738개입니다.

## 2. 메타데이터

| 영역 | 필드 | 처리 규칙 |
|---|---|---|
| 공통 | `source_id`, `source_url`, `source_type`, `data_version`, `approval_status` | 정책 원본 유형은 `local_welfare_api`. 정책과 PDF 모두 승인 상태를 기록합니다. |
| 적용 지역 | `sido_name`, `sigungu_name`, `region_scope`, `candidate_scope`, `scope_status`, `applies_to` | 통합시 표준명과 원문을 각각 보존합니다. 확인되지 않은 범위는 `region_scope=unknown`으로 두고 후보를 검색 보조에 사용합니다. 그래프도 동일한 적용 범위를 사용합니다. |
| 신청 | `application_text`, `application_method_name`, `application_required`, `application_basis` | 원문에 직접 신청 여부가 명시된 경우에만 참·거짓을 기록합니다. 출처·원문 문장·확인일을 기록하며 대상자 결정 등 선행 조건을 보존합니다. 정책 그래프의 `application`에도 같은 네 값을 그대로 둡니다. |
| 문의처 | `contact`, `contact_status`, `contact_candidates`, `contact_details` | `contact`와 본문에는 XML 그룹에서 확인한 번호를 사용합니다. 상태는 `source_group_confirmed`, `legacy_candidate_review`, `unknown`입니다. `view_count`는 조회수입니다. |
| 그래프 기관 | `agencies` | 담당 부서는 `responsible_department`로 저장합니다. 신청 기관 관계는 신청 원문에서 확인된 경우에만 부여합니다. |

## 3. 검색과 답변

정책과 PDF 청크에 공통 버전을 사용합니다. 지역 별칭은 검색과 위치 분류에 사용하며, 본문 지역 표기는 표준 행정명으로 유지합니다. 자동 추출된 연령·지원 필요 태그·적용 지역 후보는 검색 보조에 사용합니다. 신청 정보가 비어 있으면 “신청 방법 정보가 없어요. 담당 부서에 문의해 주세요”로 안내합니다.

## 4. 승인과 반영

1. 최초 공개는 관리자가 최종 검증 후 `release_manifest.json`을 승인한 뒤 진행합니다. 공개 답변에는 버전 매니페스트의 `public_fields`를 사용합니다. 표본 검증 범위를 그대로 표시합니다.
2. 이후 정책이 갱신되면 Django 관리자에서 정책별 승인·반영을 마칠 때까지 이전 승인본을 사용합니다. 정책별 검토를 마친 경우 `approval_status=approved`로 기록하고 “자료 검토 완료”로 표시합니다.

## 5. 검증 항목

- 신청 방법 빈칸에서는 신청 필요 여부를 미확정으로 유지합니다.
- 평탄화된 문의처 배열의 순서를 근거로 번호를 확정하지 않습니다. 조회수와 후보 번호는 본문에 넣지 않습니다.
- PDF 출처만으로 승인 상태를 변경하지 않습니다.
- 정책·청크 ID 중복, 문서와 그래프의 지역 범위 일치, 승인 매니페스트 해시를 확인합니다.

## 6. 파일 위치

- `data/processed/local_welfare/nationwide/final_v3/`에는 전체·노인 후보 정책과 갱신 전 통합시 정책 이력이 있습니다.
- `data/rag/nationwide_v3/`에는 정책·PDF 문서와 청크, 정책 그래프, 검증 보고서와 승인 매니페스트가 있습니다.
