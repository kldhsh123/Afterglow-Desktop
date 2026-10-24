import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({ plugins: [vue()], clearScreen: false, server: { port: 1420, strictPort: true, watch: { usePolling: true, interval: 400, ignored: ['**/开发缓存/**', '**/artifacts/**', '**/src-tauri/resources/**', '**/src-tauri/gen/**', '**/test-results/**', '**/tests/native-rpc/target/**'] } }, envPrefix: ['VITE_', 'TAURI_ENV_'], build: { target: 'es2022' } })
