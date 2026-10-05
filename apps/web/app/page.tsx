// Phase 0 placeholder. The full UI shell is built in Phase 1 (SPEC.md §11).
export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3">
      <h1 className="font-mono text-2xl tracking-tight">wyrd.exe</h1>
      <p className="text-sm text-neutral-400">
        Story engine backend is running. The interface arrives in Phase 1.
      </p>
      <a className="text-sm text-violet-400 hover:underline" href="http://127.0.0.1:8000/api/health">
        API health →
      </a>
    </main>
  );
}
