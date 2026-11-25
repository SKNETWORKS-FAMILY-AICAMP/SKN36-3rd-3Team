# 지자체 복지서비스 API 수집 데이터

한국사회보장정보원의 지자체 복지서비스 API에서 받은 정책 목록과 상세 정보를 보관합니다. [공공데이터포털](https://www.data.go.kr/data/15108347/openapi.do) · [수집 파일 폴더](local_welfare_service_outputs/) · [중앙부처 API 데이터](../api/)

## 기존 수집본 · 2026-11-07

| 지역 | 목록 건수 | 상세 포함 |
| --- | ---: | ---: |
| 서울특별시 | 397 | 397 |
| 경기도 | 692 | 207 |
| 전북특별자치도 | 396 | 396 |
| **합계** | **1,485** | **1,000** |

- [목록 CSV](local_welfare_service_outputs/welfare_all_20261107_103452.csv) · [목록·상세 CSV](local_welfare_service_outputs/welfare_all_full_20261107_103452.csv) · [목록·상세 JSONL](local_welfare_service_outputs/welfare_all_full_20261107_103452.jsonl)
- 11월 9일 별도 실행의 [노인복지 정책 선별본](../../processed/local_welfare/elderly_filtered/run_20261109_222318_640379/policies_elderly_selected.jsonl)은 서울 169건, 경기 256건, 전남 라벨 149건으로 총 574건입니다. 전남 라벨 149건은 11월 7일 원본에 포함되어 있지 않습니다.
- [경기 상세 누락 485건](local_welfare_service_outputs/welfare_gyeonggi_missing_485.jsonl)은 **새 정책 485건이 아니라** 위 692건 중 기존에 상세가 비어 있던 485건의 상세 데이터입니다. `servId`로 결합해야 합니다.

## 추가 지역

| 지역 | 파일 | 목록·상세 매칭 건수 |
| --- | --- | ---: |
| 부산광역시 | [welfare_busan_full.jsonl](local_welfare_service_outputs/welfare_busan_full.jsonl) | 285 |
| 충청북도 | [welfare_chungbuk_full.jsonl](local_welfare_service_outputs/welfare_chungbuk_full.jsonl) | 304 |
| 충청남도 | [welfare_chungnam_full.jsonl](local_welfare_service_outputs/welfare_chungnam_full.jsonl) | 339 |
| 대구광역시 | [welfare_daegu_full.jsonl](local_welfare_service_outputs/welfare_daegu_full.jsonl) | 137 |
| 대전광역시 | [welfare_daejeon_full.jsonl](local_welfare_service_outputs/welfare_daejeon_full.jsonl) | 80 |
| 경상북도 | [welfare_gyeongbuk_full.jsonl](local_welfare_service_outputs/welfare_gyeongbuk_full.jsonl) | 289 |
| 인천광역시 | [welfare_incheon_full.jsonl](local_welfare_service_outputs/welfare_incheon_full.jsonl) | 191 |
| 제주특별자치도 | [welfare_jeju_full.jsonl](local_welfare_service_outputs/welfare_jeju_full.jsonl) | 125 |
| 세종특별자치시 | [welfare_sejong_full.jsonl](local_welfare_service_outputs/welfare_sejong_full.jsonl) | 52 |
| 울산광역시 | [welfare_ulsan_full.jsonl](local_welfare_service_outputs/welfare_ulsan_full.jsonl) | 102 |
| 강원특별자치도 | [welfare_gangwon_full.jsonl](local_welfare_service_outputs/welfare_gangwon_full.jsonl) | 401 |
| 경상남도 | [welfare_gyeongnam_full.jsonl](local_welfare_service_outputs/welfare_gyeongnam_full.jsonl) | 488 |
| **합계** | **12개 지역** | **2,793** |

- 11월 20일 수집본 10개 지역은 제공받은 JSONL을 보관합니다.
- 강원·경남은 목록·상세 XML을 서비스 ID(`servId`)로 결합했습니다. 상세 필드에는 기존 형식과 같이 `detail_` 접두사를 붙였습니다.
- JSONL은 한 줄에 정책 한 건을 담습니다. 신규 데이터를 챗봇 검색에 반영하려면 지역·노인 관련성 검토와 적재가 필요합니다. [전처리 안내](../../../src/welfare_preprocessing/README.md)
- 위 목록 1,485건과 12개 지역 2,793건을 결합한 **중복 없는 4,278건(15개 지역)** 파일은 [PR #36의 통합 원본](../../staging/local_welfare/2026-11-25/merged_policies_raw.jsonl)입니다. 광주광역시·전라남도 독립 수집본은 이 폴더에 없습니다. 기존 574건의 전남 라벨 149건은 [별도 보존본](../../staging/local_welfare/2026-11-25/legacy_jeonnam_selected.jsonl)에 있으며, 4,278건과 합치기 전에 출처를 검토해야 합니다.
