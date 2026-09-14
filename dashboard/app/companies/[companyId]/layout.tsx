"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { getCompany, syncCompanyNow } from "@/lib/api";
import { INDUSTRIES, type Company } from "@/lib/types";
import { Badge, Button, InlineNote, Spinner } from "@/components/ui";

const TABS: { href: string; label: string }[] = [
  { href: "", label: "Overview" },
  { href: "/jobs", label: "Jobs" },
  { href: "/safety", label: "Safety procedures" },
  { href: "/audit", label: "Audit log" },
  { href: "/inventory", label: "Inventory" },
  { href: "/call", label: "Talk to agent" },
];

export default function CompanyLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ companyId: string }>();
  // Keying by companyId forces a full remount on company switch, so
  // `company`/`notFound` below always start fresh for the new company.
  return (
    <CompanyLayoutInner key={params.companyId} companyId={params.companyId}>
      {children}
    </CompanyLayoutInner>
  );
}

function CompanyLayoutInner({
  companyId,
  children,
}: {
  companyId: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  const [company, setCompany] = useState<Company | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<{ tone: "success" | "danger"; message: string } | null>(
    null
  );

  useEffect(() => {
    getCompany(companyId)
      .then(setCompany)
      .catch(() => setNotFound(true));
  }, [companyId]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const result = await syncCompanyNow(companyId);
      setSyncResult({
        tone: "success",
        message: `Synced ${result.synced_documents} documents to Moss.`,
      });
    } catch (err) {
      setSyncResult({
        tone: "danger",
        message: err instanceof Error ? err.message : "Sync failed.",
      });
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncResult(null), 5000);
    }
  };

  if (notFound) {
    return (
      <div className="max-w-3xl mx-auto px-8 py-16 text-center">
        <p className="text-base font-medium text-[var(--ink)]">No company called &quot;{companyId}&quot;</p>
        <p className="text-sm text-[var(--ink-muted)] mt-1.5">
          <Link href="/" className="text-[var(--brand)] hover:underline">
            Back to companies
          </Link>
        </p>
      </div>
    );
  }

  const basePath = `/companies/${companyId}`;
  const industryLabel = company
    ? INDUSTRIES.find((i) => i.value === company.industry)?.label ?? company.industry
    : "";

  return (
    <div>
      <div className="border-b border-[var(--line)] bg-[var(--surface)]">
        <div className="max-w-5xl mx-auto px-8 pt-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              {company ? (
                <>
                  <div className="flex items-center gap-2.5">
                    <h1 className="text-xl font-semibold text-[var(--ink)] tracking-tight">
                      {company.name}
                    </h1>
                    <Badge tone="neutral">{industryLabel}</Badge>
                  </div>
                  <p className="text-xs font-mono text-[var(--ink-faint)] mt-1.5">
                    index: {company.moss_index_name} &nbsp;/&nbsp; room: fieldline-{company.id}
                  </p>
                </>
              ) : (
                <div className="flex items-center gap-2 text-sm text-[var(--ink-muted)] h-8">
                  <Spinner /> Loading company...
                </div>
              )}
            </div>
            <div className="flex items-center gap-3">
              {syncResult ? <InlineNote tone={syncResult.tone}>{syncResult.message}</InlineNote> : null}
              <Button
                variant="secondary"
                size="sm"
                onClick={handleSync}
                disabled={syncing || !company}
              >
                <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
                {syncing ? "Syncing" : "Sync to Moss"}
              </Button>
            </div>
          </div>

          <nav className="flex gap-1 mt-6 -mb-px">
            {TABS.map((tab) => {
              const href = `${basePath}${tab.href}`;
              const active = tab.href === "" ? pathname === basePath : pathname?.startsWith(href);
              return (
                <Link
                  key={tab.href}
                  href={href}
                  className={`px-4 py-2.5 text-sm border-b-2 transition-colors ${
                    active
                      ? "border-[var(--brand)] text-[var(--ink)] font-medium"
                      : "border-transparent text-[var(--ink-muted)] hover:text-[var(--ink)]"
                  }`}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-8 py-8">{children}</div>
    </div>
  );
}