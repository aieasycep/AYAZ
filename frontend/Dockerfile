# ── AYAZ Frontend — multi-stage production image ──────────────────────────────
# Stage 1: deps — install node_modules (layer-cached separately from source)
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline

# ── Stage 2: builder — compile Next.js with output:standalone ─────────────────
FROM node:20-alpine AS builder
WORKDIR /app

# NEXT_PUBLIC_* values are baked into the JS bundle at build time.
# Pass the backend URL as a build argument and expose it as an env var so
# Next.js picks it up during `npm run build`.
ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ── Stage 3: runner — minimal production runtime ──────────────────────────────
# next.config.js sets output:'standalone', so .next/standalone contains a
# self-contained server.js with only the packages it actually needs bundled in.
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# Non-root user for security
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# Static assets (served directly by the standalone server or a CDN)
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

# Honor $PORT so Render / Railway can bind to their assigned port.
ENV PORT=3000
CMD ["sh", "-c", "node server.js"]
