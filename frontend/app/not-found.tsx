import Link from "next/link";

export default function NotFound() {
  return (
    <div className="text-sm">
      <p className="font-semibold">Not found</p>
      <p className="mt-1 text-neutral-500">That portfolio or rebalance date doesn’t exist.</p>
      <Link href="/" className="mt-3 inline-block text-blue-600 dark:text-blue-400 hover:underline">
        ← all portfolios
      </Link>
    </div>
  );
}
