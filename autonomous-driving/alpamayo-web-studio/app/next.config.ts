import type { NextConfig } from "next";

const apiOrigin = process.env.ALPAMAYO_STUDIO_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  agentRules: false,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
