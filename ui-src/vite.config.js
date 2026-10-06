import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    proxy: { '/api': 'http://172.19.0.213:8080' }   // dev local contra la VM
  }
})
