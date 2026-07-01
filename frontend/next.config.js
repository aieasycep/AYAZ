/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Required for Docker production images: produces a self-contained
  // .next/standalone directory with a minimal Node server (server.js).
  // With this flag the runtime image needs no node_modules mount — only
  // .next/standalone + .next/static + public/ are copied in.
  output: 'standalone',
};

module.exports = nextConfig;
