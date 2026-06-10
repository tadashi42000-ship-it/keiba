import type { Metadata, Viewport } from "next";
import { Inter, Noto_Sans_JP } from "next/font/google";

import { ToastProvider } from "@/components/notifications/toast-stack";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const notoSansJp = Noto_Sans_JP({ subsets: ["latin"], variable: "--font-noto-jp" });

export const metadata: Metadata = {
  title: "Keiba Mobile",
  description: "Mobile-friendly keiba app powered by Next.js + FastAPI",
  applicationName: "Keiba Mobile",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Keiba Mobile",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body className={`${inter.variable} ${notoSansJp.variable} antialiased`}>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
