/**
 * 화면 이동(라우팅) 정의.
 *   /                 홈
 *   /chat             대화 (첫 질문은 홈에서 라우터 state 로 전달, URL 에 질문 없음)
 *   /result           예전 검색 결과 주소 → 대화 화면으로 안내만 (자동 검색 없음)
 *   /policy/:policyId 복지 상세
 *   그 외             홈으로 안내
 */
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import Chat from './pages/Chat'
import Home from './pages/Home'
import PolicyDetail from './pages/PolicyDetail'

function NotFound() {
  return (
    <main className="px-4 py-10 text-center">
      <p className="text-xl font-bold">페이지를 찾을 수 없어요</p>
      <Link to="/" className="mt-4 inline-block min-h-14 rounded-button bg-primary px-6 py-4 text-lg font-bold text-on-primary">
        홈으로
      </Link>
    </main>
  )
}

/** 예전 /result 주소로 들어온 경우. 주소의 질문을 자동으로 보내지 않습니다 */
function ResultMoved() {
  return (
    <main className="px-4 py-10 text-center">
      <p className="text-xl font-bold">검색 결과 화면이 대화 화면으로 바뀌었어요</p>
      <p className="mt-2 text-base text-muted">홈에서 질문하시면 답을 보고 이어서 더 물어보실 수 있어요.</p>
      <Link to="/" className="mt-4 inline-block min-h-14 rounded-button bg-primary px-6 py-4 text-lg font-bold text-on-primary">
        홈으로
      </Link>
    </main>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Home />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/result" element={<ResultMoved />} />
          <Route path="/policy/:policyId" element={<PolicyDetail />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
