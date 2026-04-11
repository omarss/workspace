import { Header } from "@/components/layout/header";
import { AnonymousBanner } from "@/components/auth/anonymous-banner";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background">
      <AnonymousBanner />
      <Header />
      <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
    </div>
  );
}
