"""의도 확인(intent_check)만 실제 LLM 으로 돌려 보는 회귀 시험. 검색·판정·답변은 하지 않는다.

앞 대화에 이어진 짧은 질문(V004 "그럼 나는 무조건 받는 거지?"), 개인 정보 질문을 거부·모름으로 답한 경우(V024 "말하기 싫어."),
그리고 반대로 되물어야 맞는 질문·범위 밖 질문·지역을 물었을 때 "모르겠어요"를 함께 본다.
의도 확인 지시문(INTENT_PROMPT)을 고칠 때마다 돌려서 13개가 모두 맞는지 확인한다. 호출 13회, 약 0.01달러.

실행 예
  uv run --no-project --python 3.12 --with python-dotenv --with langchain-openai python -X utf8       scripts/eval_intent_followups.py data/eval/v4/results/intent_followups_<이름>.json
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
if len(sys.argv) != 2:
    raise SystemExit("사용법: eval_intent_followups.py <결과.json>")
if Path(sys.argv[1]).exists():
    raise SystemExit(f"[중단] 결과 파일이 이미 있습니다 (덮어쓰지 않음): {sys.argv[1]}")
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from src.agents.intent_check import classify_intent

U = lambda t: {"role": "user", "content": t}
A = lambda t: {"role": "assistant", "content": t}
MEAL = [U("혼자 사는데 밥 갖다주는 데 없나?"), A("횡성군에 어르신 식사 배달 사업이 있어요. 결식 우려가 있는 저소득 어르신이 대상이에요.")]
CARE = [U("혼자 사는데 안부 확인해 주는 데 있나?"), A("강북구에 음료를 배달하면서 안부를 확인하는 사업이 있어요. 저소득 돌봄 취약가구가 대상이라, 기초생활수급자나 차상위에 해당하시는지 여쭤봐도 될까요?")]
REGION_Q = [U("횡성 엄마 보청기 지원 돼?"), A("말씀하신 '횡성'과 화면에서 고르신 지역 강원특별자치도 강릉시가 달라요. 어느 지역 기준으로 찾아 드릴까요?\n1. 강원특별자치도 횡성군\n2. 강원특별자치도 강릉시")]
GW = {"kind": "region", "sido_name": "강원특별자치도", "sigungu_name": "횡성군"}  # 채팅 요청과 같은 모양
SB = {"kind": "region", "sido_name": "서울특별시", "sigungu_name": "강북구"}
GN = {"kind": "region", "sido_name": "강원특별자치도", "sigungu_name": "강릉시"}
CASES = [
    ("V004 자격 후속", "그럼 나는 무조건 받는 거지?", MEAL, GW, "search"),
    ("자격 후속2", "나도 되는 거야?", MEAL, GW, "search"),
    ("신청 후속", "그거 어떻게 신청해?", MEAL, GW, "search"),
    ("V024 거절", "말하기 싫어.", CARE, SB, "search"),
    ("거절2", "그건 왜 물어? 안 알려줄래.", CARE, SB, "search"),
    ("모름", "그런 거 잘 모르겠어.", CARE, SB, "search"),
    ("앞대화 없는 자격", "그럼 나도 받을 수 있어?", [], GW, "clarify"),
    ("모호 배고파", "나 배고파", [], GW, "clarify"),
    ("모호 힘들어", "힘들어", [], SB, "clarify"),
    ("새 주제", "근데 틀니도 지원돼?", MEAL, GW, "search"),
    ("범위 밖", "오늘 날씨 어때?", MEAL, GW, "out_of_scope"),
    ("제도 안내", "기초연금 신청 방법 알려줘", [], SB, "search"),
    ("지역 질문에 모름", "모르겠어요", REGION_Q, GN, "clarify"),
]
out = []
for name, q, hist, region, want in CASES:
    r = classify_intent(q, hist, region)
    ok = r["intent"] == want
    out.append({"case": name, "question": q, "want": want, **r, "ok": ok})
    print(f"{'OK ' if ok else 'XX '} {name:12} want={want:12} got={r['intent']:12} q={r['search_query'] or r['clarification_question'][:60]!r}")
print(f"{sum(o['ok'] for o in out)}/{len(out)}")
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
if not all(o["ok"] for o in out):
    raise SystemExit("[실패] 기대와 다른 분류가 있습니다.")
