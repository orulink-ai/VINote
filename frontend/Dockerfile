FROM node:20-alpine AS build

WORKDIR /frontend

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

RUN apk add --no-cache wget

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
COPY --from=build /frontend/dist /usr/share/nginx/html

RUN sed -i 's/\r$//' /docker-entrypoint.d/40-runtime-config.sh \
    && chmod +x /docker-entrypoint.d/40-runtime-config.sh

EXPOSE 80
