# MMSN Clipper — frontend (Next.js, standalone output)
FROM node:20-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend ./
# NEXT_PUBLIC_* values are inlined into the JS bundle at BUILD time, so
# they must arrive as a build arg, not a runtime env var. Render passes
# each service env var as a Docker build arg automatically (see
# render.yaml: NEXT_PUBLIC_API_URL), which is why this ARG exists.
# NOTE: changing the backend URL later requires a rebuild of this image.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# /app/public must exist in the builder stage (even empty — see
# frontend/public/.gitkeep), or this COPY fails the whole build.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
# Next's standalone server.js reads process.env.PORT (default 3000) and
# binds 0.0.0.0, so Render's injected PORT just works — do NOT hardcode
# a port here or set PORT by hand in render.yaml.
CMD ["node", "server.js"]
