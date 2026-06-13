import type { Metadata } from "next";
import "./globals.css";
import NavBar from "@/components/NavBar";

export const metadata: Metadata = {
  title: "HanoiRent Insights — Tìm & phân tích nhà cho thuê Hà Nội",
  description:
    "Bản đồ tương tác và dashboard phân tích thị trường nhà cho thuê tại Hà Nội, " +
    "tổng hợp từ Nhatot và Mogi.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <head>
        <link
          rel="preconnect"
          href="https://fonts.googleapis.com"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <div className="flex flex-col h-screen">
          <NavBar />
          <main className="flex-1 min-h-0">{children}</main>
        </div>
      </body>
    </html>
  );
}
