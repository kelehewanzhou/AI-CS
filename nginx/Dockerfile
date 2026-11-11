FROM node:24-alpine@sha256:a34ab6d7f6f4813f4d0c5469d74685604b962fbdbf5793a7bc7b4998ecb867c8 AS web
WORKDIR /web
RUN corepack enable && corepack prepare pnpm@10.34.9 --activate
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
ENV NEXT_PUBLIC_API_URL=/api/v1 NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM nginx:1.30.6@sha256:42c68eab6f7e22611786a9fe1d1c019e275c50185bd54b8f75dc2b9184322703
COPY --from=web /web/out/ /usr/share/nginx/html/
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/templates/ /opt/kglearn/templates/
COPY nginx/snippets/ /etc/nginx/snippets/
COPY nginx/40-kglearn-config.sh /docker-entrypoint.d/40-kglearn-config.sh
RUN chmod +x /docker-entrypoint.d/40-kglearn-config.sh && rm -f /etc/nginx/conf.d/default.conf
