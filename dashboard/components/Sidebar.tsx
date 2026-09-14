"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Plus, Radio } from "lucide-react";

import { listCompanies } from "@/lib/api";
import type { Company } from "@/lib/types";

export default function Sidebar() {
  const pathname = usePathname();
  const [companies, setCompanies] = useState<Company[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCompanies()
      .then((data) => {
        if (!cancelled) setCompanies(data);
      })
      .catch(() => {
        if (!cancelled) setCompanies([]);
      });
    return () => {
      cancelled = true;
    };
    // Re-fetch whenever the route changes, so a newly created company
    // shows up here without a manual refresh.
  }, [pathname]);

  return (
    <aside className="w-64 shrink-0 border-r border-[var(--line)] bg-[var(--surface)] flex flex-col h-screen sticky top-0">
      <div className="px-5 pt-6 pb-5">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--brand)] text-white">
            <Radio size={16} />
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-[var(--ink)]">
            FieldLine
          </span>
        </Link>
        <p className="mt-1.5 text-xs text-[var(--ink-faint)] pl-[42px]">Dispatch console</p>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-6">
        <div className="px-2 pb-2 flex items-center justify-between">
          <span className="text-xs font-medium text-[var(--ink-faint)]">Companies</span>
          <Link
            href="/"
            className="text-[var(--ink-faint)] hover:text-[var(--brand)] rounded p-0.5"
            aria-label="Add company"
          >
            <Plus size={14} />
          </Link>
        </div>

        {companies === null ? (
          <div className="px-2 py-2 text-sm text-[var(--ink-faint)]">Loading...</div>
        ) : companies.length === 0 ? (
          <Link
            href="/"
            className="block px-2 py-2 text-sm text-[var(--brand)] hover:underline"
          >
            Add your first company
          </Link>
        ) : (
          <ul className="space-y-0.5">
            {companies.map((company) => {
              const active = pathname?.startsWith(`/companies/${company.id}`);
              return (
                <li key={company.id}>
                  <Link
                    href={`/companies/${company.id}`}
                    className={`flex flex-col rounded-[var(--radius-sm)] px-3 py-2 text-sm transition-colors ${
                      active
                        ? "bg-[var(--brand-tint)] text-[var(--brand-strong)] font-medium"
                        : "text-[var(--ink-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--ink)]"
                    }`}
                  >
                    <span className="truncate">{company.name}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      <div className="px-5 py-4 border-t border-[var(--line)]">
        <p className="text-xs text-[var(--ink-faint)] leading-relaxed">
          Each company keeps its own Moss index -- job history, safety
          procedures, and inventory never cross between companies.
        </p>
      </div>
    </aside>
  );
}