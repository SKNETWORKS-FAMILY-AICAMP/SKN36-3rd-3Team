import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // 브라우저가 /api/... 로 보내는 요청을 FastAPI(8000번 포트)로 넘깁니다.
    // 같은 주소로 보이기 때문에 CORS 설정이 필요 없습니다.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
