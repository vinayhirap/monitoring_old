/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Same-origin proxy — browser hits /api/* on the Next.js server, which
  // forwards to FastAPI on localhost:8000. The user only needs port 3000
  // open in their firewall; no CORS, no second-port config.
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_BASE_INTERNAL || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
  async redirects() {
    // Page-rename redirects — keeps old bookmarks working after the
    // professionalization pass (astrology → vedic-timing etc.)
    return [
      { source: "/astrology",  destination: "/vedic-timing",  permanent: true },
      { source: "/numerology", destination: "/symbol-cycles", permanent: true },
    ];
  },
  // Long-running endpoints (pipeline scans of ~180 stocks) can take 60-120s.
  // Default proxy timeouts in Node's http server are too short.
  experimental: { proxyTimeout: 180_000 },  // 3 min
};
module.exports = nextConfig;
