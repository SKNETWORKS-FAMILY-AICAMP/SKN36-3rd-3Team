빌드, 배포, 자동화 등을 위해 실행하는 별도의 스크립트 파일들을 모아두는 곳입니다.

- `python -m scripts.build_local_welfare_candidate --output-dir /tmp/welfare-candidates`: PR #36 통합 원본의 해시 검증, 지역·노인 후보, 정책 문서, PDF 포함 A/B 청크, 적재 전 교차 검증. 경기 상세 ID 결합은 PR #36에서 완료했습니다.
- `python -m scripts.load_postgres --policy-path <후보 정책 파일> --rag-root <후보 rag 폴더> --check`: DB를 수정하지 않는 파일 검증.
- `--apply`는 명시적 수동 작업입니다. 기존 DB와 정책/청크 ID 집합이 달라지면 중단합니다. 검수·검색 인덱스 전환·롤백은 별도 배포 절차가 필요합니다.
