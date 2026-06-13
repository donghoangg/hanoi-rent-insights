/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Cho phép load ảnh thumbnail từ Supabase Storage (và placeholder).
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.supabase.co" },
    ],
  },
};

export default nextConfig;
