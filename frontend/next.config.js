/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Required by frontend/Dockerfile (standalone server output).
  output: "standalone",
};
module.exports = nextConfig;
