# Holt web app (web/). Build context: web/.
#   docker build -f deploy/web/Dockerfile web
#
# Uses Next.js standalone output when web/next.config sets
# `output: "standalone"` (small image); otherwise falls back to
# `next start` with production node_modules, so it works either way.
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM deps AS build
COPY . .
# NEXT_PUBLIC_* values are inlined into the client bundle at build time.
ARG NEXT_PUBLIC_SITE_HOST=localhost:3000
ARG NEXT_PUBLIC_FREE_AI_QUOTA=3
# Contact details on /terms, /privacy, /refunds and /contact. Required: with
# NODE_ENV=production the build refuses to bake in the placeholders.
ARG NEXT_PUBLIC_CONTACT_EMAIL
ARG NEXT_PUBLIC_CONTACT_CITY
# "1" on staging: statically prerendered pages bake their robots metadata in.
ARG ROBOTS_NOINDEX=
ENV NEXT_PUBLIC_SITE_HOST=$NEXT_PUBLIC_SITE_HOST \
    NEXT_PUBLIC_FREE_AI_QUOTA=$NEXT_PUBLIC_FREE_AI_QUOTA \
    NEXT_PUBLIC_CONTACT_EMAIL=$NEXT_PUBLIC_CONTACT_EMAIL \
    NEXT_PUBLIC_CONTACT_CITY=$NEXT_PUBLIC_CONTACT_CITY \
    ROBOTS_NOINDEX=$ROBOTS_NOINDEX \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build && rm -rf .next/cache
RUN mkdir /out && \
    if [ -d .next/standalone ]; then \
      cp -a .next/standalone/. /out/ && \
      mkdir -p /out/.next && cp -a .next/static /out/.next/static && \
      cp -a public /out/public && \
      echo 'exec node server.js' > /out/start.sh; \
    else \
      npm prune --omit=dev --no-audit --no-fund && \
      cp -a .next node_modules public package.json next.config.* /out/ && \
      echo 'exec node_modules/.bin/next start -H 0.0.0.0 -p "${PORT:-3000}"' > /out/start.sh; \
    fi

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /out /app
USER node
EXPOSE 3000
CMD ["sh", "/app/start.sh"]
