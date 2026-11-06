"""실행: python -m streamlit run src/ui/app.py (저장소 루트에서)."""
import logging
from pathlib import Path
import sys
from urllib.parse import urlparse

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.ui.schemas import CONDITIONS, SIGUNGU, UserProfile
from src.ui.service import answer

st.set_page_config(page_title='어르신 복지 도우미', page_icon='🌿', layout='centered')
st.session_state.setdefault('font_size', 20)
st.session_state.setdefault('messages', [])


def resize(delta):
    st.session_state.font_size = max(20, min(28, st.session_state.font_size + delta))


size = st.session_state.font_size
st.markdown(f'''<style>
.stApp, [data-testid="stHeader"], [data-testid="stBottom"] {{background:#F7F8E7;color:#172B1D;}}
.stApp p, .stApp label, .stApp li, .stApp input, .stApp textarea,
.stApp [data-baseweb="select"], .stApp a, .stApp button {{font-size:{size}px !important;}}
.stApp p, .stApp label, .stApp li {{color:#172B1D;}}
.stApp button {{min-height:56px;font-weight:700;}}
[data-testid="stButton"] button {{background:#019A38;color:white;border:2px solid #006523;}}
[data-testid="stButton"] button p {{color:white;font-weight:700;}}
.stApp input, .stApp textarea {{color:#172B1D;background:white;min-height:56px;}}
.stApp textarea::placeholder {{color:#354A39;opacity:1;}}
.stApp a {{color:#005C22;text-decoration:underline;}}
.stApp a.phone {{display:flex;align-items:center;justify-content:center;min-height:56px;
background:#E67E22;color:#172B1D;font-weight:700;border:2px solid #813C00;border-radius:8px;}}
.stApp :focus-visible {{outline:3px solid #172B1D !important;outline-offset:3px;}}
[data-testid="stChatMessage"] {{background:white;border:1px solid #355C3D;}}
</style>''', unsafe_allow_html=True)

st.title('어르신 복지 도우미')
left, right = st.columns(2)
left.button('가+ 글씨 크게', on_click=resize, args=(2,), use_container_width=True)
right.button('가- 글씨 작게', on_click=resize, args=(-2,), use_container_width=True)
st.markdown('<a class="phone" href="tel:129">☎ 129 전화 상담</a>', unsafe_allow_html=True)
st.write('궁금한 복지 정보를 쉬운 말로 물어보세요.')
st.info('📋 회의용 시안입니다. 예시 답변은 실제 자격 판정이 아니에요. 자료 기준일: 확인 전.')

with st.container(border=True):
    st.subheader('📍 어떤 도움이 필요하세요?')
    sigungu = st.selectbox('사는 곳 (경상남도)', SIGUNGU)
    age = st.number_input('나이 (만 나이)', min_value=0, max_value=120, value=65, step=1)
    conditions = st.multiselect('지금 상황 (여러 개 선택 가능)', CONDITIONS)
    st.write('선택한 조건은 다음 질문부터 적용돼요. 이름이나 연락처는 적지 마세요.')

st.subheader('💬 자주 묻는 질문')
quick_question = None
for label in ('💰 기초연금 받을 수 있나요?', '🤝 돌봄 서비스', '🏠 가까운 복지시설', '🧠 치매 도움'):
    if st.button(label, use_container_width=True):
        quick_question = label


def show_response(response):
    st.write(response.answer)
    for source in response.sources:
        with st.container(border=True):
            st.write('📚 출처')
            st.write(source.title)
            st.write(f'기관: {source.org}')
            if urlparse(source.url).scheme in ('http', 'https'):
                st.link_button('🔗 출처 열기', source.url, use_container_width=True)
            else:
                st.write('온라인 링크가 없어요. 기관에 문의해 주세요.')
    if response.need_call_129:
        st.warning('☎ 확실한 안내가 필요해요. 129로 전화해 보세요. 위의 전화 상담 버튼을 누르세요.')


st.subheader('🗨️ 나눈 이야기')
for question, response in st.session_state.messages:
    with st.chat_message('user'):
        st.write(question)
    with st.chat_message('assistant'):
        show_response(response)

question = st.chat_input('궁금한 점을 적어 주세요') or quick_question
if question:
    try:
        profile = UserProfile(sigungu, int(age), conditions)
        with st.spinner('답변을 준비하고 있어요…'):
            response = answer(question, profile)
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        logging.getLogger(__name__).exception('답변 서비스 오류')
        st.error('지금 답변을 준비하지 못했어요. 잠시 뒤 다시 시도하거나 ☎ 129로 전화해 보세요.')
    else:
        st.session_state.messages.append((question, response))
        st.rerun()
