# v3 임베딩 결과 공유

복지정책·공식 안내서 청크를 숫자 벡터로 변환한 확정 결과입니다. 팀원이 GPU에서 다시 계산하지 않고 같은 결과로 Qdrant에 적재할 수 있도록 공유합니다.

## 1. 대상과 설정

| 항목 | 값 |
|---|---|
| 데이터 버전 | `nationwide_2026_11_26_6efc3b7671b3` |
| 입력 | `data/rag/nationwide_v3/policy_chunks.jsonl` 2,551개 + `guideline_chunks.jsonl` 2,738개 |
| 벡터 | 5,289행 × 1,024차원, float32, 정규화, Cosine |
| 모델 | `nlpai-lab/KURE-v1` |
| 리비전 | `8b418a58414668e75532ed045c22d9ca018ae2b2` |
| 전처리 | 줄바꿈을 공백으로 치환 (`newline_to_space`) |
| 배치 / 최대 입력 | 16 / 8,192토큰 |
| 설정 식별자 | `6aaacecf145b` |

행 순서는 정책 청크 전체 다음 안내서 청크 전체입니다. 순서를 바꾸면 벡터와 본문이 어긋납니다. 입력 청크와 승인 매니페스트는 기존 경로를 사용하며 이 폴더에 중복 복사하지 않습니다.

## 2. 파일

| 파일 | 역할 |
|---|---|
| `vectors.npy` | Runpod GPU에서 계산한 벡터 5,289개 |
| `chunk_map.csv` | 행 번호, 청크 ID, 포인트 ID, 본문 및 임베딩 입력 해시의 대응표 |
| `embedding_info.json` | 모델·환경·전처리·입력 및 결과 파일 SHA-256·실행 시각 |
| `load_report.json` | 작업자 PC의 Qdrant 적재 및 검증 기록 원본 사본 |

결과 파일 3개와 적재 기록은 원본 바이트 그대로 복사했습니다. `.gitattributes`의 `-text` 규칙으로 줄바꿈 자동 변환을 막습니다. 결과 파일은 직접 편집하지 마세요.

## 3. 필요한 코드와 실행 환경

검증·적재 스크립트는 별도 RAG 코드 브랜치 `feature/rag-v3-search`의 커밋 `f35f27a42d3cef8fff18f63f32cc2feb7da50cc3`에 있습니다. 이 데이터 PR에는 스크립트나 검색 코드 변경을 넣지 않았습니다.

- [검증 스크립트](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN36-3rd-3Team/blob/f35f27a42d3cef8fff18f63f32cc2feb7da50cc3/scripts/verify_v3_vectors.py)
- [적재 스크립트](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN36-3rd-3Team/blob/f35f27a42d3cef8fff18f63f32cc2feb7da50cc3/scripts/load_v3_qdrant.py)
- [임베딩 생성 스크립트](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN36-3rd-3Team/blob/f35f27a42d3cef8fff18f63f32cc2feb7da50cc3/scripts/embed_v3_chunks.py)

두 변경이 함께 반영되어 스크립트·청크·이 결과 폴더가 모두 있는 작업 폴더에서 아래 명령을 실행하세요. `scripts/`에 파일이 없다면 먼저 RAG 코드 반영 여부를 확인하세요. 검증에는 Python과 NumPy가 필요합니다. GPU와 모델 다운로드는 기본 파일 검증·적재에 필요하지 않습니다.

## 4. 받은 뒤 확인하는 방법

저장소 루트에서 실행합니다. 이 명령은 DB에 접속하거나 벡터를 다시 계산하지 않습니다.

```powershell
python scripts/verify_v3_vectors.py --vectors-dir data/embeddings/nationwide_2026_11_26_6efc3b7671b3 --data-dir data/rag/nationwide_v3 --script scripts/embed_v3_chunks.py
```

FAIL이 없어야 다음 단계로 진행합니다. 3차 DB 대조와 모델 독립 재계산은 선택 옵션이며, 위 명령에서는 SKIP이 정상입니다. 상세 해시는 `embedding_info.json`의 `inputs`, `outputs`, `manifest_sha256`을 확인하세요.

## 5. 팀원 PC의 Qdrant 적재

먼저 해당 PC에서 Qdrant를 준비한 뒤 계획을 확인합니다. 아래 명령은 DB에 쓰지 않습니다.

```powershell
python scripts/load_v3_qdrant.py --vectors-dir data/embeddings/nationwide_2026_11_26_6efc3b7671b3 --data-dir data/rag/nationwide_v3 --qdrant-url http://localhost:6333
```

실제 적재는 대상 서버와 계획을 확인한 담당자가 같은 명령에 `--execute`를 추가하여 진행합니다. 새 컬렉션은 `welfare_chunks_v3_6efc3b7671b3`입니다. 같은 이름이 있으면 기본 실행은 중단하며 기존 컬렉션을 삭제하지 않습니다. 같은 작업을 복구하는 경우에만 스크립트의 검사를 거쳐 `--execute --resume`을 사용합니다.

Git에서 파일을 받는 것만으로 팀원 PC의 DB가 생성되지는 않습니다. 이 PR은 서비스 컬렉션·환경변수를 바꾸거나 Neo4j를 적재하지 않습니다.

## 6. 검증 기록의 의미

`load_report.json`은 작업자 PC의 `localhost:6333`, Qdrant 1.20.0에서 5,289개 적재 후 검사 11개가 PASS한 기록입니다(FAIL 0, WARN 0). 다른 PC의 적재 완료를 보증하는 기록은 아닙니다.

데이터 릴리스 승인과 정책별 검토 상태는 별개입니다. 원본 청크의 `approval_status=pending`, 지역 후보·미확정 상태는 그대로 보존합니다. 파일·벡터 검증 통과는 검색·LLM 답변 정확도 평가 통과를 뜻하지 않습니다.
