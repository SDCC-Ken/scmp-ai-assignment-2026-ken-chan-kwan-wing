# Frontend (Nuxt 4 + TypeScript + Tailwind CSS 4)

Runs on port 9180 (`WEB_PORT`). Env is read from the repo-root `../.env` if present; theme values use `NUXT_PUBLIC_THEME_*`.

- `bun install` - install dependencies
- `bun run dev` - dev server at http://localhost:9180
- `bun run lint` / `bun run lint:fix` - ESLint (`@nuxt/eslint`)
- `bun run typecheck` - `nuxt typecheck` (vue-tsc)
- `bun run test` - Vitest (theme util, offline)
- `bun run build` then `bun run preview` (or `node .output/server/index.mjs` with `NITRO_PORT=9180`)
