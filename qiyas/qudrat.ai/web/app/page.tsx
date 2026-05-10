// Landing page. Server component — fetches the public bank stats from the
// API at request time so the number stays current without client-side JS.
//
// The API banner endpoint (`/`) returns service+version; we don't show
// counts publicly yet (Phase 8 adds an analytics endpoint that does).

import Link from 'next/link';

async function getStats(): Promise<{ service: string; version: string } | null> {
  // In production same-origin nginx proxies /api/* and / to different upstreams.
  // For server-side fetch from inside the pod we hit the Go API directly.
  const base = process.env.QUDRAT_API_URL ?? 'http://127.0.0.1:8080';
  try {
    const res = await fetch(`${base}/`, { cache: 'no-store' });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function Home() {
  const stats = await getStats();
  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center gap-12 px-6 py-16 text-center">
      <header>
        <h1 className="text-5xl font-bold">qudrat</h1>
        <p className="mt-3 text-lg text-neutral-600 dark:text-neutral-400">
          تدريب الذكاء لاختباري القدرات والتحصيلي
        </p>
      </header>

      <section className="space-y-3">
        <p className="text-base text-neutral-700 dark:text-neutral-300">
          آلاف الأسئلة الأصلية. ممارسة قصيرة كل يوم. تتبع نقاط الضعف.
        </p>
        <p className="text-sm text-neutral-500">
          {stats ? `النسخة ${stats.version}` : 'جارٍ التحميل…'}
        </p>
      </section>

      <nav className="flex flex-col gap-3 sm:flex-row sm:justify-center">
        <Link
          href="/login"
          className="rounded-xl bg-blue-600 px-6 py-3 text-white shadow hover:bg-blue-700"
        >
          ابدأ التدريب
        </Link>
        <Link
          href="/practice"
          className="rounded-xl border border-neutral-300 px-6 py-3 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
        >
          ادخل إلى التمارين
        </Link>
      </nav>
    </main>
  );
}
