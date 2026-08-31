# syntax=docker/dockerfile:1
#
# Dev-mode image: runs the Vite dev server itself rather than building a
# static bundle behind nginx. This matches how the team already runs the
# frontend locally (`npm run dev`) and gets teammates hot-reload for free —
# docker-compose bind-mounts frontend/ over this image's copy at runtime.
# Build context is the repo root (see frontend/Dockerfile.dockerignore),
# mirroring backend/Dockerfile's convention.
FROM node:22-alpine

WORKDIR /app/frontend

# Installed separately from source so this layer is cached across source
# edits and only invalidates when package.json/package-lock.json change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
