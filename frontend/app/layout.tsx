import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "HPC39 Portfolio Dashboard",
  description: "Deposits, withdrawals, XIRR, CAGR and per-rebalance holdings for the HPC39 portfolios",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-neutral-200 dark:border-neutral-800">
          <div className="mx-auto max-w-6xl px-4 py-3 flex items-center gap-4">
            <Link href="/" className="font-semibold tracking-tight">
              HPC39 Dashboard
            </Link>
            <nav className="text-sm text-neutral-500 flex gap-3">
              {[5, 7, 8, 10].map((p) => (
                <Link key={p} href={`/portfolio/${p}`} className="hover:text-neutral-900 dark:hover:text-neutral-100">
                  HPC39_{p}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
