import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MMSN Clipper — Long-form to Shorts",
  description:
    "Upload a video, get AI-picked vertical clips with captions for Shorts, Reels and TikTok.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-ink text-gray-200">
        <header className="border-b border-gray-800">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
            <a href="/" className="text-xl font-bold text-white">
              ✂️ MMSN <span className="text-amber-500">Clipper</span>
            </a>
            <span className="rounded-full bg-gray-800 px-3 py-1 text-xs text-gray-400">
              Phase 1 — local dev build
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
        <footer className="mx-auto max-w-5xl px-4 pb-8 text-xs text-gray-500">
          Upload is the primary path. A pasted YouTube link only fetches
          metadata — it never downloads the video. Downloading YouTube videos
          breaks YouTube&apos;s Terms of Service; MMSN does not do it.
        </footer>
      </body>
    </html>
  );
}
