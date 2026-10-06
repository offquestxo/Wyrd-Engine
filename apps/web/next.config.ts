import type { NextConfig } from "next";

// The browser talks to the API through this app's own origin (docs/decisions.md, Phase 5):
// /api/* is forwarded to FastAPI on 127.0.0.1. SSE (/api/events) streams through the proxy.
const API_TARGET = process.env.WYRD_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Don't gzip proxied responses: compression buffers Server-Sent Events.
  compress: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_TARGET}/api/:path*` }];
  },
};

export default nextConfig;
