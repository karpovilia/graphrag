FROM harbor.apsolutions.ru/dockerhub/library/node:22.12-slim AS build

WORKDIR /app
RUN npm i -g pnpm@9.4.0

COPY package.json pnpm-lock.yaml  ./
RUN pnpm install --ignore-scripts --frozen-lockfile

COPY tsconfig.json tsconfig.json
COPY nuxt.config.ts nuxt.config.ts
COPY public public
COPY static static
COPY import-map.json import-map.json
COPY server server
COPY app app
RUN pnpm build


FROM harbor.apsolutions.ru/gcr/distroless/nodejs22-debian12


ENV NODE_ENV=production
WORKDIR /app

COPY --from=build /app/.output ./.output
COPY static static
COPY import-map.json import-map.json

CMD [".output/server/index.mjs"]
