# Stage 1: Build the React application
FROM node:20-alpine AS build-stage

WORKDIR /app

# npm ci uses package-lock.json for exact, reproducible installs
COPY package*.json ./
RUN npm ci --prefer-offline

# Copy source and build.
# VITE_SKIP_DATA_SYNC=1 suppresses the sync:data prebuild hook in Docker;
# data is mounted as a volume at runtime, not baked into the image.
COPY . .
RUN VITE_SKIP_DATA_SYNC=1 npm run build

# Stage 2: Serve with Nginx
FROM nginx:1.27-alpine

LABEL org.opencontainers.image.title="dugout-client" \
      org.opencontainers.image.description="Sharks softball dashboard frontend" \
      org.opencontainers.image.source="https://github.com/anchorgroupops/dugout" \
      org.opencontainers.image.vendor="The Sharks"

# Remove default placeholder; our nginx.conf is bind-mounted at runtime
RUN rm -f /etc/nginx/conf.d/default.conf

COPY --from=build-stage /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --spider -q http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
