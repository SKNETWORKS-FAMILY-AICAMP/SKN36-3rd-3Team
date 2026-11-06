## 🔗 관련 Issue

Refs #고령층을 위한 정책 데이터셋 및 API 조사 #1
https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN36-3rd-3Team/issues/1#issue-6194793784

# docs: 고령층 복지정책 API 조사·수집 결과 및 챗봇 활용 계획 정리

## 📌 PR 개요

Repository Issue의 **고령층 관련 정책 데이터셋 조사·신청**, **정책 API 조사·신청**, **데이터 구성 및 챗봇 활용 방식의 Markdown 문서화** 요구사항에 대응합니다.

공공데이터포털의 **중앙부처 복지서비스 OpenAPI** 활용 승인을 받아 Python으로 데이터를 수집했으며, 수집 과정과 현재 확보 범위, 향후 RAG 챗봇 활용 방안을 정리했습니다.

## ✅ Issue 요구사항 대응

- [x] **고령층 관련 정책 데이터셋 찾아오기 / 필요시 신청:** 중앙부처 복지서비스 OpenAPI 조사 및 활용 승인, 목록 데이터 확보
- [x] **고령층 관련 정책 API 찾아오기 / 필요시 신청:** 목록조회·상세조회 API 확인 및 일반 인증키 발급
- [x] **어떤 정보가 있고 챗봇에 어떻게 활용할 수 있는지 MD 작성:** 수집 필드, 데이터 흐름, 활용 시나리오, 제약사항 문서화

> **주의:** 461건은 `srchKeyCode=001` 조회 조건에서 반환된 복지서비스 목록 전체입니다. **461건 모두가 고령층 전용 정책이라는 뜻은 아닙니다.** 고령층 관련 서비스 선별은 후속 작업입니다.

## 📊 현재 수집 결과

| 항목 | 결과 | 상태 |
|---|---|---|
| API 활용 신청 및 인증키 발급 | 승인 완료 | ✅ 완료 |
| 복지서비스 목록 | **461건**, 5페이지 조회 | ✅ 완료 |
| 목록 저장 | `welfare_list.json`, `welfare_list.csv` | ✅ 완료 |
| 서비스별 상세정보 | **99건** 정상 파일 확인(실행 로그 기준) | 🔄 일부 완료 |
| 상세정보 미수집 | **362건** | ⏳ 예정 |
| 목록·상세 병합 및 RAG용 데이터셋 생성 | 미진행 | ⏳ 예정 |

상세정보 수집은 API의 **일일 상세조회 100회 제한**에 도달하여 중단되었습니다. 저장된 XML은 유지되며, 후속 실행 시 정상 기존 파일을 검증한 뒤 건너뛰도록 수집 코드를 구성했습니다.

## 🔗 데이터 출처 및 수집 방식

- **공식 출처:** [공공데이터포털 — 중앙부처 복지서비스 OpenAPI](https://www.data.go.kr/data/15090532/openapi.do)
- **API 제공 기능:** `NationalWelfarelistV001`(목록), `NationalWelfaredetailedV001`(상세)
- **원본 응답:** XML
- **목록 요청:** `serviceKey`, `callTp=L`, `pageNo`, `numOfRows`, `srchKeyCode=001`
- **상세 요청:** `serviceKey`, `callTp=D`, `servId` (명세상 필수값; 기존 수집 스크립트 반영 여부 확인 필요)
- **일일 호출 한도:** 목록조회 100회 / 상세조회 100회 (활용신청 화면 기준)

```text
공공데이터포털 API 활용 승인
        ↓
목록 API 페이지별 요청 (XML)
        ↓
목록 XML 파싱 → JSON·CSV 저장 (461건)
        ↓
servId 추출 → 상세 API 개별 요청 (XML)
        ↓
상세 원본 XML 저장 (현재 99건)
        ↓
[예정] XML 검증·JSON 변환 → 목록/상세 병합
        ↓
[예정] 고령층 정책 분류 → RAG 검색용 청크·임베딩
```

## 🗂️ 확보 데이터 및 챗봇 활용

| 정보 | 대표 필드 | 챗봇 활용 예시 |
|---|---|---|
| 정책명·개요 | `servNm`, `servDgst`, `wlfareInfoOutlCn` | 관련 복지정책 검색 및 요약 |
| 대상·선정 기준 | `tgtrDtlCn`, `slctCritCn` | 지원 가능성 판단에 필요한 조건 안내 |
| 혜택·지원 내용 | `alwServCn` | 지원 내용과 금액 설명 |
| 신청·처리 절차 | `applmetList` | 신청 방법 및 절차 안내 |
| 기관·문의처 | `jurMnofNm`, `rprsCtadr` | 담당 기관 및 문의처 제공 |
| 기준연도·법령 | `crtrYr`, `baslawList` | 정책 기준시점 및 법적 근거 안내 |

**활용 시나리오(향후 구현):** 사용자가 “나이가 많은데 받을 수 있는 지원이 있을까요?”라고 질문하면, 목록 데이터로 관련 정책 후보를 검색하고 상세정보의 지원 대상·선정 기준을 근거로 정책을 설명하며 신청 방법과 공식 문의처를 함께 안내합니다. 실제 수급 자격은 담당 기관 확인이 필요합니다.

### 데이터 가공 현황

- **완료:** 목록 XML 파싱, JSON·CSV 저장, 서비스 ID 기반 상세 XML 개별 저장
- **예정:** 상세 XML의 반복 요소(`applmetList` 등)를 배열로 보존해 JSON 변환, `servId` 기준 병합, 누락·중복·기준연도 검증, 고령층 관련 정책 분류, RAG 청크 생성
- **원칙:** 원본 XML 보존, 출처·수집 시점 관리, 정책의 최신성 검증

## 🔍 검증 및 제약사항

- [x] 목록 API 정상 응답(`HTTP 200`, `resultCode=0`, `SUCCESS`) 확인
- [x] 목록 461건 수집 및 파일 저장 확인
- [x] 상세 XML 샘플에서 지원 대상·선정 기준·지원 내용·신청 절차 필드 확인
- [x] 일일 호출 한도 초과 오류(`HTTP 429`, `LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR`) 원인 확인
- [ ] 나머지 상세정보 수집 및 전체 XML 전수 검증
- [ ] 고령층 정책 선별 및 RAG 검색 품질 평가

## 🔐 보안 및 협업 유의사항

- API 인증키는 **환경변수 `DATA_API_KEY`**로 관리하고 코드·README·PR·로그에 노출하지 않습니다.
- 키가 노출된 이력이 있으므로 재발급 후 기존 키 교체를 권장합니다.
- 대량 원본 파일을 Git에 포함할지 여부는 팀의 저장소 정책에 따라 결정합니다. 코드·문서와 원본 데이터의 버전 관리 범위를 구분합니다.

## 📎 관련 문서

- `README_welfare_data_collection.md` — API 수집 및 데이터 구조 상세 설명
- `ISSUE_고령층_정책데이터_API_수집_활용.md` — Issue 요구사항 대응 상세 보고서
- [공공데이터포털 API 상세 페이지](https://www.data.go.kr/data/15090532/openapi.do)

> PR 등록 전에 `#이슈번호`를 실제 Issue 번호로 교체해 주세요. 위 관련 문서도 실제 커밋에 포함된 경우에만 유지해 주세요.

## 📁 프로젝트 파일 구조 및 위치

현재 VS Code에서 정리한 폴더 구조를 기준으로, 데이터 수집 관련 파일의 위치와 역할을 안내합니다. 아래는 **주요 경로 중심의 구조**이며, 각 폴더에 다른 팀원들의 파일이 추가로 존재할 수 있습니다.

```text
SKN36-3rd-3Team/
├── data/
│   ├── raw/
│   │   └── welfare/                  # 복지서비스 API 원본 수집 데이터
│   │       ├── welfare_list.json     # 목록 조회 결과 (461건)
│   │       ├── welfare_list.csv      # 목록 조회 결과 (461건)
│   │       ├── details/              # 서비스별 상세 XML (현재 정상 확인 99건)
│   │       │   └── WLF*.xml
│   │       └── detail_failures.json  # 상세 조회 실패 기록 (생성된 경우)
│   ├── processed/                    # 향후 정제·통합 데이터 저장 예정
│   └── README.md                     # data 폴더 안내 문서
├── docs/
│   ├── data/
│   │   └── README_data_extraction.md # 본 문서 (PR 설명 및 수집 현황)
│   ├── meetings/                     # 회의 자료
│   ├── references/                   # 참고 자료
│   ├── data-sources.md               # 데이터 소스 조사
│   ├── evaluation.md                 # 평가 관련 문서
│   └── project-plan.md               # 프로젝트 계획
├── scripts/
│   ├── collect_welfare.py            # 복지서비스 목록 수집
│   ├── collect_welfare_details.py    # 상세정보 수집·이어받기
│   └── test_api.py                   # API 연결 테스트
├── .env                              # 로컬 API 인증정보 (Git 업로드 금지)
├── .venv/                            # 로컬 Python 가상환경 (Git 업로드 금지)
├── README.md                         # 저장소 메인 안내
├── requirements.txt                  # Python 의존성 목록
├── pyproject.toml                    # Python 프로젝트 설정
└── uv.lock                           # uv 의존성 잠금 파일
```

### 파일별 역할과 데이터 흐름

| 위치 | 역할 | 현재 상태 |
|---|---|---|
| `scripts/test_api.py` | 인증 및 API 정상 응답 확인 | 테스트에 사용 |
| `scripts/collect_welfare.py` | 목록 API 페이지별 호출 및 JSON·CSV 저장 | 목록 461건 수집 완료 |
| `scripts/collect_welfare_details.py` | `servId`별 상세 XML 수집, 기존 파일 검증 및 이어받기 | 상세 99건 확인, 나머지 수집 예정 |
| `data/raw/welfare/welfare_list.json` | 서비스 목록 원본 응답을 파싱한 JSON | 생성 완료 |
| `data/raw/welfare/welfare_list.csv` | 목록 데이터를 표 형태로 저장한 CSV | 생성 완료 |
| `data/raw/welfare/details/` | 상세 API 응답을 서비스별 XML로 보존 | 일부 수집 완료 |
| `data/processed/` | 향후 XML 정제, 목록·상세 병합, RAG용 데이터 저장 | 예정 |
| `docs/data/README_data_extraction.md` | 출처·수집 방법·진행 상황·활용 계획 공유 | 본 문서 |

**처리 흐름:** `scripts/`의 수집 코드 → `data/raw/welfare/`의 원본·목록 데이터 → *(향후)* `data/processed/`의 정제·통합 데이터 → *(향후)* RAG 검색 시스템.

> **실행 시 유의:** 파일을 `scripts/`로, 데이터를 `data/raw/welfare/`로 이동했다면 Python 코드 내부의 상대경로(`welfare_data/`)도 새 위치에 맞게 수정해야 합니다. 경로 수정과 재실행 검증이 완료되었다는 의미는 아닙니다. 또한 `.env`, `.venv/`, 인증키 및 공개 범위가 확정되지 않은 원본 데이터는 PR에 포함하지 않도록 확인해 주세요.
