# syntax=docker/dockerfile:1
FROM oven/bun:1 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --ignore-scripts
COPY . .
RUN bun run build

FROM node:24-slim AS runtime
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    NITRO_HOST=0.0.0.0 \
    NITRO_PORT=9180
WORKDIR /app
COPY --from=build --chown=node:node /app/.output ./.output
USER node
EXPOSE 9180
# Theme and API bases stay overridable at runtime, e.g.
#   -e NUXT_PUBLIC_THEME_LIGHT_PRIMARY='#ff0000' -e NUXT_PUBLIC_API_BASE=http://localhost:9181
#   -e NUXT_API_BASE_SERVER=http://api:9181   (private; SSR-only, used inside the container network)
CMD ["node", ".output/server/index.mjs"]
