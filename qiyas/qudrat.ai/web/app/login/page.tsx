'use client';

// Login flow: choose phone or email, request an OTP, enter the code,
// land on /practice. The session cookie is set HttpOnly by the Go API,
// so the client never sees the token; subsequent requests are credentialed
// by virtue of being same-origin.

import { useRouter } from 'next/navigation';
import { useState } from 'react';

type Step = 'identify' | 'verify';

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>('identify');
  const [channel, setChannel] = useState<'sms' | 'email'>('sms');
  const [identifier, setIdentifier] = useState('');
  const [challengeId, setChallengeId] = useState('');
  const [code, setCode] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const res = await fetch('/api/auth/otp/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel, identifier }),
        credentials: 'include',
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body.error ?? 'فشل الإرسال');
        return;
      }
      setChallengeId(body.challenge_id);
      setStep('verify');
    } finally {
      setPending(false);
    }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const res = await fetch('/api/auth/otp/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ challenge_id: challengeId, code }),
        credentials: 'include',
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body.error ?? 'رمز خاطئ');
        return;
      }
      router.push('/practice');
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-8 px-6 py-12">
      <h1 className="text-3xl font-bold">تسجيل الدخول</h1>

      {step === 'identify' && (
        <form onSubmit={start} className="space-y-5">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setChannel('sms')}
              className={
                'flex-1 rounded-lg border px-4 py-2 ' +
                (channel === 'sms'
                  ? 'border-blue-600 bg-blue-50 dark:bg-blue-950'
                  : 'border-neutral-300 dark:border-neutral-700')
              }
            >
              جوال
            </button>
            <button
              type="button"
              onClick={() => setChannel('email')}
              className={
                'flex-1 rounded-lg border px-4 py-2 ' +
                (channel === 'email'
                  ? 'border-blue-600 bg-blue-50 dark:bg-blue-950'
                  : 'border-neutral-300 dark:border-neutral-700')
              }
            >
              بريد
            </button>
          </div>
          <input
            type={channel === 'sms' ? 'tel' : 'email'}
            placeholder={channel === 'sms' ? '+9665XXXXXXXX' : 'name@example.com'}
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            dir="ltr"
            required
            className="w-full rounded-lg border border-neutral-300 bg-transparent px-4 py-3 text-lg dark:border-neutral-700"
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-xl bg-blue-600 px-6 py-3 text-white disabled:opacity-50"
          >
            {pending ? 'جارٍ الإرسال…' : 'أرسل رمز التحقق'}
          </button>
        </form>
      )}

      {step === 'verify' && (
        <form onSubmit={verify} className="space-y-5">
          <p className="text-neutral-600 dark:text-neutral-400">
            أرسلنا رمزاً إلى <span dir="ltr">{identifier}</span>
          </p>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]{6}"
            placeholder="000000"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            dir="ltr"
            required
            className="w-full rounded-lg border border-neutral-300 bg-transparent px-4 py-3 text-center text-2xl tracking-widest dark:border-neutral-700"
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-xl bg-blue-600 px-6 py-3 text-white disabled:opacity-50"
          >
            {pending ? 'جارٍ التحقق…' : 'تحقق'}
          </button>
          <button
            type="button"
            onClick={() => setStep('identify')}
            className="w-full text-sm text-neutral-500 hover:text-neutral-700"
          >
            تغيير الرقم/البريد
          </button>
        </form>
      )}
    </main>
  );
}
