# 지자체 복지정책 전처리 Python 모듈

첨부된 STEP 2, STEP 3, STEP 4 노트북의 필드 매핑/지역·노인 관련성 규칙을 분리한 실행형 코드입니다.
기존 JSONL 파일을 변경하지 않고 새 경로에 결과를 생성합니다. **지자체 정책 데이터 전용**이며 VWorld 수집은 별도 파이프라인입니다.

## 구성

| 모듈 | 기능 |
|---|---|
| `collect_local_welfare.py` | 지역별 API 목록·상세 조회, 페이지/서비스 ID 캐시, 호출 한도 |
| `io_utils.py` | JSONL 입출력, ID 검사, 실행별 출력 폴더 |
| `quality_checks.py` | 건수·중복·결측 요약 |
| `normalize_policies.py` | 목록/상세 필드 통합, 날짜/태그/지역 표준화 |
| `region_candidates.py` | 미확정 전남광주통합특별시 정책의 지역 후보 생성 |
| `region_selection.py` | 서울·경기·전남·전국 후보 포함, 광주/unknown 제외 |
| `elderly_filter.py` | 노인 direct/indirect/review/exclude_candidate 1차 분류 |
| `run_pipeline.py` | 기능별 CLI 실행 |

## 설치

```bash
pip install -r requirements.txt
```

## 입력/출력 예시

프로젝트 루트에서 ZIP 내용물을 풀었을 때:

```bash
python run_pipeline.py audit --input data/raw/api/local_welfare_service_resume/merged/welfare_seoul_gyeonggi_jeonnam_full.jsonl --id-field servId
python run_pipeline.py normalize --input data/raw/api/local_welfare_service_resume/merged/welfare_seoul_gyeonggi_jeonnam_full.jsonl --output data/processed/local_welfare/policies.jsonl
python run_pipeline.py region-candidates --input data/processed/local_welfare/policies.jsonl --csv data/processed/local_welfare/region_classification_candidates.csv
python run_pipeline.py region-select --input data/processed/local_welfare/policies.jsonl --candidates data/processed/local_welfare/region_classification_candidates.csv --output-dir data/processed/local_welfare/region_filtered_final
```

`region-select`가 출력한 `run_.../policies_selected.jsonl` 경로를 다음 실행에 넣습니다.

```bash
python run_pipeline.py elderly --input data/processed/local_welfare/region_filtered_final/run_YYYYMMDD_HHMMSS_xxxxxx/policies_selected.jsonl --output-dir data/processed/local_welfare/elderly_filtered
```

최종 노인 데이터는 실행별 폴더의 `policies_elderly_selected.jsonl`입니다. `direct + indirect`를 선택하고, `review`와 `exclude_candidate`는 별도 보존합니다.

## 유의 사항

- `region_classification_candidates.csv`의 `confirmed_region`은 사람이 확인할 때만 기입합니다. 자동 후보만으로 포함한 레코드는 `region_selection_verified=False`가 됩니다.
- **`elderly_classification_review.csv`는 review 전용이 아니라 전체 분류 검토표**입니다. `review`만 보려면 `elderly_candidate_category == 'review'`로 필터링하세요.
- 지역 구분이 없는 정책, 적용 지역이 불확실한 정책을 단정하지 마세요. `national`도 **검증된 전국 대상임을 의미하지 않으며 후보**입니다.
- 저장용 JSONL을 만드는 과정은 API 추가 호출이 필요 없습니다.
- 수집 CLI는 `.env`의 `DATA_GO_KR_API_KEY`를 사용하고 요청당 1회로 계산합니다. 실제 잔여 일일 한도는 자동 확인하지 않습니다.
- 수집 CLI는 신규 지역 데이터의 캐시 기반 수집용이며, **기존 서울·경기 스냅샷 복원·누락 보완의 모든 옵션까지 완전히 이식한 것은 아닙니다**. 기존 수집 결과가 있다면 재호출보다 그 JSONL을 입력으로 사용하세요.
- 폴더별 실제 데이터 건수는 파일/실행에 따라 변동됩니다. 고정 건수에 의존하지 않습니다.
- 정책 신청 가능 여부를 자동 분류만으로 확정하지 마세요. 원문·적용 지역을 최종 확인해야 합니다.
