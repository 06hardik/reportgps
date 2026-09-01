FROM node:20-slim

WORKDIR /app

# Copy package files first for layer caching
COPY package.json package-lock.json ./

# Install only production dependencies
RUN npm ci --omit=dev

# Copy application source
COPY server.js .

# Expose backend port
EXPOSE 5001

CMD ["node", "server.js"]
