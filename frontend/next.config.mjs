/** @type {import('next').NextConfig} */

// When `BUILD_TARGET=native` (Tauri or Capacitor build pipelines), Next.js
// produces a fully static export at `out/` so the shell can ship it bundled.
// In dev and on a hosted web target, the standard server build is used.
const isNative = process.env.BUILD_TARGET === "native";

const nextConfig = {
  reactStrictMode: true,
  output: isNative ? "export" : undefined,
  // Static export cannot use server-side rewrites; the native runtimes inject
  // their own bridge for `/api/*`. For the web target, proxy to the backend.
  ...(isNative
    ? {}
    : {
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: `${process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8088"}/:path*`,
            },
          ];
        },
      }),
  images: {
    // Static export has no Image Optimization server; disable it for native.
    unoptimized: isNative,
  },
};

export default nextConfig;
