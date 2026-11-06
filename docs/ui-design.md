# 어르신 복지 도우미 — #12 회의용 UI 시안

## 범위와 팀 문서 우선 적용

팀 README와 project-plan에서는 지역·기술·화면을 회의 검토 사항으로 둡니다.
따라서 경남 18개 시·군과 Streamlit은 이번 **검토용 시안**이며 팀 전체의 확정 결정이 아닙니다.
참고 기획의 Qdrant 등은 이 작업에서 도입하지 않고 기존 requirements를 유지했습니다.
data/ 및 기존 문서는 수정하지 않았습니다. 실제 수급 자격·시설 검색은 구현 범위 밖입니다.

## 화면 구성

```text
┌──────────────────────────────────────┐
│ 어르신 복지 도우미                    │
│ [가+ 글씨 크게] [가- 글씨 작게]        │
│ [☎ 129 전화 상담]                     │
│ 회의용 시안 / 자료 기준일: 확인 전     │
├──────────────────────────────────────┤
│ 📍 사는 곳 [경남 시·군 선택]           │
│ 나이 [65]  상황 [여러 개 선택]         │
├──────────────────────────────────────┤
│ 💬 연금 / 돌봄 / 시설 / 치매 빠른 질문 │
├──────────────────────────────────────┤
│ 사용자 질문                          │
│ 쉬운 말 답변                         │
│ [📚 출처: 제목 · 기관 · 링크]         │
│ [☎ 불확실하면 129 안내]               │
└──────────────────────────────────────┘
  [궁금한 점을 적어 주세요 …] 전송
```

조건 변경은 다음 질문부터 적용됩니다. 기존 답변과 출처는 session_state에 보존합니다.
새 브라우저 세션에서는 기록이 초기화됩니다. 서버 저장·개인정보 입력은 제공하지 않습니다.
`해당 없음`과 다른 상황의 동시 선택은 안내 후 전송하지 않습니다.

## 접근성 및 색상

- 배경 #F7F8E7, 본문 #172B1D, 주요 버튼 #019A38 + 흰색 굵은 글씨.
- 전화 버튼 #E67E22 + 어두운 글씨. 주황 배경 위 흰색 작은 글씨는 피합니다.
- 기본 20px, 2px씩 최대 28px. 초록 버튼 글씨는 20px 이상 굵게 표시합니다.
  초록/흰색 대비는 약 3.7:1로 큰 굵은 글씨 기준에 맞추며 작은 글씨에 사용하지 않습니다.
- 버튼 최소 높이 56px, 키보드 포커스 테두리, 아이콘과 한글 함께 표시.
- 흐린 회색 안내 대신 어두운 본문색, 짧은 문장과 명시적 오류 안내를 사용합니다.
- 전화 링크는 `tel:129`이며 PC에서는 통화 앱 설치 여부에 따라 동작합니다.
- Streamlit의 DOM 선택자로 스타일을 적용하므로 버전 변경 때 모바일·키보드·확대 화면을 재점검합니다.

## 백엔드 연결 계약

UI는 `src.ui.service.answer(question: str, profile: UserProfile) -> ChatResponse`만 호출합니다.
`schemas.py`의 dataclass는 Streamlit에 의존하지 않습니다.

```json
{
  "question": "기초연금을 받을 수 있나요?",
  "profile": {"sigungu": "창원시", "age": 65, "conditions": ["혼자 사심"]}
}
```

```json
{
  "answer": "[시연용 예시] 신청 조건을 확인해야 해요. 최종 확인은 주민센터 또는 129에 문의해 주세요.",
  "sources": [{"title": "보건복지상담센터 (예시 참고 링크)", "org": "보건복지상담센터", "url": "https://www.129.go.kr/index.do"}],
  "need_call_129": false
}
```

JSON은 계약 설명용이며 별도 HTTP 서버는 없습니다. `dataclasses.asdict()`로 직렬화할 수 있습니다.
조건 값은 화면에 표시된 여섯 가지 문자열을 사용합니다. 빈 목록은 미선택입니다.
Mock은 연금·돌봄·시설·치매 키워드의 고정 예시만 반환합니다. 조건 필터링을 수행하지 않습니다.
그 외 질문은 sources=[] 및 need_call_129=true입니다. 출처는 실제 검색 근거가 아닌 예시 참고 링크입니다.

- `USE_MOCK=true` (기본): `mock.answer` 호출. 키·네트워크·DB 없이 시연 가능.
- `USE_MOCK=false`: `rag_backend.answer` 호출. RAG 담당자가 이 함수 본문을 교체합니다.
  현재는 NotImplementedError를 발생시키고 UI에 재시도/129 안내를 표시합니다. Mock으로 자동 대체하지 않습니다.
- 그 외 환경변수 값과 빈 질문은 ValueError. 백엔드는 반드시 ChatResponse 반환.
- 실제 구현은 지역·나이·상황을 검색 필터로 변환하고 근거가 부족하면 need_call_129=true를 반환해야 합니다.
- 자료 기준일은 현재 계약에 없으므로 화면에 '확인 전'을 표시합니다. 실제 연결 시 Source에 기준일 필드 추가를 협의합니다.
- 출처는 http/https만 링크로 표시합니다. 외부 응답을 HTML로 직접 삽입하지 않습니다.

## 실행 및 검증 (PowerShell, 저장소 루트)

```powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
$env:USE_MOCK = 'true'
.venv/Scripts/python.exe -m streamlit run src/ui/app.py
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_ui.py' -v
```

환경변수는 셸에서 설정합니다(.env 자동 로드는 하지 않습니다).
표준 unittest로 계약·입력 검증·라우팅을 검사하고 Streamlit AppTest로 실제 앱 스크립트와 위젯을 실행합니다.

검증 결과 (2026-11-06, Windows, Python 3.12.13 / Streamlit 1.56.0):

- 기존 패키지 포함 130개 의존성 설치 및 `uv pip check` 통과.
- unittest 7개 통과: 네 가지 Mock 주제/직렬화, 미확인·빈 질문, 18개 지역과 잘못된 입력,
  실제 백엔드 전환, 빠른 질문·채팅·기록 유지, 글씨 크기 상하한, 조건 충돌·백엔드 실패.
- AppTest 앱 실행 시 import 오류 및 처리되지 않은 예외 없음.
- headless 서버 `/_stcore/health` HTTP 200 / ok, 이후 3초 정상 유지 후 종료.
- `git diff --check` 통과. 실제 브라우저의 시각·모바일·보조기기 검수는 다음 할 일입니다.

참고: [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest),
[129 공식 홈페이지](https://www.129.go.kr/index.do).

## 다음 회의에서 결정할 일

1. 경남 우선 범위와 Streamlit 화면 채택 여부.
2. 실제 RAG 연결 담당, 출처 기준일 필드 및 소득 등 추가 질문 계약.
3. 시설은 시·군 단위 안내임을 확인 (거리순·좌표 검색은 별도 작업).
4. 어르신 사용자 대상 문구·모바일·키보드·스크린리더 사용성 점검.
5. 실제 근거 기반 답변·오류·응답 지연 시나리오 통합 테스트.
