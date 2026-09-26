import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: [
    "192.168.137.1",
    "172.17.6.30",
    "localhost",
    "127.0.0.1",
  ],
};

export default nextConfig;
