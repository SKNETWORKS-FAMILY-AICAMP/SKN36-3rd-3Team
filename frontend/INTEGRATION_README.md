# 프론트엔드 ↔ FastAPI 연동 안내

## 폴더 복사

이 ZIP의 `frontend/` 폴더를 **SKN36-3rd-3Team 프로젝트 루트**에 복사하세요.
기존 팀원 UI의 React 컴포넌트·스타일은 유지했습니다. `node_modules/`, `dist/`는 의도적으로 제외했습니다.

## 실행

터미널 1 (프로젝트 루트):

```powershell
uv run uvicorn backend.src.main:app --reload --port 8000
```

터미널 2:

```powershell
cd frontend
npm ci
npm run dev
```

Vite가 `/api`를 `http://127.0.0.1:8000`으로 프록시합니다.

## 현재 실제 연동 상태

- **채팅 페이지**: `POST /api/chat` 실제 연동. `session_id` 송수신, PostgreSQL 대화 유지. snake_case 응답을 camelCase로 변환.
- **검색 결과 페이지**: 현재는 별도 `/api/ask`가 없어 **`POST /api/chat`을 통한 임시 답변 연결**입니다. PDF guideline 출처만 근거 카드로 표시합니다. 정책 카드 데이터나 상세 정보를 만들어내지 않습니다.
- **지역 선택**: 지역 목록은 UI의 정적 자료를 사용하지만 모든 지역을 `preparing`으로 표시합니다. 질문에 지역 문자열을 덧붙이는 것은 엄격한 지역 필터가 **아닙니다**. 경고 문구를 표시합니다.
- **정책 상세**: 서버 `/api/policies/{id}`가 없으므로 미구현 오류 표시 (mock 정책 상세 노출 금지).
- **현재 위치**: 기존 `location.ts`가 `/api/location/region` 호출. 백엔드에 해당 API가 없으면 오류와 수동 지역 선택 안내.
- **mock.ts/fixtures.ts**: 개발 비교용으로 보존했지만 `index.ts`는 실제 HTTP 어댑터를 사용합니다.

## 백엔드 후속 필수 작업

1. `POST /api/ask`의 지역 필터와 실제 `ResultItem` 근거 매핑 정의/구현.
2. `GET /api/policies/{id}` 상세 조회 구현 (Qdrant/Neo4j 실제 데이터만).
3. `GET /api/regions` 및 선택적으로 `POST /api/location/region` 구현.
4. 세션 소유권/인증, 에러 처리, 개인정보/보안, 충분한 타임아웃 및 통합 테스트.

> 본 프론트엔드 빌드는 백엔드의 실제 정책 검색 정확도나 서비스 운영 준비 여부를 보증하지 않습니다.
