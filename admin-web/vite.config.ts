import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    // 本机后端仅监听 127.0.0.1（IPv4）；用 localhost 会被解析到 IPv6(::1) 导致代理超时，
    // 故代理目标显式写 127.0.0.1。
    proxy: {
      '/v1': 'http://127.0.0.1:8000',
      '/admin': 'http://127.0.0.1:8000',
    },
  },
})
