import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig } from 'vite'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }

          if (id.includes('@xyflow/react')) {
            return 'reactflow'
          }

          if (id.includes('@radix-ui') || id.includes('react-resizable-panels')) {
            return 'ui-vendor'
          }

          if (id.includes('lucide-react')) {
            return 'icons'
          }

          if (
            id.includes('/react/') ||
            id.includes('/react-dom/') ||
            id.includes('scheduler') ||
            id.includes('next-themes') ||
            id.includes('sonner')
          ) {
            return 'framework'
          }

          return 'vendor'
        },
      },
    },
  },
})
