import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// En producción la app se publica bajo el prefijo /solvento (Tailscale funnel
// enruta /solvento → backend y elimina el prefijo). Por eso el build usa
// base '/solvento/' para que los assets y la API se pidan con ese prefijo.
// Cuando la app viva en su propio dominio, compila con SOLVENTO_BASE=/ .
// En desarrollo la app vive en la raíz y el proxy reenvía /api al backend.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? process.env.SOLVENTO_BASE || '/solvento/' : '/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}))
