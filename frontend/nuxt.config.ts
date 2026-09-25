import tailwindcss from '@tailwindcss/vite'

// Theme defaults; override with NUXT_PUBLIC_THEME_* (see ../.env.example).
// The real .env lives at the repo root; package.json scripts pass `--dotenv ../.env`
// (missing file is ignored, existing process env wins).
export default defineNuxtConfig({
  compatibilityDate: '2026-09-01',
  devtools: { enabled: false },
  modules: ['@nuxt/eslint'],
  css: ['~/assets/css/main.css'],
  devServer: { port: Number(process.env.WEB_PORT) || 9180 },
  vite: { plugins: [tailwindcss()] },
  runtimeConfig: {
    // Private (server-only): API base used during SSR. In Docker, `localhost` is the web container
    // itself, so compose sets NUXT_API_BASE_SERVER=http://api:9181. Empty falls back to public.apiBase.
    apiBaseServer: '',
    public: {
      // Browser-facing API base (NUXT_PUBLIC_API_BASE).
      apiBase: 'http://localhost:9181',
      theme: {
        lightPrimary: '#32a9e1',
        lightSecondary: '#1e40af',
        lightBackground: '#ffffff',
        darkPrimary: '#7dd3fc',
        darkSecondary: '#94a3b8',
        darkBackground: '#020617',
      },
    },
  },
})
