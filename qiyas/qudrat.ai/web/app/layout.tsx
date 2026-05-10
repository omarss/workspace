import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'qudrat — تدريب القدرات والتحصيلي',
  description: 'منصة تدريب الذكاء لاختباري القدرات والتحصيلي.',
};

// Lock dir=rtl + lang=ar at the root. Every Arabic-first surface inherits
// it; the few Latin-only screens (debug/api docs) can locally override.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
