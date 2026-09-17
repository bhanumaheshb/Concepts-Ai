/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // The engine runs as a separate FastAPI process. Proxying it through Next means
  // the browser only ever talks to one origin, so the app works unchanged behind a
  // tunnel — and the backend itself never has to be exposed to the internet.
  async rewrites() {
    const backend = process.env.BACKEND_ORIGIN || "http://127.0.0.1:8001";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },

  // Next refuses cross-origin dev requests unless the host is listed. A quick
  // tunnel gets a fresh random *.trycloudflare.com hostname on every start.
  allowedDevOrigins: ["*.trycloudflare.com"],
};

export default nextConfig;
