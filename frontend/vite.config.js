import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = `http://127.0.0.1:${process.env.VISION_PORT || '8765'}`

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  base: command === 'build' ? '/static/' : '/',
  build: {
    outDir: '../app/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': backend,
      '/uploads': backend,
    },
  },
}))
