FROM node:22-alpine AS admin-build

WORKDIR /src/admin

COPY admin/package.json admin/package-lock.json ./
RUN npm ci
COPY admin/ ./
RUN npm run build

FROM caddy:2.8.4-alpine

ARG RELEASE_SHA=unknown
LABEL org.opencontainers.image.revision="$RELEASE_SHA"

COPY ops/Caddyfile /etc/caddy/Caddyfile
COPY --from=admin-build /src/admin/dist /srv/admin
