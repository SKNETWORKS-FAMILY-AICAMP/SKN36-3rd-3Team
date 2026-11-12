/**
 * 화면 확인용 예시 데이터.
 *
 * - 정책 내용·연락처·링크는 저장소의 전처리 산출물(normalized_policies.jsonl)에 실제로
 *   있는 레코드를 옮긴 것입니다. 가짜 전화번호나 URL을 만들지 않았습니다.
 * - 단, 검색 점수·답변 문장·배지는 화면 확인용으로 적은 예시입니다. 실제 RAG가
 *   붙으면 전부 서버가 만듭니다. 그래서 화면 위에 "예시 답변입니다" 띠가 항상 보입니다.
 * - highlights(누가/무엇을/어떻게)와 keyFigure도 예시입니다. 원문을 줄여서 적었고,
 *   숫자는 원문에 있는 것만 명칭·조건과 함께 적었습니다. 나중에는 서버가 적재 시 생성하고
 *   검수한 것만 내려 줍니다(계약 T8). 검수 전 상태를 보여 주려고 일부는 일부러 null입니다:
 *   광진구 음료배달 = 전부 null, 하남 장수수당 = how만 null(원문 자동 펼침 확인용).
 * - 이 파일은 api/mock.ts만 읽습니다. 페이지·컴포넌트에서 직접 import하지 않습니다.
 */
import type { Badge, Contact, GuidelineItem, PolicyDetail, PolicyItem, RegionsData } from '../types/view'

/** 정책 1건의 예시 원본. 상세(PolicyDetail) + 검색에 필요한 추가 정보 */
export type PolicyFixture = Omit<PolicyDetail, 'isExample' | 'badges' | 'sources' | 'referenceCandidates'> & {
  /** 질문에 이 단어가 들어 있으면 결과에 포함 */
  keywords: string[]
  /** 카드에 보일 한 줄 근거 */
  snippet: string
  themes: string[]
  /** 이 정책이 1순위일 때 보여 줄 예시 답변 (숫자·금액을 쓰지 않음) */
  exampleAnswer: string
  /** 노인 관련성 자동 분류 상태 (데이터 문서 참고). candidate=후보, needs_review=확인 필요 */
  relevance: 'candidate' | 'needs_review'
}

const BOKJIRO = 'https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId='

export const POLICIES: PolicyFixture[] = [
  // ───────────── 전국 공통 (중앙 정책) ─────────────
  {
    policyId: 'central:WLF00001164',
    title: '기초연금',
    summary: '만 65세 이상이면서 소득이 일정 기준 이하인 어르신께 매달 드리는 연금입니다.',
    highlights: {
      who: '만 65세 이상이고 가구 소득인정액이 선정기준액 이하인 어르신 대상',
      what: '매월 25일 기초연금을 지급해요. 금액은 국민연금 등에 따라 달라져요',
      how: '주민센터, 국민연금공단 지사, 복지로(인터넷·앱)에서 신청',
    },
    keyFigure: '기준연금액 월 349,700원 · 실제 받는 금액은 소득·국민연금에 따라 달라요',
    sidoName: null,
    sigunguName: null,
    targetText:
      '만 65세 이상인 어르신으로서 소득인정액이 매년 보건복지부장관이 정하여 고시하는 금액 이하인 사람에게 지원합니다.\n단, 직역연금 수급권자와 그 배우자는 기초연금 지급대상에서 제외하나, 특례대상과 예외대상에 해당하는 경우 지급 가능합니다.',
    selectionCriteriaText:
      '연령 : 만 65세이상인 자\n소득인정액 : 가구의 소득인정액이 선정기준액 이하인 자, 소득인정액은 아래와 같이 계산합니다.\n2026도 선정기준액은 단독가구는 2,470,000원, 부부가구는 3,952,000원',
    benefitText:
      '매월 25일에 기준연금액(349,700원)과 국민연금 급여액 등을 고려하여 기초연금액을 지급합니다.\n* 25일이 토·공휴일인 경우에는 그 전 일에 지급\n기초연금액의 감액은 부부가 모두 받는 경우 등 일부 경우에 이뤄집니다.',
    applicationText:
      '거주지 읍/면/동 주민센터, 전국 국민연금공단 지사 또는 복지로 웹사이트(PC/모바일앱)에서 ‘서비스 신청’을 하시면 됩니다.\n담당 시/군/구청에서 조사 및 심사 후 결과를 알려 드립니다.',
    department: '보건복지부 기초연금과',
    contacts: [
      { label: '국민연금공단', tel: '1355' },
      { label: '보건복지상담센터', tel: '129' },
    ],
    contactNote: null,
    relatedForms: [
      { name: '기초연금 신청서 (복지로)', url: 'https://bokjiro.go.kr/ssis-tbu/CmmFileUtil/getDownload.do?atcflId=1035GOWF16GOWF161035&atcflSn=1' },
    ],
    sourceUrl: `${BOKJIRO}WLF00001164&wlfareInfoReldBztpCd=01`,
    startDate: null,
    endDate: null,
    keywords: ['기초연금', '연금', '65세', '노령', '매달', '돈'],
    snippet: '만 65세 이상인 어르신으로서 소득인정액이 매년 보건복지부장관이 정하여 고시하는 금액 이하인 사람에게 지원합니다.',
    themes: ['소득보장'],
    exampleAnswer:
      '기초연금은 만 65세 이상이면서 소득이 일정 기준 이하인 어르신께 매달 드리는 전국 제도예요. 받으실 수 있는지는 가까운 주민센터나 국민연금공단(1355)에서 확인해 주세요.',
    relevance: 'candidate',
  },
  {
    policyId: 'central:WLF00003191',
    title: '노인맞춤돌봄서비스',
    summary: '일상생활이 어려운 어르신께 안부 확인, 생활 지원 등 돌봄을 제공하는 서비스입니다.',
    highlights: {
      who: '65세 이상 기초생활수급자·차상위·기초연금 수급자 중 돌봄이 필요한 어르신 대상',
      what: '안부 확인, 생활 지원, 사회참여 프로그램 등 방문·통원 돌봄',
      how: '주민센터나 복지로에서 신청하면 시·군·구가 조사한 뒤 서비스를 연결해요',
    },
    keyFigure: null,
    sidoName: null,
    sigunguName: null,
    targetText:
      '돌봄서비스가 필요한 65세 이상 ①국민기초생활 수급자, ②차상위 계층 또는 ③기초연금수급자로서 유사 중복사업 자격에 해당되지 않는 자를 대상으로 합니다.\n※ 다만, 시장·군수·구청장이 서비스가 필요하다고 인정하는 경우 예외적으로 제공 가능',
    selectionCriteriaText:
      '대상자 선정 조사지를 통해 사회-신체-정신영역의 돌봄필요도에 따른 대상자 군을 결정합니다.\n(중점돌봄군) 신체적인 기능제한으로 일상생활지원 필요가 큰 대상\n(일반돌봄군) 사회적인 관계 단절 및 일상생활의 어려움으로 돌봄이 필요가 있는 대상',
    benefitText:
      '방문형, 통원형(집단 프로그램) 등의 직접 서비스(안전지원, 사회참여, 생활교육, 일상생활지원) 및 연계 서비스(민간후원 자원), 특화서비스, 사후관리서비스를 제공합니다.\n개인별 돌봄욕구, 필요정도에 따라 서비스 내용, 제공시간, 제공주기 등을 결정합니다.',
    applicationText:
      '거주지 읍/면/동 주민센터 또는 복지로 웹사이트(PC/모바일앱)에서 ‘서비스 신청’을 하시면 됩니다.\n담당 시/군/구청에서 조사 및 심사 후 노인맞춤돌봄서비스 수행기관이 서비스를 제공합니다.',
    department: '보건복지부 노인정책과',
    contacts: [{ label: '보건복지상담센터', tel: '129' }],
    contactNote: null,
    relatedForms: [],
    sourceUrl: `${BOKJIRO}WLF00003191&wlfareInfoReldBztpCd=01`,
    startDate: null,
    endDate: null,
    keywords: ['돌봄', '혼자', '독거', '안부', '거동', '외로', '말벗', '맞춤돌봄'],
    snippet: '돌봄서비스가 필요한 65세 이상 국민기초생활 수급자, 차상위 계층 또는 기초연금수급자를 대상으로 합니다.',
    themes: ['생활지원', '보호·돌봄', '안전·위기'],
    exampleAnswer:
      '혼자 지내시면서 일상생활이 힘드실 때 안부 확인과 생활 지원을 받을 수 있는 노인맞춤돌봄서비스가 있어요. 해당되시는지 주민센터에서 상담받아 보세요.',
    relevance: 'candidate',
  },
  {
    policyId: 'central:WLF00001155',
    title: '노인일자리 및 사회활동 지원사업',
    summary: '어르신께 다양한 일자리와 사회활동 기회를 제공하는 사업입니다.',
    highlights: {
      who: '65세 이상 어르신 대상 (일부 사업은 60세 이상)',
      what: '공익활동·역량활용 일자리와 사회활동 기회, 활동비 지급',
      how: '주민센터, 노인일자리 수행기관, 복지로에서 신청',
    },
    keyFigure: null,
    sidoName: null,
    sigunguName: null,
    targetText:
      '사회활동 지원사업 참여 조건에 부합하는 65세 이상 어르신을 지원하며, 일부 사업의 경우 60세 이상인 분들도 지원 가능합니다.\n(노인공익활동사업) 65세 이상 기초연금수급자\n(노인역량활용사업) 65세 이상(단, 일부유형은 60세 이상)',
    selectionCriteriaText:
      '(노인공익활동사업) 소득인정액, 참여경력, 세대구성, 활동역량을 종합적으로 판단하여 선발합니다.\n(노인역량활용사업) 활동역량, 필요도, 사무역량, 인성, 대인관계 역량, 유관 자격증 보유를 종합적으로 판단하여 선발합니다.',
    benefitText:
      '(노인공익활동사업) 지역사회 공익 증진을 위해 자발적으로 참여하는 봉사 활동에 월 30시간 이상 참여시 월 29만원을 지급합니다.\n(노인역량활용사업) 노인의 경력과 활동역량을 활용하여 사회적 도움이 필요한 영역에 서비스를 제공하는 일자리로 월 60시간, 월 63.4만원을 지급합니다.',
    applicationText:
      '거주지 읍/면/동 주민센터, 기초자치단체 및 민간일자리 수행기관 또는 복지로 웹사이트(PC/모바일앱)에서 ‘서비스 신청’을 하시면 됩니다.',
    department: '보건복지부 노인지원과',
    contacts: [{ label: '노인일자리 상담', tel: '1544-3388' }],
    contactNote: null,
    relatedForms: [],
    sourceUrl: `${BOKJIRO}WLF00001155&wlfareInfoReldBztpCd=01`,
    startDate: null,
    endDate: null,
    keywords: ['일자리', '일', '소득', '용돈', '활동', '봉사'],
    snippet: '65세 이상 어르신을 지원하며, 일부 사업의 경우 60세 이상인 분들도 지원 가능합니다.',
    themes: ['일자리'],
    exampleAnswer:
      '어르신께 일자리와 사회활동 기회를 드리는 노인일자리 사업이 있어요. 참여 조건과 모집 시기는 주민센터나 노인일자리 상담 전화로 확인해 주세요.',
    relevance: 'candidate',
  },
  {
    policyId: 'central:WLF00001170',
    title: '장기요양급여 이용지원',
    summary: '요양등급을 받은 저소득 국가유공자 등에게 장기요양 본인부담금 일부를 지원합니다.',
    highlights: {
      who: '요양등급을 받은 국가유공자·유족 등 가운데 생활이 어려운 분 대상',
      what: '장기요양 본인부담금의 40~80%를 돌려드려요 (식재료비 등 비급여 제외)',
      how: '주민센터 또는 보훈(지)청에서 신청',
    },
    keyFigure: null,
    sidoName: null,
    sigunguName: null,
    targetText:
      '독립유공자, 국가유공자, 5·18민주유공자, 특수임무유공자 본인 및 배우자, 유족 중 부모(선순위)\n고엽제후유의증환자 중 장애정도판정자 및 참전유공자 본인',
    selectionCriteriaText:
      '「노인장기요양보험법」상 요양등급(1~5등급,인지지원등급)을 판정받고 노인장기요양기관의 재가급여 또는 시설급여 서비스 이용자 중에서 생활이 곤란한 분을 대상으로 합니다.',
    benefitText:
      '장기요양급여 이용에 따른 본인일부부담금 중 대상별로 40~80%를 환급합니다.\n※ 단, 식재료비, 간식비, 상급침실료 등 비급여 부분은 제외',
    applicationText: '거주지 읍/면/동 주민센터 또는 보훈지(방)청에서 ‘서비스 신청’을 하시면 됩니다.',
    department: '국가보훈부 복지서비스과',
    contacts: [{ label: '보훈상담센터', tel: '1577-0606' }],
    contactNote: null,
    relatedForms: [],
    sourceUrl: `${BOKJIRO}WLF00001170&wlfareInfoReldBztpCd=01`,
    startDate: null,
    endDate: null,
    keywords: ['요양', '장기요양', '요양원', '간병', '유공자', '병원비', '의료비'],
    snippet: '요양등급을 판정받고 장기요양기관 서비스를 이용하는 분 중 생활이 곤란한 분을 대상으로 합니다.',
    themes: ['신체건강', '보호·돌봄'],
    exampleAnswer:
      '요양등급을 받으셨고 국가유공자이시면 장기요양 본인부담금 일부를 돌려받을 수 있는 제도가 있어요. 해당 여부는 보훈상담센터나 주민센터에서 확인해 주세요.',
    relevance: 'candidate',
  },

  // ───────────── 서울특별시 ─────────────
  {
    policyId: 'local:WLF00002209',
    title: '저소득 어르신 무료급식 지원 사업',
    summary: '식사를 거를 우려가 있는 어르신께 경로식당 식사나 도시락·밑반찬 배달을 제공합니다.',
    highlights: {
      who: '식사를 거르기 쉬운 만 60세 이상 저소득 어르신 대상 (배달은 만 65세 이상)',
      what: '경로식당 식사(주 6회) 또는 도시락·밑반찬 배달',
      how: '동주민센터에 신청',
    },
    keyFigure: null,
    sidoName: '서울특별시',
    sigunguName: '서대문구',
    targetText:
      '결식 우려가 있는 만 60세 이상 저소득 어르신 지원\n- 경로식당 : 만 60세 이상\n- 도시락 및 밑반찬 배달 : 만 65세 이상\n※ 수혜자 선정기준 - 1순위 : 생계급여수급자 기준 부적합으로 탈락된 생활이 어려운 독거어르신',
    selectionCriteriaText: null,
    benefitText:
      '- 경로식당 : 주6회 경로식당 이용\n- 식사배달서비스 : 주7회 가정으로 점심식사 배달(주말은 대체식으로 제공)\n- 밑반찬배달 : 주2회 가정으로 밑반찬 배달',
    applicationText: '동주민센터에 신청',
    department: null,
    contacts: [],
    contactNote: '5447',
    relatedForms: [],
    sourceUrl: `${BOKJIRO}WLF00002209&wlfareInfoReldBztpCd=02`,
    startDate: '2013-01-01',
    endDate: null,
    keywords: ['밥', '식사', '급식', '도시락', '반찬', '끼니', '경로식당'],
    snippet: '결식 우려가 있는 만 60세 이상 저소득 어르신 지원 - 경로식당 : 만 60세 이상, - 도시락 및 밑반찬 배달 : 만 65세 이상',
    themes: ['안전·위기'],
    exampleAnswer:
      '서대문구에는 식사를 거르기 쉬운 어르신께 경로식당이나 도시락·밑반찬 배달로 식사를 도와드리는 사업이 있어요. 해당되는지 동주민센터에서 확인해 보세요.',
    relevance: 'needs_review',
  },
  {
    policyId: 'local:WLF00001004',
    title: '저소득 독거 어르신 안부확인(음료배달)',
    summary: '홀로 사시는 어르신께 매일 음료를 배달하며 안부를 확인합니다.',
    // 검수 전 상태 예시: 요약이 하나도 없으면 화면이 원문을 바로 펼쳐 보여 줍니다
    highlights: { who: null, what: null, how: null },
    keyFigure: null,
    sidoName: '서울특별시',
    sigunguName: '광진구',
    targetText: '만60세이상 저소득 홀몸 어르신',
    selectionCriteriaText: null,
    benefitText: '매일 야쿠르트 배달을 실시하여 어르신의 건강 · 생활 안전 등 안부확인과 위급상황 발생 시 신속히 대처',
    applicationText: '본인 신청 및 동주민센터에서 돌봄사각지대 어르신발굴',
    department: null,
    contacts: [],
    contactNote: '2966',
    relatedForms: [],
    sourceUrl: `${BOKJIRO}WLF00001004&wlfareInfoReldBztpCd=02`,
    startDate: '2017-01-01',
    endDate: null,
    keywords: ['안부', '혼자', '독거', '우유', '요구르트', '야쿠르트', '배달', '홀몸'],
    snippet: '만60세이상 저소득 홀몸 어르신께 매일 음료를 배달하며 안부를 확인합니다.',
    themes: ['안전·위기'],
    exampleAnswer:
      '광진구에는 혼자 사시는 어르신께 매일 음료를 배달하면서 안부를 확인해 드리는 사업이 있어요. 동주민센터에 문의하시면 신청 방법을 안내받을 수 있어요.',
    relevance: 'needs_review',
  },
  {
    policyId: 'local:WLF00005874',
    title: '도봉형 어르신 일자리사업',
    summary: '도봉구 거주 어르신께 일자리를 지원해 소득과 사회참여를 돕습니다.',
    highlights: {
      who: '도봉구에 사는 60세 이상 어르신 대상 (60~64세는 소득 기준 있음)',
      what: '월 30시간 활동하면 활동비를 드려요',
      how: '접수 기간에 동주민센터 방문 신청 (인터넷 접수 없음)',
    },
    keyFigure: '활동비 월 290,000원 (월 30시간 만근 시)',
    sidoName: '서울특별시',
    sigunguName: '도봉구',
    targetText: '도봉구에 거주하는 60세 이상 어르신\n- 60세 ~ 64세 어르신: 기준중위소득 180% 이하',
    selectionCriteriaText: null,
    benefitText: '- 활동조건: 월 30시간(1일 3시간, 10일) 만근 시, 활동비 290,000원 지급\n- 지급일: 익월 5일',
    applicationText: '- 접수기간 내 동 주민센터 방문 신청(인터넷 접수 미지원)',
    department: null,
    contacts: [],
    contactNote: '4500',
    relatedForms: [],
    sourceUrl: `${BOKJIRO}WLF00005874&wlfareInfoReldBztpCd=02`,
    startDate: '2024-08-01',
    endDate: null,
    keywords: ['일자리', '일', '소득', '용돈', '활동'],
    snippet: '도봉구에 거주하는 60세 이상 어르신께 일자리를 지원합니다.',
    themes: ['일자리', '서민금융'],
    exampleAnswer:
      '도봉구에는 60세 이상 어르신께 일자리를 드리는 사업이 있어요. 접수 기간에 동주민센터를 방문해 신청하시면 돼요.',
    relevance: 'needs_review',
  },

  // ───────────── 경기도 ─────────────
  {
    policyId: 'local:WLF00001710',
    title: '노인 장수수당',
    summary: '장수 어르신께 수당을 드리는 사업입니다. 현재 신규 신청은 받지 않습니다.',
    // how만 null인 예시: 신청 원문이 있으므로 "자세한 내용"이 처음부터 펼쳐집니다
    highlights: {
      who: '2016년 전부터 하남시에 살고 계신 1926년 이전 출생 어르신 (기존 수급자만)',
      what: '매월 수당을 드려요',
      how: null,
    },
    keyFigure: '월 30,000원 · 현재 신규 신청은 받지 않아요',
    sidoName: '경기도',
    sigunguName: '하남시',
    targetText:
      '2016. 1. 1.이전부터 하남시에 거주한 1926. 12. 31. 이전 출생자\n본 사업은 일몰사업으로, 현재 신규 신청은 받고 있지 않으며 기존 장수수당 수급자에 한하여 지원하고 있습니다.',
    selectionCriteriaText: null,
    benefitText: '월 30,000원',
    applicationText: '행정복지센터 방문신청',
    department: '경기도 하남시 복지문화국 노인장애인복지과',
    contacts: [],
    contactNote: '5021',
    relatedForms: [],
    sourceUrl: `${BOKJIRO}WLF00001710&wlfareInfoReldBztpCd=02`,
    startDate: '2013-01-01',
    endDate: null,
    keywords: ['장수', '수당', '돈', '매달'],
    snippet: '2016. 1. 1.이전부터 하남시에 거주한 1926. 12. 31. 이전 출생자. 현재 신규 신청은 받고 있지 않습니다.',
    themes: ['서민금융'],
    exampleAnswer:
      '하남시 노인 장수수당은 현재 새로 신청을 받지 않고 기존 수급자만 지원하고 있어요. 자세한 내용은 행정복지센터에 문의해 주세요.',
    relevance: 'needs_review',
  },
  {
    policyId: 'local:WLF00006800',
    title: '장애어르신 쉼마루',
    summary: '광명시 장애 어르신을 위한 건강·여가 프로그램 공간입니다.',
    highlights: {
      who: '광명시 장애 어르신 대상',
      what: '건강·여가 프로그램과 쉼터를 무료로 이용',
      how: '전화(02-897-6501) 또는 방문 상담',
    },
    keyFigure: null,
    sidoName: '경기도',
    sigunguName: '광명시',
    targetText:
      '시설명 : 장애어르신 쉼마루\n위치 : 광명시 금당로 47, 광명시 장애인이음센터\n주요사업 - 건강증진 프로그램 : 슐런, 파크골프, 한궁 등 - 사회참여 프로그램 : 웃음치료, 노래교실, 문화체험 등',
    selectionCriteriaText: '- 무료 사용',
    benefitText: '- 무료 이용',
    applicationText: '- 서비스 이용: 카페·쉼터 이용, 웃음치료·문화탐방·스포츠·생활공예 등 여가 프로그램\n- 신청방법: 전화(02-897-6501) 또는 방문 상담',
    department: '경기도 광명시 돌봄복지국 노인장애인과',
    contacts: [{ label: '장애어르신 쉼마루', tel: '02-897-6501' }],
    contactNote: null,
    relatedForms: [],
    sourceUrl: `${BOKJIRO}WLF00006800&wlfareInfoReldBztpCd=02`,
    startDate: '2025-10-13',
    endDate: null,
    keywords: ['장애', '여가', '프로그램', '노래', '운동', '쉼터'],
    snippet: '광명시 장애 어르신을 위한 건강증진·사회참여 프로그램을 무료로 이용할 수 있습니다.',
    themes: [],
    exampleAnswer:
      '광명시에는 장애가 있는 어르신이 무료로 건강·여가 프로그램을 이용할 수 있는 쉼마루가 있어요. 전화나 방문으로 상담받아 보세요.',
    relevance: 'needs_review',
  },
]

/** 홈 화면 "자주 찾는 복지" 4개 */
export const QUICK_POLICIES: Array<{ policyId: string; emoji: string; label: string }> = [
  { policyId: 'central:WLF00001164', emoji: '💰', label: '기초연금 알아보기' },
  { policyId: 'central:WLF00003191', emoji: '🤝', label: '노인맞춤 돌봄서비스' },
  { policyId: 'central:WLF00001155', emoji: '👷', label: '어르신 일자리' },
  { policyId: 'central:WLF00001170', emoji: '🏥', label: '장기요양 지원' },
]

/** 공식 안내서(PDF) 예시. 현재 자료는 전부 "검토 중" 상태입니다 */
export const GUIDELINES: Array<GuidelineItem & { relatedPolicyIds: string[]; keywords: string[] }> = [
  {
    kind: 'guideline',
    documentId: 'pdf:e90db348378d8a27',
    documentTitle: '2026 기초연금 사업안내',
    sectionTitle: '주요 개정 사항',
    pageStart: 13,
    pageEnd: 17,
    pageExact: false,
    approval: 'pending',
    snippet: '2026년 기초연금 제도의 주요 개정 사항을 안내합니다.',
    badges: [{ label: '안내서 참고 (검토 중) p.13~17', tone: 'info' }],
    sourceUrl: null,
    relatedPolicyIds: ['central:WLF00001164'],
    keywords: ['기초연금', '연금'],
  },
]

/**
 * 지역 목록. 데이터가 있는 서울·경기·전남만 둡니다 (다른 시도는 선택 창에 보이지 않음).
 * 세 곳 모두 '이용 가능'. 전남은 예시 정책이 아직 없어 지금은 전국 공통 결과만 나옵니다.
 * 범위 밖 지역(위치 찾기 결과·예전 저장값)은 isServiceSido 로 거릅니다.
 */
export const REGIONS: RegionsData = {
  serviceScope: ['서울특별시', '경기도', '전라남도'],
  regions: [
    {
      sidoName: '서울특별시',
      status: 'active',
      sigungu: ['강남구', '강동구', '강북구', '강서구', '관악구', '광진구', '구로구', '금천구', '노원구', '도봉구', '동대문구', '동작구', '마포구', '서대문구', '서초구', '성동구', '성북구', '송파구', '양천구', '영등포구', '용산구', '은평구', '종로구', '중구', '중랑구'],
    },
    {
      sidoName: '경기도',
      status: 'active',
      sigungu: ['가평군', '고양시', '과천시', '광명시', '광주시', '구리시', '군포시', '김포시', '남양주시', '동두천시', '부천시', '성남시', '수원시', '시흥시', '안산시', '안성시', '안양시', '양주시', '양평군', '여주시', '연천군', '오산시', '용인시', '의왕시', '의정부시', '이천시', '파주시', '평택시', '포천시', '하남시', '화성시'],
    },
    {
      sidoName: '전라남도',
      status: 'active',
      sigungu: ['강진군', '고흥군', '곡성군', '광양시', '구례군', '나주시', '담양군', '목포시', '무안군', '보성군', '순천시', '신안군', '여수시', '영광군', '영암군', '완도군', '장성군', '장흥군', '진도군', '함평군', '해남군', '화순군'],
    },
  ],
}

/** 선택 창에 있는 시도인지 (위치 찾기 결과·저장된 지역이 범위 밖이면 false) */
export function isServiceSido(sidoName: string): boolean {
  return REGIONS.serviceScope.includes(sidoName)
}

/** 예시 정책의 배지 계산 (실제로는 서버가 내려 줍니다) */
export function badgesFor(p: PolicyFixture): Badge[] {
  const badges: Badge[] = []
  const hasDetail = Boolean(p.targetText || p.benefitText)
  if (!hasDetail) badges.push({ label: '상세정보 부족 · 기관 문의', tone: 'warn' })
  if (p.sidoName === null) badges.push({ label: '전국 공통', tone: 'ok' })
  else badges.push({ label: '지역 확인 필요', tone: 'warn' })
  badges.push(
    p.relevance === 'candidate'
      ? { label: '어르신 관련 후보', tone: 'info' }
      : { label: '어르신 해당 여부 확인 필요', tone: 'warn' },
  )
  return badges.slice(0, 3)
}

export function toPolicyItem(p: PolicyFixture): PolicyItem {
  return {
    kind: 'policy',
    policyId: p.policyId,
    title: p.title,
    sidoName: p.sidoName,
    sigunguName: p.sigunguName,
    // 검수된 "누가" 요약이 있으면 카드에도 그것을, 없으면 원문 한 문장 (계약 3.4와 동일 규칙)
    snippet: p.highlights.who ?? p.snippet,
    badges: badgesFor(p),
    themes: p.themes,
  }
}

export function toPolicyDetail(p: PolicyFixture): PolicyDetail {
  const { keywords: _k, snippet: _s, themes: _t, exampleAnswer: _a, relevance: _r, ...rest } = p
  return {
    ...rest,
    isExample: true,
    badges: badgesFor(p),
    sources: [],
    referenceCandidates: GUIDELINES.filter((g) => g.relatedPolicyIds.includes(p.policyId)).map(stripGuidelineExtras),
  }
}

export function stripGuidelineExtras(g: (typeof GUIDELINES)[number]): GuidelineItem {
  const { relatedPolicyIds: _r, keywords: _k, ...item } = g
  return item
}

export const DEFAULT_CONTACT: Contact = { label: '보건복지상담센터', tel: '129' }
