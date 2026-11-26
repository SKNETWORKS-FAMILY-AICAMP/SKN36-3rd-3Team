# v3 생성 입력과 검증 기록 (2026-11-26)

`data/rag/nationwide_v3/`와 `data/processed/local_welfare/nationwide/final_v3/`를 만든 입력과, 그 결과를 검증한 기록입니다.

| | |
|---|---|
| 버전 | `nationwide_2026_11_26_6efc3b7671b3` |
| 기준 정책·PDF·그래프 | 커밋 `0c76ae4` |
| 생성 코드 | `scripts/regenerate_v3.py` + `src/rag`, `src/welfare_preprocessing` |

## 폴더

| 폴더·파일 | 내용 |
|---|---|
| `changes/region_changes.jsonl` | 지역 변경 목록 (12,330줄) |
| `changes/contact_changes.jsonl` | 문의처 변경 목록 (6,600줄) |
| `changes/application_changes.jsonl` | 신청 방법 변경 목록 (625줄) |
| `changes/team3-stage-checked.jsonl` | 통합시 1단계 생성본 555건 (원본 상세 515 + 추가 XML 40). SHA-256 `ac13990912c6ec80d9ffde08f42006d4fad9375315c6a749f570696fb9b67e28` |
| `changes/region_scope_unresolved.csv` | 원문이 등록 시군구와 달라 적용 지역을 비워 둔 3건 |
| `changes/contact_unresolved.csv` | 문의처 미해결 82건 |
| `changes/application_unresolved.csv` | 신청 방법 미확정 658건 |
| `audit/` | 표본 대조, 통합시 515건 대응표, 수정 전후 비교(`fix1_*`), 검증 보고서 |

`audit/region/region_unresolved.csv`는 **수정 전 상태를 남긴 기록**입니다. 지금 값과 다른 줄이 있습니다. 지금 상태는 `final_v3/policies_all.jsonl`을 봅니다.

추가 상세 XML 원본은 `data/raw/local_welfare/detail_xml_2026-11-26.zip`, 통합시 원본은 `data/raw/local_welfare/local_welfare_service_outputs/전남광주통합특별시_복지서비스.zip`에 있습니다.

## 다시 만들기

기준 파일 5개는 저장소 용량 때문에 여기 넣지 않았습니다. 커밋 `0c76ae4`에서 꺼내 씁니다. 저장소 루트에서 실행합니다 (Git Bash 기준).

```bash
IN=/tmp/v3_inputs; OUT=/tmp/v3_out        # OUT 은 비어 있는 새 폴더
mkdir -p "$IN" && cp data/staging/local_welfare/2026-11-26/changes/* "$IN/"
git show 0c76ae4:data/processed/local_welfare/nationwide/final/policies_all.jsonl                > "$IN/contact-all.jsonl"
git show 0c76ae4:data/processed/local_welfare/nationwide/final/policies_elderly_candidates.jsonl > "$IN/contact-elder.jsonl"
git show 0c76ae4:data/rag/nationwide_v2/guideline_chunks.jsonl        > "$IN/v3-guideline_chunks.jsonl"
git show 0c76ae4:data/rag/nationwide_v2/guideline_documents.jsonl     > "$IN/v3-guideline_documents.jsonl"
git show 0c76ae4:data/rag/nationwide_v2/policy_graph_entities.jsonl   > "$IN/v3-policy_graph_entities.jsonl"
PYTHONPATH=src python -B -X utf8 scripts/regenerate_v3.py --inputs "$IN" --output "$OUT"
```

출력의 `data/rag/nationwide_v3/release_manifest.json`이 저장소의 것과 같은 버전·같은 해시면 재현된 것입니다. 2026-11-26에 이 순서로 다시 만들어 버전과 해시 9개가 모두 같음을 확인했습니다.

PowerShell의 `>`는 파일 인코딩을 바꿀 수 있으니 위 명령은 Git Bash에서 실행합니다.

## 검증 요약

- 수정 요청과 재검토 결과: `docs/data-requests/4_v3_검토본_수정요청.md`
- 해시 9개, 건수, 중복, ID 짝, 버전 통일: 위반 0건
- 표본 13건을 복지로 페이지와 직접 비교: 모두 일치
- 승인 상태는 `release_manifest.json`의 `status`를 따릅니다.
