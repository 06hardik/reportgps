# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Builder — installs deps and builds the React app
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Build the production React bundle — output goes to /app/dist
RUN npm run build

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Runtime — Nginx serves the static build output
# The Node dev server is NOT used in production.
# ─────────────────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Remove the default Nginx page
RUN rm -rf /usr/share/nginx/html/*

# Copy the built React app from the builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy our custom Nginx config for SPA routing
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
