# 지자체 복지서비스 API 원본

기존 수집본과 지역별로 정리한 신규 수집본은 [수집 결과 폴더](local_welfare_service_outputs/)에서 확인할 수 있습니다. 중앙부처 복지서비스 원본은 [별도 API 폴더](../api/)에 있습니다.

## 추가 지역

| 지역 | 파일 | 목록·상세 매칭 건수 |
| --- | --- | ---: |
| 부산광역시 | [welfare_busan_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_busan_full.jsonl) | 285 |
| 충청북도 | [welfare_chungbuk_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_chungbuk_full.jsonl) | 304 |
| 충청남도 | [welfare_chungnam_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_chungnam_full.jsonl) | 339 |
| 대구광역시 | [welfare_daegu_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_daegu_full.jsonl) | 137 |
| 대전광역시 | [welfare_daejeon_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_daejeon_full.jsonl) | 80 |
| 경상북도 | [welfare_gyeongbuk_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_gyeongbuk_full.jsonl) | 289 |
| 인천광역시 | [welfare_incheon_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_incheon_full.jsonl) | 191 |
| 제주특별자치도 | [welfare_jeju_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_jeju_full.jsonl) | 125 |
| 세종특별자치시 | [welfare_sejong_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_sejong_full.jsonl) | 52 |
| 울산광역시 | [welfare_ulsan_full.jsonl](local_welfare_service_outputs/2026-11-20/welfare_ulsan_full.jsonl) | 102 |
| 강원특별자치도 | [welfare_gangwon_full.jsonl](local_welfare_service_outputs/2026-11-23/welfare_gangwon_full.jsonl) | 401 |
| 경상남도 | [welfare_gyeongnam_full.jsonl](local_welfare_service_outputs/2026-11-23/welfare_gyeongnam_full.jsonl) | 488 |
| **합계** | **12개 지역** | **2,793** |

- `2026-11-20/`에는 제공받은 지역별 JSONL 10개를 그대로 보관합니다.
- `2026-11-23/`에는 강원·경남 목록·상세 XML을 `servId`로 결합한 JSONL을 보관합니다. 기존 수집 형식에 맞춰 상세 필드에 `detail_` 접두사를 붙였습니다.
- 각 행은 정책 1건입니다. 표의 건수는 수집본 기준입니다. 챗봇 검색에 사용하려면 지역·노인 관련성 검토와 적재가 필요합니다. [전처리 안내](../../../src/welfare_preprocessing/README.md)
