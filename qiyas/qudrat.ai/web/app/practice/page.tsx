'use client';

// Quick Boost practice surface. Fetches 5 unanswered items, runs the user
// through them one at a time, posts each answer, and shows a final
// summary screen. If /me 401s the user gets bounced to /login.

import Link from 'next/link';
import { useEffect, useState } from 'react';

type Choice = { key: string; text: string };
type ServedItem = {
  id: string;
  question_text: string;
  topic: string;
  skill: string;
  difficulty_target: string;
  estimated_time_seconds: number;
  choices: Choice[];
};

type AttemptResult = {
  AttemptID: string;
  Correct: boolean;
  CorrectAnswer: string;
  Explanation: string;
  DistractorRationales: Record<string, string>;
};

type Phase = 'loading' | 'unauth' | 'empty' | 'practicing' | 'done' | 'error';

export default function PracticePage() {
  const [phase, setPhase] = useState<Phase>('loading');
  const [items, setItems] = useState<ServedItem[]>([]);
  const [idx, setIdx] = useState(0);
  const [chosen, setChosen] = useState<string | null>(null);
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number>(Date.now());

  useEffect(() => {
    (async () => {
      try {
        const me = await fetch('/api/me', { credentials: 'include' });
        if (me.status === 401) {
          setPhase('unauth');
          return;
        }
        const res = await fetch('/api/sessions/quick-boost?count=5', { credentials: 'include' });
        if (!res.ok) {
          if (res.status === 404) {
            setPhase('empty');
            return;
          }
          const body = await res.json().catch(() => ({}));
          setErrMsg(body.error ?? 'فشل التحميل');
          setPhase('error');
          return;
        }
        const body = await res.json();
        const list = (body.items ?? []) as ServedItem[];
        if (list.length === 0) {
          setPhase('empty');
          return;
        }
        setItems(list);
        setStartedAt(Date.now());
        setPhase('practicing');
      } catch {
        setPhase('error');
        setErrMsg('تعذر الاتصال بالخادم');
      }
    })();
  }, []);

  async function submit(choiceKey: string) {
    if (chosen) return;
    setChosen(choiceKey);
    const elapsed = Date.now() - startedAt;
    const res = await fetch('/api/attempts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        item_id: items[idx].id,
        choice_key: choiceKey,
        time_taken_ms: elapsed,
        hint_used: false,
      }),
    });
    if (!res.ok) {
      setErrMsg('فشل تسجيل الإجابة');
      return;
    }
    const body = (await res.json()) as AttemptResult;
    setResult(body);
    setScore((s) => ({ correct: s.correct + (body.Correct ? 1 : 0), total: s.total + 1 }));
  }

  function next() {
    setChosen(null);
    setResult(null);
    setStartedAt(Date.now());
    if (idx + 1 >= items.length) {
      setPhase('done');
      return;
    }
    setIdx(idx + 1);
  }

  if (phase === 'loading') return <Center>جارٍ التحميل…</Center>;
  if (phase === 'unauth')
    return (
      <Center>
        <p className="mb-4">يجب تسجيل الدخول.</p>
        <Link href="/login" className="rounded-lg bg-blue-600 px-4 py-2 text-white">
          تسجيل الدخول
        </Link>
      </Center>
    );
  if (phase === 'empty')
    return (
      <Center>
        <p className="mb-4">لا توجد أسئلة جديدة الآن. عُد لاحقاً.</p>
        <Link href="/" className="rounded-lg bg-blue-600 px-4 py-2 text-white">
          الصفحة الرئيسية
        </Link>
      </Center>
    );
  if (phase === 'error')
    return (
      <Center>
        <p className="mb-4 text-red-600">{errMsg ?? 'خطأ غير متوقع'}</p>
      </Center>
    );
  if (phase === 'done') {
    return (
      <Center>
        <h2 className="text-3xl font-bold">انتهت الجلسة</h2>
        <p className="mt-3 text-2xl">
          {score.correct} / {score.total}
        </p>
        <Link
          href="/practice"
          className="mt-6 rounded-xl bg-blue-600 px-6 py-3 text-white"
          onClick={() => location.reload()}
        >
          جلسة جديدة
        </Link>
      </Center>
    );
  }

  const item = items[idx];
  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between text-sm text-neutral-500">
        <span>
          {idx + 1} / {items.length}
        </span>
        <span>{item.topic}</span>
      </div>
      <h2 className="text-xl leading-relaxed">{item.question_text}</h2>

      <div className="mt-6 space-y-3">
        {item.choices.map((c) => {
          const isChosen = chosen === c.key;
          const isCorrect = result && c.key === result.CorrectAnswer;
          const isWrongChosen = result && isChosen && !result.Correct;
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => submit(c.key)}
              disabled={!!chosen}
              className={
                'block w-full rounded-xl border px-5 py-4 text-start text-lg transition ' +
                (isCorrect
                  ? 'border-green-600 bg-green-50 dark:bg-green-950'
                  : isWrongChosen
                    ? 'border-red-600 bg-red-50 dark:bg-red-950'
                    : isChosen
                      ? 'border-blue-600 bg-blue-50 dark:bg-blue-950'
                      : 'border-neutral-300 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-900')
              }
            >
              <span className="ms-2 font-bold">{c.key}.</span> {c.text}
            </button>
          );
        })}
      </div>

      {result && (
        <div className="mt-6 rounded-xl border border-neutral-300 bg-neutral-50 p-5 dark:border-neutral-700 dark:bg-neutral-900">
          <p className="font-semibold">
            {result.Correct ? 'إجابة صحيحة' : `الصحيح: ${result.CorrectAnswer}`}
          </p>
          <p className="mt-2 leading-relaxed text-neutral-700 dark:text-neutral-300">
            {result.Explanation}
          </p>
          <button
            type="button"
            onClick={next}
            className="mt-5 rounded-lg bg-blue-600 px-5 py-2 text-white"
          >
            التالي
          </button>
        </div>
      )}
    </main>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {children}
    </main>
  );
}
