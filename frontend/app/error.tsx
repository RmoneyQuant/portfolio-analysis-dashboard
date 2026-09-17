"use client";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="rounded-lg border border-rose-300 bg-rose-50 dark:bg-rose-950/40 p-4 text-sm">
      <p className="font-semibold text-rose-700 dark:text-rose-300">Couldn’t load data</p>
      <p className="mt-1 text-rose-600 dark:text-rose-400">{error.message}</p>
      <p className="mt-2 text-neutral-500">
        Is the API running? <code>uv run uvicorn api:app --reload --port 8000</code>
      </p>
      <button
        onClick={reset}
        className="mt-3 rounded border border-rose-300 px-3 py-1 text-rose-700 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/40"
      >
        Retry
      </button>
    </div>
  );
}
