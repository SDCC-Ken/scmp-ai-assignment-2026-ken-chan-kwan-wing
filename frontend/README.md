# Frontend (Nuxt 4 + TypeScript + Tailwind CSS 4)

Runs on port 9180 (`WEB_PORT`). Env is read from the repo-root `../.env` if present; theme values use `NUXT_PUBLIC_THEME_*`.

- `bun install` - install dependencies
- `bun run dev` - dev server at http://localhost:9180
- `bun run lint` / `bun run lint:fix` - ESLint (`@nuxt/eslint`)
- `bun run typecheck` - `nuxt typecheck` (vue-tsc)
- `bun run test` - Vitest (theme and auth utils, offline)
- `bun run build` then `bun run preview` (or `node .output/server/index.mjs` with `NITRO_PORT=9180`)

## Mock Google sign-in (Phase 1)

`/login` shows a "Sign in with Google" button (inline SVG, no Google scripts or requests) under a permanent
**mock warning**. The button opens an account chooser listing the fictional seed users
(`GET /api/auth/mock-users`); picking one calls `POST /api/auth/mock-google/login` and receives a real JWT
from the backend. Nothing is authenticated by Google.

- **State:** the JWT is stored in the `auth-token` cookie (`SameSite=Lax`, `Secure` only over https,
  `Max-Age` from `expires_in`). Only the user object is in `useState`; the token is never in the SSR payload,
  URLs or logs. The cookie is set from JavaScript, so it is readable by page scripts (not `httpOnly`); a
  `httpOnly` cookie would need the backend to set it. Accepted for this demo.
- **Guarding:** global middleware `app/middleware/auth.global.ts` redirects unauthenticated users to `/login`
  and signed-in users away from it, validating the cookie with `GET /api/auth/me` (also during SSR). A 401/403
  clears the cookie and shows a "session expired" notice.
- **API calls:** use `useApi()` (adds the Bearer header, signs out on 401). Sign out calls
  `POST /api/auth/logout` best-effort and always clears the local session.
- **API base URLs:** browser uses `NUXT_PUBLIC_API_BASE` (default `http://localhost:9181`); SSR uses the private
  `NUXT_API_BASE_SERVER` when set (docker-compose sets `http://api:9181`, because `localhost` inside the web
  container is the container itself). It is a runtime env var, not baked into the build.
- The backend must allow CORS from the web origin (`http://localhost:9180`) with the `Authorization` header.

## Dev aid: API stub

`scripts/mock-api-stub.ts` is a throwaway implementation of the auth contract for developing the UI without the
backend (not used by tests, Docker or production):

```bash
bun scripts/mock-api-stub.ts                       # listens on 9181 (API_PORT), CORS for http://localhost:9180
curl -X POST localhost:9181/__stub/expire          # make /api/auth/me return 401 (session-expiry check)
curl -X POST localhost:9181/__stub/reset
```
