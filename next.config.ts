// @ts-ignore - JBOX managed JavaScript helper
import __withJboxAssets from "./jbox.asset-redirects.cjs";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: process.env.SIGNALPOST_STATIC_EXPORT === '1' ? "export" : "standalone",
  trailingSlash: true,
  images: { unoptimized: true },
  // Allow preview subdomains for Keystone preview system
  allowedDevOrigins: [
    "preview.localhost",
    "*.preview.localhost",
    "preview.jboxai.com",
    "*.preview.jboxai.com",
  ],

};

export default __withJboxAssets(nextConfig);
