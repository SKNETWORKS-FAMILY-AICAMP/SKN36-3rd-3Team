# SKN36 Splitting V3 — 실데이터 검증 패키지

## 시작하기

이 폴더는 사용자 원본 ZIP의 필수 데이터 4개, 표 구조 보완된 Splitting 코드, 재실행 결과, Jupyter Notebook, HTML 가이드 및 수동 검수 큐를 담고 있습니다.

**기본 입력**: `splitting_inputs/` 4개 파일, **결과**: `splitting_output_v3/`.

### Windows PowerShell에서 실행

```powershell
cd "C:\Dev\project\project 3st\SKN36-RAG-Splitting"
uv run --no-project python .\SKN36_auto_splitting.py --input-dir ".\splitting_inputs" --output-dir ".\splitting_output_v3" --strict-counts
```

Python 가상환경을 직접 실행할 경우:

```powershell
uv venv --python 3.11
uv pip install --python .\.venv\Scripts\python.exe -r .\requirements.txt
.\.venv\Scripts\python.exe .\SKN36_auto_splitting.py --input-dir ".\splitting_inputs" --output-dir ".\splitting_output_v3" --strict-counts
```

### Notebook

`SKN36_Policy_PDF_Splitting_Qdrant_Neo4j_임베딩직전_V3.ipynb`를 Jupyter에서 열고 Run All. 시작 셀 `INPUT_DIR`만 필요시 바꾸세요.

### 다운로드를 추가하면 자동 인식하는 PDF

원본 PDF 4종은 페이지 인용 후보 대조를 돕지만 필수 입력은 아닙니다. 노령층 분권 PDF 1종은 이 패키지에는 없으며, 다음 GitHub 경로에서 사용자가 직접 내려받아야 합니다:

`https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN36-3rd-3Team/tree/feature/10-api-data-processing/data/raw/pdf`

파일 이름: `2026 나에게 힘이 되는 복지서비스_분권(노령층).pdf` (필수 폴더에 넣으면 자동 페이지 추출). 이 결과도 공식 의미 단위 구조화가 아니므로 검수해야 합니다.

**검수 파일과 한계**: `SKN36_임베딩직전_V3_품질개선_종합보고서.md`를 반드시 읽으세요.

**주요 주의**: `embedding_ready.jsonl` 생성은 임베딩/DB 적재/실제 수급 자격 승인과 별개입니다. `.env`, `.venv`는 Git에 추가하지 마세요.
