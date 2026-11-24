# PDF 점검 파일 설명서


## 네 파일 한눈에 보기

| 파일 | 역할 |
| --- | --- |
| [`.github/workflows/pdf-check.yml`](../../.github/workflows/pdf-check.yml) | 매월 1일 09:10 KST에 점검을 예약하고 수동 실행도 엽니다. 실행 후 상태와 보고서를 결과 브랜치에 저장합니다. |
| [`scripts/check_pdfs.py`](../../scripts/check_pdfs.py) | 보건복지부 게시판에서 개정본과 관련 고시를 찾고, 기준 PDF와 비교해 상태·보고서·요약을 만듭니다. |
| [`scripts/pdf-check-requirements.txt`](../../scripts/pdf-check-requirements.txt) | 게시판 조회, HTML 해석, PDF 텍스트 추출에 필요한 Python 패키지를 설치할 때 사용합니다. |
| [`configs/pdf-check-sources.json`](../../configs/pdf-check-sources.json) | 점검할 공식 게시판, 검색어, 첨부 선택 기준과 프로젝트 기준 PDF 네 파일의 경로를 정의합니다. |

## 1. `.github/workflows/pdf-check.yml`

### 실행 조건과 순서

- **예약 실행** · `10 9 1 * *`와 `timezone: Asia/Seoul`을 사용해 매월 1일 09:10 KST에 예약합니다. 예약 실행은 저장소의 기본 브랜치인 `dev`의 워크플로를 사용합니다.
- **수동 실행** · GitHub의 **Actions → 보건복지부 PDF 월간 점검 → Run workflow**에서 `dev`를 선택합니다. 첫 배포에서는 수동 실행으로 결과 브랜치에 기록되는지 확인합니다.
- 실행 환경은 `ubuntu-latest`이며 작업 제한 시간은 30분입니다. 코드를 가져온 뒤, 두 번째 체크아웃으로 `pdf-check-results` 브랜치를 작업 폴더의 `pdf-check-results/`에 가져옵니다. `.python-version`에 지정된 Python으로 패키지를 설치하고 점검 스크립트를 실행합니다.

### 입출력과 브랜치 배치

| 구분 | 위치 | 설명 |
| --- | --- | --- |
| 입력 | `dev` | 점검 파일 4개와 이미 등록된 `.python-version`, `data/raw/pdf/`의 기준 PDF 4개를 읽습니다. |
| 입력 | `pdf-check-results` 브랜치 루트의 `state.json` | 첫 실행은 초기 상태를 읽고, 이후 실행은 직전 점검이 저장한 상태를 읽습니다. |
| 중간 출력 | 러너의 `pdf-check-output/state.json`, `pdf-check-output/report.json` | 다음 상태와 이번 보고서를 생성하고 두 JSON의 문법을 확인합니다. |
| 브랜치 출력 | `pdf-check-results` 브랜치의 `state.json`, `runs/<실행 ID>-<재실행 번호>.json` | 상태 파일을 갱신하고 실행별 보고서를 추가해 커밋과 푸시를 합니다. 워크플로는 이 작업에 `contents: write` 권한을 사용합니다. |
| 실행 화면 출력 | **Summary**, **Artifacts** | Summary에는 Markdown 요약이 표시됩니다. `pdf-check-<실행 ID>-<재실행 번호>` 아티팩트에서 `report.json`을 내려받을 수 있습니다. |

처음에는 `pdf-check-results` 브랜치 루트에 초기 `state.json`을 커밋하고 푸시합니다. `applied_version`에는 각 기준판의 공식 게시물 URL·게시 시각·첨부 URL과 **프로젝트에서 실제로 사용하는 PDF의 SHA-256**을 기록합니다. 아직 성공한 점검이나 발견한 후보가 없다면 `last_success_at`은 `null`, `known_candidate_ids`는 빈 배열로 시작합니다.

초기 상태의 구조를 기초연금 항목으로 예시합니다. 실제 초기 파일에는 세 출처의 기준 PDF 네 건을 등록하고, `applied_version`의 빈 값에는 각 기준판에서 확인한 값을 넣습니다.

```json
{
  "sources": [
    {
      "source_id": "basic_pension",
      "last_success_at": null,
      "documents": [
        {
          "document_id": "basic_pension",
          "applied_version": {
            "post_url": null,
            "published_at": null,
            "attachment_url": null,
            "sha256": null
          },
          "latest_observed_version": null
        }
      ]
    }
  ],
  "known_candidate_ids": []
}
```

그다음 `pdf-check-files`에서 `dev`를 대상으로 PR을 열고, 머지한 뒤 수동 실행합니다. 예를 들어 실행 ID가 `123456789`이고 첫 시도라면, 결과 브랜치에 `runs/123456789-1.json`이 추가됩니다. 같은 실행을 재실행하면 `runs/123456789-2.json`으로 구분됩니다. 스크립트가 출처별 실패를 담은 보고서와 상태를 생성하면, 워크플로는 두 파일을 저장하고 보고서를 업로드한 뒤 실행을 실패로 표시합니다.

## 2. `scripts/check_pdfs.py`

### 점검 방법

1. **기준판을 확인합니다.** 설정의 로컬 PDF를 읽어 SHA-256을 계산합니다. 이전 상태의 `applied_version.sha256`과 다르면 해당 문서를 확인 실패로 기록합니다. 공식 기준 게시물과 최근에 관측한 개정 게시물의 첨부도 다시 확인합니다.
2. **새 게시물을 검색합니다.** 첫 점검은 출처별 기준판 중 가장 이른 게시 시각부터 확인합니다. 이후에는 마지막 성공일의 전날 00:00 KST부터 하루 겹쳐 조회하며, 조회 시작점은 기준판의 게시 시각보다 앞서지 않습니다. 중복 게시물은 게시판 ID와 게시물 번호로 구분합니다.
3. **첨부를 확인하고 변경을 비교합니다.** 같은 게시물에서 첨부 URL·파일명·표시 용량 등이 이전과 같으면 확인해 둔 해시와 비교 결과를 재사용합니다. 새 첨부, 정보가 바뀐 첨부, 이전에 다운로드가 실패한 첨부는 내려받아 PDF 여부와 SHA-256을 확인합니다. 이 방식은 첨부 정보가 그대로인 상태에서 파일 내용만 교체된 경우를 감지하기 어렵습니다.
4. **후보와 오류를 기록합니다.** 새 판·첨부 교체·정오표는 `candidates`에, 관련 고시·설명서는 `related_notices`에 기록합니다. 고시의 PDF가 여러 개면 각 첨부를 확인합니다. 타임아웃과 일부 HTTP 오류는 조건에 따라 한 번 더 시도합니다. 페이지 구조가 깨졌거나, 목록이 반복되거나, PDF 대신 HTML이 내려오면 오류로 기록합니다.
5. **다음 실행에 필요한 상태를 저장합니다.** 출처별 점검을 모두 마치면 `last_success_at`을 갱신합니다. 일부가 실패한 출처는 마지막 성공 시점을 유지해 다음에 같은 기간을 다시 확인합니다. `applied_version`은 서비스 반영판, `latest_observed_version`은 마지막으로 관측한 판을 가리킵니다. 이미 기록한 후보는 후속 실행에서 같은 ID로 표시하고 `is_new: false`을 기록합니다.

페이지 비교 결과에는 추출한 텍스트를 기준으로 달라진 섹션과 구판·후보판의 PDF 쪽 번호가 들어갑니다. 표·이미지·텍스트를 추출하기 어려운 페이지는 관리자가 원문에서 확인합니다. 후보를 검토하고 서비스에 반영하는 절차는 별도 문서에 있습니다. [PDF 갱신 방법](<PDF 갱신 방법에 대한 설명.md>)

### 명령줄 입출력

| 옵션 | 구분 | 설명 |
| --- | --- | --- |
| `--config` | 선택 입력 | 출처 설정 경로입니다. 기본값은 `configs/pdf-check-sources.json`입니다. |
| `--source` | 선택 입력 | 출처 ID입니다. 여러 번 지정할 수 있고, 생략하면 설정에 등록된 출처를 모두 점검합니다. |
| `--state-in` | 선택 입력 | 이전 상태 JSON입니다. 로컬에서 생략하면 등록된 기준판부터 시작합니다. |
| `--as-of` | 선택 입력 | 과거 점검의 조회 종료 시각입니다. 생략하면 실행 시작 시각을 사용합니다. 시간대가 없으면 한국 시간으로 해석합니다. |
| `--state-out` | 필수 출력 | 다음 실행에서 읽을 상태 JSON 경로입니다. |
| `--report` | 필수 출력 | 실행 시각, 조회 범위, 문서·첨부별 판정, 후보, 오류를 담은 JSON 경로입니다. |
| `--summary` | 선택 출력 | Markdown 요약 파일 경로입니다. 같은 요약은 터미널에도 출력됩니다. |
| `--work-dir` | 선택 출력 위치 | 내려받은 PDF와 비교 초안을 둘 폴더입니다. 기본값은 `data/staging/pdf-check/`입니다. |

보고서의 `trigger`는 로컬 수동 실행이면 `manual`, 과거 시점 테스트면 `historical`, GitHub Actions 실행이면 `schedule` 또는 `workflow_dispatch` 등 이벤트 이름입니다. `started_at`과 `finished_at`은 실제 시각이며, `scheduled_at`은 예약 실행일 때 코드가 계산한 해당 월 1일 09:10 KST입니다.

| 종료 코드 | 설명 |
| --- | --- |
| `0` | 점검을 완료했습니다. 새 개정본을 발견해도 점검 자체가 완료되면 `0`입니다. |
| `2` | 하나 이상의 출처에서 오류가 나서 보고서에 실패를 남겼습니다. 명령줄 인자 오류도 `2`를 낼 수 있으므로 보고서가 생성됐는지 함께 확인합니다. |
| `1` | 설정·파일 경로·JSON 등 실행에 필요한 입력을 처리하지 못했습니다. |

### 로컬 실행과 결과 예시

3절의 방법으로 패키지를 설치한 뒤, 프로젝트 루트에서 PowerShell로 실행합니다. 기초연금만 점검해 8월과 9월의 결과를 각각 저장하는 예시입니다. `--as-of`는 게시물의 조회 종료 시각을 지정합니다. 첨부는 실행 시점에 보건복지부가 제공하는 파일을 읽습니다.

```powershell
$testRun = 'data/staging/pdf-check/runs/basic-pension-test'

.\.venv\Scripts\python.exe scripts/check_pdfs.py `
  --source basic_pension `
  --as-of '2026-08-01T09:10:00+09:00' `
  --state-out "$testRun/august-state.json" `
  --report "$testRun/august-report.json"

.\.venv\Scripts\python.exe scripts/check_pdfs.py `
  --source basic_pension `
  --as-of '2026-09-01T09:10:00+09:00' `
  --state-in "$testRun/august-state.json" `
  --state-out "$testRun/september-state.json" `
  --report "$testRun/september-report.json"
```

| 결과 예시 | 보고서에서 확인할 항목 |
| --- | --- |
| 8월 1일 기준 기초연금 사업안내 변경 없음 | `sources[].pdf_status`는 `unchanged`이고, 7월 28일 관련 고시는 `related_notices`에 따로 들어갑니다. |
| 9월 1일 기준 8월 5일 일부개정판 발견 | `candidates`에서 `change_type: revised_guide`와 게시물 번호 `1491527`을 확인합니다. `changed_sections`에는 검토할 구판·개정판의 페이지가 기록됩니다. |
| 이후 점검에서 같은 일부개정판을 재확인 | 같은 후보 ID에 `is_new: false`가 기록됩니다. 이미 발견한 개정판이 보고서에 있어도 이번 실행의 전체 결과는 `unchanged`일 수 있습니다. |
| 노인보건복지 1권은 동일하고 2권 확인 실패 | 권별 `documents[].pdf_status`를 확인합니다. 출처의 `status`는 `partial`이고, `errors`에 2권의 실패 단계·URL·사유 등이 기록됩니다. |

다음은 기존 기초연금 개정판을 다시 확인했을 때의 로컬 보고서에서 관련 항목만 발췌한 예시입니다. 이번 실행의 결과는 `unchanged`이고, 이전에 발견한 개정판은 `is_new: false`로 기록됩니다.

```json
{
  "trigger": "manual",
  "scheduled_at": null,
  "status": "unchanged",
  "sources": [
    {
      "source_id": "basic_pension",
      "status": "unchanged",
      "pdf_status": "unchanged"
    }
  ],
  "candidates": [
    {
      "document_id": "basic_pension",
      "post_id": "1491527",
      "change_type": "revised_guide",
      "is_new": false
    }
  ]
}
```

기초연금 일부개정 사례의 기준 게시물과 개정 게시물은 보건복지부에서 확인할 수 있습니다. [1월판 게시물](https://www.mohw.go.kr/board.es?mid=a10409020000&bid=0026&act=view&list_no=1488765) · [8월 개정 게시물](https://www.mohw.go.kr/board.es?mid=a10409020000&bid=0026&act=view&list_no=1491527)

## 3. `scripts/pdf-check-requirements.txt`

`pip`이 읽는 설치 목록입니다. GitHub Actions는 `.python-version`에서 Python 3.12를 준비하고, 이 파일에 지정된 범위 안에서 아래 패키지를 설치합니다.

| 설치 항목 | 스크립트에서 쓰는 기능 |
| --- | --- |
| `beautifulsoup4>=4.12,<5` | 게시물 목록, 상세 페이지, 첨부 링크의 HTML 해석 |
| `PyMuPDF>=2.1,<3` | PDF 열기, 페이지 수와 페이지별 텍스트 추출 |
| `requests>=2.32.4,<3` | 보건복지부 게시물 조회와 PDF 다운로드 |

**입력**은 패키지 목록과 Python 환경이고, **설치 결과**는 그 환경에서 `bs4`, `pymupdf`, `requests`를 불러올 수 있게 되는 것입니다. 프로젝트 루트의 PowerShell에서 기존 `.venv`에 설치하고 확인할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r scripts/pdf-check-requirements.txt
.\.venv\Scripts\python.exe -c "import bs4, pymupdf, requests; print('PDF 점검 패키지 준비 완료')"
```

## 4. `configs/pdf-check-sources.json`

스크립트는 이 JSON의 `sources`에서 게시판 URL, 검색어, 공식 기준 게시물, 로컬 기준판 경로와 첨부 선택 기준을 읽습니다.

| `source_id` | 검색 방법 | 비교할 기준판 |
| --- | --- | --- |
| `elderly_health_welfare` | 발간자료에서 `노인보건복지`를 검색합니다. 관련 고시·지침은 별도 게시판에서 `노인보건복지`와 `노인복지법`으로 찾습니다. | 노인보건복지 사업안내 1권과 2권을 각각 추적합니다. |
| `basic_pension` | 훈령·예규·고시·지침 게시판에서 `기초연금 사업안내`와 `기초연금`을 검색합니다. | 기초연금 사업안내 PDF와 별도로 올라온 정오표·관련 고시를 확인합니다. |
| `welfare_services_guide` | 발간자료의 `복지서비스`, `복지 서비스`, `나에게 힘이` 검색 결과를 확인합니다. | 프로젝트의 표지합본을 기준으로 공식 통합 첨부를 확인합니다. 분권 첨부는 선택에서 제외합니다. |

- `board_url`·`search_terms`는 기본 검색 범위를 정하고, `related_searches`는 별도 관련 게시판 검색을 추가합니다.
- `documents[].document_id`는 결과에 쓰는 문서 식별자입니다. `baseline_path`는 저장소 루트 기준 PDF 경로이고, `baseline_post_url`은 그 판의 공식 게시물 URL입니다.
- `volume`, `preferred_attachment_terms`, `exclude_attachment_terms`는 한 게시물에서 목표 첨부를 선택할 때 쓰입니다. `baseline_is_local_variant`이 지정된 표지합본이 같은 게시물의 공식 첨부와 다르면 `baseline_attachment_differs` 후보로 기록합니다.

**설정 적용 예시** · 위 PowerShell 명령의 `--source basic_pension`은 `source_id`가 `basic_pension`인 항목을 선택합니다. 스크립트가 `data/raw/pdf/2026년 기초연금 사업안내.pdf`의 해시와 공식 첨부를 대조하고, 결과를 보고서의 `sources` 및 `candidates`에 기록합니다.

## PDF 점검 파일과 폴더 구조

### 코드 브랜치

```text
저장소 루트/
├─ .github/workflows/
│  └─ pdf-check.yml
├─ scripts/
│  ├─ check_pdfs.py
│  └─ pdf-check-requirements.txt
├─ configs/
│  └─ pdf-check-sources.json
├─ data/raw/pdf/
│  ├─ 2026_노인보건복지사업안내(1권).pdf
│  ├─ 2026_노인보건복지사업안내(2권).pdf
│  ├─ 2026년 기초연금 사업안내.pdf
│  └─ 2026 나에게 힘이 되는 복지서비스_표지합본 최종.pdf
└─ docs/pdf-check-desc/
   ├─ PDF 점검 파일 설명서.md
   └─ PDF 갱신 방법에 대한 설명.md
```

`.python-version`과 `data/raw/pdf/`의 기준 PDF 네 파일은 `dev`에 이미 있습니다. 위의 점검 파일 네 개와 설명 문서 두 개를 코드 PR에 포함합니다.

### 로컬 작업 공간

```text
data/staging/pdf-check/
├─ downloads/<실행 키>/
├─ comparisons/<문서 ID>-<해시 조합>/comparison.json
└─ runs/
```

`downloads/`에는 받은 후보 PDF, `comparisons/`에는 비교 초안, `runs/`에는 로컬 점검의 상태와 보고서가 들어갑니다. 개발 시 `tests/test_pdf_check.py`로 조회 기간, 후보 중복 방지, 권별 첨부 선택, 오류 재시도 등을 확인할 수 있습니다.

### 결과 브랜치

```text
pdf-check-results 브랜치 루트/
├─ state.json
└─ runs/
   └─ <실행 ID>-<재실행 번호>.json
```

`state.json`은 다음 실행의 입력으로 계속 갱신되고, `runs/` 아래에는 매 실행의 보고서가 쌓입니다. 로컬에서는 작업 공간의 `runs/`에서 테스트 출력을 보고, GitHub에서는 `pdf-check-results` 브랜치나 각 실행의 **Artifacts**에서 실제 보고서를 확인합니다.
