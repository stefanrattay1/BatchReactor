import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
    plugins: [vue()],
    build: {
        rollupOptions: {
            output: {
                manualChunks(id) {
                    if (!id.includes('node_modules')) return

                    if (id.includes('chart.js')) return 'vendor-chartjs'
                    if (id.includes('@vue-flow')) return 'vendor-vueflow'
                    if (id.includes('/node_modules/vue')) return 'vendor'

                    return 'vendor'
                }
            }
        }
    },
    server: {
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true
            }
        }
    },
    test: {
        environment: 'node',
        include: ['src/tests/**/*.test.js'],
    },
})
