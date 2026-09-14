"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  ClipboardList,
  Filter,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from "lucide-react";

import { listAuditLog } from "@/lib/api";
import { TOOL_LABELS, type AuditLogEntry, type ToolName } from "@/lib/types";
import { Badge, Button, Card, EmptyState, Select, Spinner } from "@/components/ui";

const TOOL_ICONS: Record<ToolName, React.ReactNode> = {
  fault_history: <Wrench size={14} />,
  safety_procedure: <ShieldAlert size={14} />,
  inventory_lookup: <Boxes size={14} />,
  dispatch_status: <ClipboardList size={14} />,
  log_job_note: <ClipboardList size={14} />,
};

const TOOL_BADGE_TONE: Record<ToolName, "brand" | "warning" | "info" | "neutral"> = {
  fault_history: "info",
  safety_procedure: "warning",
  inventory_lookup: "brand",
  dispatch_status: "neutral",
  log_job_note: "neutral",
};

function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function ConfidenceBadge({ entry }: { entry: AuditLogEntry }) {
  if (entry.confidence_score === null) {
    return <Badge tone="neutral">No match</Badge>;
  }
  const pct = Math.round(entry.confidence_score * 100);
  if (entry.below_confidence_floor) {
    return <Badge tone="danger">{pct}% -- below floor</Badge>;
  }
  return <Badge tone="success">{pct}% confident</Badge>;
}

export default function AuditLogPage() {
  const params = useParams<{ companyId: string }>();
  return <AuditLogPageInner key={params.companyId} companyId={params.companyId} />;
}

function AuditLogPageInner({ companyId }: { companyId: string }) {
  const [entries, setEntries] = useState<AuditLogEntry[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [toolFilter, setToolFilter] = useState<ToolName | "all">("all");

  const refresh = async () => {
    setRefreshing(true);
    try {
      const data = await listAuditLog(companyId);
      setEntries(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load the audit log.");
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const filtered = useMemo(() => {
    if (!entries) return null;
    if (toolFilter === "all") return entries;
    return entries.filter((e) => e.tool_name === toolFilter);
  }, [entries, toolFilter]);

  const stats = useMemo(() => {
    if (!entries) return null;
    const total = entries.length;
    const safetyCalls = entries.filter((e) => e.tool_name === "safety_procedure");
    const belowFloor = safetyCalls.filter((e) => e.below_confidence_floor).length;
    const uniqueTools = new Set(entries.map((e) => e.tool_name)).size;
    return { total, safetyCalls: safetyCalls.length, belowFloor, uniqueTools };
  }, [entries]);

  return (
    <div>
      <div className="flex items-start justify-between mb-5 gap-4">
        <div>
          <h2 className="text-base font-semibold text-[var(--ink)]">Audit log</h2>
          <p className="text-sm text-[var(--ink-muted)] mt-0.5 max-w-lg">
            Every question the agent answered on a call, what it said back,
            and -- for safety procedures -- how confident it was and where
            the answer came from.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={refresh} disabled={refreshing}>
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          {refreshing ? "Refreshing" : "Refresh"}
        </Button>
      </div>

      {loadError ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--danger)]/25 bg-[var(--danger-tint)] px-5 py-4 text-sm text-[var(--danger)] mb-6">
          Couldn&apos;t reach the FieldLine backend at{" "}
          <code className="font-mono">
            {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
          </code>
          .
        </div>
      ) : null}

      {stats ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <StatCard
            icon={<ClipboardList size={16} />}
            label="Total tool calls"
            value={stats.total}
          />
          <StatCard
            icon={<ShieldAlert size={16} />}
            label="Safety procedure queries"
            value={stats.safetyCalls}
          />
          <StatCard
            icon={<AlertTriangle size={16} />}
            label="Below confidence floor"
            value={stats.belowFloor}
            tone={stats.belowFloor > 0 ? "amber" : undefined}
          />
        </div>
      ) : null}

      <div className="flex items-center gap-2.5 rounded-[var(--radius-md)] border border-[var(--line)] bg-[var(--surface)] px-4 py-3 mb-5">
        <Filter size={14} className="text-[var(--ink-faint)] shrink-0" />
        <span className="text-sm text-[var(--ink-muted)] shrink-0">Tool</span>
        <Select
          value={toolFilter}
          onChange={(e) => setToolFilter(e.target.value as ToolName | "all")}
          className="max-w-xs"
        >
          <option value="all">All tools</option>
          {(Object.keys(TOOL_LABELS) as ToolName[]).map((tool) => (
            <option key={tool} value={tool}>
              {TOOL_LABELS[tool]}
            </option>
          ))}
        </Select>
        {filtered ? (
          <span className="text-xs text-[var(--ink-faint)] ml-auto">
            {filtered.length} {filtered.length === 1 ? "entry" : "entries"}
          </span>
        ) : null}
      </div>

      {filtered === null ? (
        <div className="flex items-center gap-2 text-sm text-[var(--ink-muted)] py-10">
          <Spinner /> Loading audit log...
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No audit entries yet"
          description="Entries appear here automatically the first time the voice agent answers a technician on a call for this company."
          action={
            <ShieldCheck size={28} className="text-[var(--ink-faint)] mx-auto mb-1" />
          }
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((entry) => (
            <AuditEntryCard key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone?: "amber";
}) {
  return (
    <Card>
      <div className="flex items-center gap-2 text-[var(--ink-muted)]">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      <p
        className={`mt-3 text-3xl font-semibold tracking-tight ${
          tone === "amber" && value > 0 ? "text-[var(--amber)]" : "text-[var(--ink)]"
        }`}
      >
        {value}
      </p>
    </Card>
  );
}

function AuditEntryCard({ entry }: { entry: AuditLogEntry }) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-md)] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 flex-wrap">
          <Badge tone={TOOL_BADGE_TONE[entry.tool_name]}>
            <span className="flex items-center gap-1.5">
              {TOOL_ICONS[entry.tool_name]}
              {TOOL_LABELS[entry.tool_name]}
            </span>
          </Badge>
          {entry.tool_name === "safety_procedure" ? <ConfidenceBadge entry={entry} /> : null}
        </div>
        <span className="text-xs text-[var(--ink-faint)] font-mono shrink-0">
          {formatTimestamp(entry.created_at)}
        </span>
      </div>

      <div className="mt-3.5 grid grid-cols-1 sm:grid-cols-[minmax(0,220px)_1fr] gap-x-6 gap-y-1">
        <span className="text-xs font-medium text-[var(--ink-faint)] uppercase tracking-wide pt-0.5">
          Technician asked
        </span>
        <p className="text-sm text-[var(--ink)]">{entry.query_text}</p>
      </div>

      <div className="mt-2.5 grid grid-cols-1 sm:grid-cols-[minmax(0,220px)_1fr] gap-x-6 gap-y-1">
        <span className="text-xs font-medium text-[var(--ink-faint)] uppercase tracking-wide pt-0.5">
          Agent responded
        </span>
        <p className="text-sm text-[var(--ink-muted)] leading-relaxed whitespace-pre-wrap">
          {entry.response_text}
        </p>
      </div>

      {entry.source_citation ? (
        <div className="mt-2.5 grid grid-cols-1 sm:grid-cols-[minmax(0,220px)_1fr] gap-x-6 gap-y-1">
          <span className="text-xs font-medium text-[var(--ink-faint)] uppercase tracking-wide pt-0.5">
            Source
          </span>
          <p className="text-sm text-[var(--brand-strong)] font-mono">{entry.source_citation}</p>
        </div>
      ) : null}
    </div>
  );
}