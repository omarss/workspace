// Next.js config. Standalone output is what the container uses — Next
// emits a self-contained server bundle into .next/standalone we can copy
// into a tiny runtime image.
/** @type {import('next').NextConfig} */
const config = {
  output: 'standalone',
  reactStrictMode: true,
  // Same-origin /api/* calls go straight to host nginx (no CORS), but in
  // local dev we proxy them to the Go API on :8080 so `pnpm dev` works
  // without nginx.
  async rewrites() {
    if (process.env.NODE_ENV === 'production') return [];
    return [{ source: '/api/:path*', destination: 'http://127.0.0.1:8080/api/:path*' }];
  },
};

export default config;
