# Neo4j 임베딩 적재와 덤프 복원

[`neo4j_save_database.ipynb`](neo4j_save_database.ipynb)는 팀원이 전달한 KURE-v1 벡터를 `A_fixed` 청크에 연결해 Neo4j에 적재하고, 검증한 DB를 덤프로 내보내는 노트북입니다.

## 임베딩 파일로 직접 적재

1. **벡터와 원본 청크 대조**  
   `data/rag/embedding_by_KUREv1/chunk_vectors.jsonl`의 벡터와 `data/rag/chunks/A_fixed/`의 정책·지침 청크를 `chunk_id`로 연결합니다. 원본 청크에서는 본문과 전체 메타데이터를 가져옵니다. `chunk_vectors.npz`, `chunk_map.csv`, `embedding_info.json`을 사용해 벡터 값, ID, 출처, 파일 해시를 전수 확인합니다.

2. **Neo4j 연결과 그래프 적재**  
   루트 `docker-compose.yml`의 Neo4j를 실행하고, 루트 `.env`의 `NEO4J_URI`, `NEO4J_ID`, `NEO4J_PW`로 접속합니다. `NEO4J_DATABASE`를 생략하면 `neo4j`를 사용합니다. 원본 UUID와 Qdrant의 `point_id`를 보존하고, 청크를 정책 또는 지침 섹션에 연결합니다. 섹션은 원본 PDF와 연결합니다. `MERGE`로 재실행 시 같은 ID를 재사용합니다.

3. **적재와 검색 검수**  
   정책 청크 662개와 PDF 지침 청크 2,738개의 본문·메타데이터·벡터·관계를 저장 후 다시 읽어 원본과 대조합니다. Qdrant와 같은 `point_id`와 `parent_id`로 출처 경로를 조회하고, 1,024차원 코사인 인덱스에서 정책·지침 벡터의 Top-5 검색을 점검합니다.

## 덤프로 공유하고 복원

4. **덤프 생성**  
   노트북 **7절**은 실행 중인 컨테이너의 실제 `/data` 경로를 확인하고, 잠시 중지한 뒤 `database/backups/<시간>/neo4j.dump`에 저장합니다. 덤프를 마치면 컨테이너를 다시 시작합니다. 백업 폴더는 Git에서 제외됩니다.

5. **팀원 환경에서 복원**  
   팀원은 `neo4j.dump`를 `notebooks/Neo4j_test/database/backups/`에 넣고 노트북 **8절**의 PowerShell 명령을 직접 실행합니다. 이번 덤프는 **Neo4j 2026.10.2**에서 생성했습니다. 같은 버전의 Neo4j를 준비하면 임베딩 파일 없이도 복원할 수 있습니다. 기존 DB 덮어쓰기는 기본으로 꺼져 있습니다. 복원 후 Cypher로 청크·관계 수, 벡터 차원, 인덱스 상태를 확인합니다.
