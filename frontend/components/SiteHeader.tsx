"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, clearToken, getToken } from "../lib/api";

// Site header + auth guard. On every page except /login and /register:
// no token (or a token the server rejects) sends the user to /login.
// When signed in it shows the user's email and a Sign out button.
export default function SiteHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  const isAuthPage = pathname === "/login" || pathname === "/register";

  useEffect(() => {
    if (isAuthPage) {
      setEmail(null);
      return;
    }
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    api
      .getMe()
      .then((me) => {
        if (!cancelled) setEmail(me.email);
      })
      .catch(() => {
        if (cancelled) return;
        clearToken();
        router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [pathname, isAuthPage, router]);

  function signOut() {
    api.logout();
    setEmail(null);
    router.replace("/login");
  }

  return (
    <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
      <a href="/" className="text-xl font-bold text-white">
        ✂️ MMSN <span className="text-amber-500">Clipper</span>
      </a>
      {email ? (
        <span className="flex items-center gap-2">
          <span className="hidden max-w-44 truncate rounded-full bg-gray-800 px-3 py-1 text-xs text-gray-300 sm:inline-block">
            {email}
          </span>
          <button
            onClick={signOut}
            className="rounded-full bg-gray-800 px-3 py-1 text-xs font-medium text-white hover:bg-gray-700"
          >
            Sign out
          </button>
        </span>
      ) : (
        <span className="rounded-full bg-gray-800 px-3 py-1 text-xs text-gray-400">
          {isAuthPage ? "Sign in to continue" : "Phase 2 — signed-in accounts"}
        </span>
      )}
    </div>
  );
}
