# Frontend (Nuxt 4 + TypeScript + Tailwind CSS 4)

Runs on port 9180 (`WEB_PORT`). Env is read from the repo-root `../.env` if present; theme values use `NUXT_PUBLIC_THEME_*`.

- `bun install` - install dependencies
- `bun run dev` - dev server at http://localhost:9180
- `bun run lint` / `bun run lint:fix` - ESLint (`@nuxt/eslint`)
- `bun run typecheck` - `nuxt typecheck` (vue-tsc)
- `bun run test` - Vitest (theme and auth utils, offline)
- `bun run build` then `bun run preview` (or `node .output/server/index.mjs` with `NITRO_PORT=9180`)

## Mock Google sign-in (Phase 1)

`/login` shows a Google One Tap-style card, **automatically on load**, fixed at the top-right of the viewport
(16px from the edges, 360px wide). Full-width MOCK warning banner on the page, plus a "MOCK" chip and the short
warning text inside the card. No Google scripts or requests: the "G" is an inline SVG. The card lists the fictional seed
users (`GET /api/auth/mock-users`) grouped by role; each row is a button ("Continue as <first name>") that calls
`POST /api/auth/mock-google/login`. Nothing is authenticated by Google.

- **Card behaviour:** not a modal (no backdrop, no focus trap, focus is never stolen on load). It is early in the tab
  order (after the theme toggle). Escape or the X collapses it; the page then shows a "Sign in with Google" button that
  re-opens it (and moves focus to the card). While a sign-in is in flight the clicked row shows a spinner, the other rows
  are disabled and Escape/X are ignored. Under 640px it flows in at the top of the page with 8px side margins; from 768px
  the page copy is shifted left so the card never covers it (640-767px it overlays).
- **Session = httpOnly cookie set by the API.** The API answers login with `Set-Cookie: scmp_session=<jwt>; HttpOnly;
  SameSite=Lax; Path=/; Max-Age=3600` and no token in the body, so **page scripts cannot read the session**
  (`document.cookie` never shows it; nothing is in localStorage/sessionStorage). The frontend never touches the token
  and sends no `Authorization` header. Auth state is only the non-secret user object in `useState` (fine in the SSR payload).
- **Cross-origin calls:** the browser calls the API on another port (web :9180 -> API :9181, same host), so every browser
  request uses `credentials: 'include'` and the API must allow the explicit origin with
  `Access-Control-Allow-Credentials: true` and the `X-Requested-With` header. Every unsafe request (POST/PUT/PATCH/DELETE)
  carries `X-Requested-With: XMLHttpRequest` (CSRF marker; otherwise the API returns 403 `CSRF check failed`).
- **SSR:** the Nuxt server forwards the incoming request's `cookie` header to `GET /api/auth/me` (using the private
  `apiBaseServer`), so a hard reload renders the signed-in page directly. Set-Cookie from API responses is never copied
  into the Nuxt response. Server-side, no cookies at all means no API call.
- **Guarding:** global middleware `app/middleware/auth.global.ts` validates the session once per server render, redirects
  unauthenticated users to `/login` and signed-in users away from it. A 401/403 clears the user; `/login?reason=expired`
  shows "session expired" only when a session cookie was actually present. `useApi()` (any API call) does the same on a 401.
- **Sign out:** `POST /api/auth/logout` (best effort; the API clears the cookie), then local state is always cleared.
- **API base URLs:** browser uses `NUXT_PUBLIC_API_BASE` (default `http://localhost:9181`); SSR uses the private
  `NUXT_API_BASE_SERVER` when set (docker-compose sets `http://api:9181`, because `localhost` inside the web
  container is the container itself). It is a runtime env var, not baked into the build. Use the same hostname for web and API
  (e.g. both `localhost`) so the host-scoped cookie is sent to both ports.

## Dev aid: API stub

`scripts/mock-api-stub.ts` is a throwaway implementation of the cookie auth contract for developing the UI without the
backend (not used by tests, Docker or production): login sets an HttpOnly `scmp_session` cookie and returns no token,
`/me` reads the cookie, logout clears it, the CSRF header is enforced, and CORS allows the explicit origin with credentials.

```bash
bun scripts/mock-api-stub.ts                       # listens on 9181 (API_PORT), CORS for http://localhost:9180
API_PORT=9191 STUB_ALLOWED_ORIGIN=http://127.0.0.1:9190 bun scripts/mock-api-stub.ts   # e.g. beside a build on 9190
curl -X POST localhost:9181/__stub/expire          # make /api/auth/me return 401 (session-expiry check)
curl -X POST localhost:9181/__stub/reset
```
