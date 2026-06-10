import type { NextConfig } from "next";
import path from "path";

// Proxy /api/v1 in dev when the browser uses same-origin axios (no NEXT_PUBLIC_API_URL).
const backendOrigin = (
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

/** Lock Turbopack to this app so Next does not pick a parent folder lockfile (e.g. C:\\Users\\…\\package-lock.json). */
const projectRoot = path.resolve(__dirname);

const nextConfig: NextConfig = {
  turbopack: {
    root: projectRoot,
  },
  experimental: {
    // AI queries can run for minutes; the default ~30s proxy timeout caused
    // "socket hang up" 500s on /api/query/adaptive even though the backend
    // completed fine. Match the 10-minute axios timeout used by the frontend.
    proxyTimeout: 600_000,
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendOrigin}/api/v1/:path*`,
      },
      {
        source: "/api/query/:path*",
        destination: `${backendOrigin}/api/query/:path*`,
      },
    ];
  },
  webpack(config) {
    config.resolve.alias = {
      ...config.resolve.alias,
      "@": path.resolve(__dirname, "src"),
    };
    return config;
  },
};

export default nextConfig;
