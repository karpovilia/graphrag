# Phase 7 — production image. Static-fixture path is gone (Phase 6
# legacy cleanup); pages talk to the R2 backend over /api.

FROM node:22.12-slim AS build

WORKDIR /app
RUN npm i -g pnpm@9.15.9

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --ignore-scripts --frozen-lockfile

COPY tsconfig.json tsconfig-build.json nuxt.config.ts ./
COPY public ./public
COPY app ./app
COPY server ./server
COPY i18n ./i18n

RUN pnpm build

FROM node:22.12-slim

ENV NODE_ENV=production \
    NITRO_PORT=3000 \
    NITRO_HOST=0.0.0.0
WORKDIR /app

COPY --from=build /app/.output ./.output

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
