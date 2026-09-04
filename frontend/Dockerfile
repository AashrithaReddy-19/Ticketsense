FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_URL=http://localhost:8000
ARG VITE_SYNC_POLL_INTERVAL_MS=15000
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_SYNC_POLL_INTERVAL_MS=$VITE_SYNC_POLL_INTERVAL_MS
RUN npm run build
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
