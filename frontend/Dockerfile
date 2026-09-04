# ── Build stage ──
FROM node:20-alpine AS build

WORKDIR /app

# Use npmmirror for faster downloads in China
RUN npm config set registry https://registry.npmmirror.com

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --prefer-offline 2>/dev/null || npm install

COPY . .
RUN npm run build

# ── Production stage ──
FROM nginx:1.25-alpine

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx config (serves static + proxies /api to backend)
COPY nginx-docker.conf /etc/nginx/nginx.conf

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --no-check-certificate --spider https://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
