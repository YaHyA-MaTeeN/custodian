/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // ⚠️ Next inlines Google Fonts at build time by default, which makes the
  // build need the network. A laptop with no internet should still be able to
  // build this app, so the stylesheet is left as an ordinary runtime link.
  optimizeFonts: false,
  // The API runs beside this app on the same machine. Keeping the base URL in
  // one env var means the day it moves to a server, nothing in the code changes.
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000',
  },
};

export default nextConfig;
