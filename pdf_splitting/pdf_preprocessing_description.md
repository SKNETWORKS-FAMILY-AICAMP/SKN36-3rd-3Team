# 노인복지정책 PDF 전처리 흐름

[`pdf_preprocessing_step_by_step.ipynb`](pdf_preprocessing_step_by_step.ipynb)는 복지정책 PDF 4종을 페이지별 JSON으로 정리한 뒤, 장·절·항 단위로 통합하고 필터링하는 노트북입니다.

1. **모델과 PDF 불러오기**  
   `.env`의 `OPENAI_API_KEY`로 GPT-6 Sol을 연결합니다. Responses API의 추론 강도는 `high`입니다. `PyMuPDF4LLMLoader`로 원본 PDF 4종을 페이지별 Markdown으로 읽습니다. API 키가 없거나 모델 호출에 실패하면 실행을 멈춥니다.

2. **페이지별 JSON 4개 만들기**  
   GPT-6 Sol이 목차·북마크와 원본 페이지 이미지를 보고 본문·표·도식·장절항 정보를 정리합니다. 표와 도식은 가능한 범위에서 텍스트로 보존하고, 복잡한 표나 화살표·배치가 중요한 도식은 필요한 영역을 PNG로 잘라 설명과 함께 연결합니다.  
   필드 `content`, `page`, `source`, `chapter`, `section`, `subsection`, `images`. `subsection`은 문자열 배열입니다.

3. **페이지 JSON 검증·수정**  
   원본 페이지, JSON 초안, 실제로 저장된 크롭을 별도의 GPT-6 Sol 호출로 대조합니다. 본문·수치 누락, 표의 행·열과 병합 관계, 도식·크롭, 목차 분류를 확인합니다. 제외 후보 페이지도 검증하며, 확인된 오류는 반영한 뒤 다시 대조합니다.

4. **장·절·항 단위로 통합**  
   GPT-6 Sol이 제안한 제목의 줄 번호와 문구를 본문에서 확인합니다. 한 페이지의 여러 항목은 나누고, 다음 페이지로 이어지는 항목은 연결합니다. 관련 이미지와 실제 PDF 페이지 범위를 기록해 `guideline_sections.jsonl`을 만듭니다.  
   필드 `section_id`, `source`, `title`, `section`, `subsection`, `content`, `page_start`, `page_end`, `images`. `subsection`은 문자열 또는 `null`입니다.

5. **통합 JSONL 검증·수정**  
   Python으로 페이지별 본문과 이미지가 빠짐없이 한 번씩 옮겨졌는지 확인합니다. GPT-6 Sol은 원본 PDF와 페이지 JSON을 대조해 표·서식·이미지의 소속, 항목 경계와 페이지 범위를 검토합니다. 잘못 배정된 구간을 옮기고 영향을 받은 페이지를 다시 확인합니다.

6. **중복과 관련성 필터링**  
   GPT-6 Sol이 모든 섹션을 검토하고, 노인 정책과 명백히 무관하거나 같은 맥락에서 완전히 중복된 항목만 별도의 재검증을 거쳐 제외합니다. 고령자가 이용할 수 있는 일반 복지, 같은 정책의 요약과 상세 지침, 판단이 불확실한 항목은 유지합니다. 필터링 결과는 `guideline_sections_filtered.jsonl`에 따로 저장합니다.

**최종 출력**은 `data/preprocessed_reproduced/` 아래의 페이지 JSON 4개, 통합 JSONL 2개, `images/`입니다. 파일을 다시 열어 구조와 이미지 참조를 검사한 뒤 출력 폴더에 게시합니다.
