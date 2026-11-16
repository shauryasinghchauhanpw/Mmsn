"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "../../lib/api";

function friendlyError(e: unknown): string {
  const msg = e instanceof Error ? e.message : "Sign-in failed";
  if (msg.includes("LOGIN_BAD_CREDENTIALS")) return "Wrong email or password.";
  if (msg.includes("Failed to fetch"))
    return "Could not reach the server — is the backend running?";
  return msg;
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(email.trim(), password);
      router.replace("/");
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-md space-y-6">
      <section>
        <h1 className="text-2xl font-bold text-white">Sign in</h1>
        <p className="mt-1 text-sm text-gray-400">
          Your projects belong to your account — nobody else can see them.
        </p>
      </section>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/60 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-xl border border-gray-800 bg-panel p-5"
      >
        <label className="block text-sm text-gray-300">
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="mt-1 w-full rounded-lg border border-gray-700 bg-ink px-3 py-2.5 text-sm text-white placeholder-gray-500"
          />
        </label>
        <label className="block text-sm text-gray-300">
          Password
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Your password"
            className="mt-1 w-full rounded-lg border border-gray-700 bg-ink px-3 py-2.5 text-sm text-white placeholder-gray-500"
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-amber-500 px-4 py-3 font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="text-center text-sm text-gray-400">
        No account yet?{" "}
        <Link href="/register" className="font-medium text-amber-500">
          Create one
        </Link>
      </p>
    </div>
  );
}
