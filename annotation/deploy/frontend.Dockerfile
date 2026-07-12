# Frontend build + Caddy server image for the annotation site.
#
# Build context is annotation/frontend:
#
#   docker build -f annotation/deploy/frontend.Dockerfile \
#     --build-arg VITE_GOOGLE_CLIENT_ID=<client-id> \
#     -t eb1-annotation-caddy annotation/frontend
#
# The final image is caddy:2-alpine with the built static assets baked into
# /srv. In compose this image is the `caddy` service: it terminates TLS, serves
# these assets, and reverse-proxies /api to the backend (see Caddyfile).
FROM node:24 AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines VITE_* vars at build time, so the OAuth client id is baked into
# the static bundle here (public value — not a secret).
ARG VITE_GOOGLE_CLIENT_ID=""
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
