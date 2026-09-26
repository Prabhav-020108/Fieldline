"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  ClipboardList,
  Clock,
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
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** Detect if an entry was synced from offline: created_at is significantly
 *  earlier than received_at (the server set received_at when it actually
 *  received the POST). A >10s delta means it was queued during an outage. */
function isSyncedFromOffline(entry: AuditLogEntry): boolean {
  if (!entry.received_at) return false;
  try {
    const created = new Date(entry.created_at).getTime();
    const received = new Date(entry.received_at).getTime();
    return received - created > 10_000; // >10s gap = offline-queued
  } catch {
    return false;
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

const AUTO_REFRESH_INTERVAL = 5000; // 5s -- fast enough for the demo

function AuditLogPageInner({ companyId }: { companyId: string }) {
  const [entries, setEntries] = useState<AuditLogEntry[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [toolFilter, setToolFilter] = useState<ToolName | "all">("all");
  const [autoRefresh, setAutoRefresh] = useState(true);

  // Track IDs we've already seen to highlight new arrivals
  const knownIdsRef = useRef<Set<string>>(new Set());
  const [newIds, setNewIds] = useState<Set<string>>(new Set());

  const load = useCallback(
    () =>
      listAuditLog(companyId)
        .then((data) => {
          // Detect new entries
          const freshIds = new Set<string>();
          for (const entry of data) {
            if (!knownIdsRef.current.has(entry.id)) {
              freshIds.add(entry.id);
            }
          }
          // Update known IDs
          for (const entry of data) {
            knownIdsRef.current.add(entry.id);
          }
          if (freshIds.size > 0 && entries !== null) {
            // Only flash new entries after the initial load
            setNewIds(freshIds);
            // Clear the highlight after animation
            setTimeout(() => setNewIds(new Set()), 2500);
          }
          setEntries(data);
          setLoadError(null);
        })
        .catch((err: unknown) => {
          setLoadError(err instanceof Error ? err.message : "Could not load the audit log.");
        }),
    [companyId, entries],
  );

  // Manual refresh button handler
  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  // Initial load
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  // Auto-refresh loop
  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => {
      listAuditLog(companyId)
        .then((data) => {
          const freshIds = new Set<string>();
          for (const entry of data) {
            if (!knownIdsRef.current.has(entry.id)) {
              freshIds.add(entry.id);
            }
          }
          for (const entry of data) {
            knownIdsRef.current.add(entry.id);
          }
          if (freshIds.size > 0) {
            setNewIds(freshIds);
            setTimeout(() => setNewIds(new Set()), 2500);
          }
          setEntries(data);
          setLoadError(null);
        })
        .catch(() => {});
    }, AUTO_REFRESH_INTERVAL);
    return () => clearInterval(id);
  }, [companyId, autoRefresh]);

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
    const offlineSynced = entries.filter(isSyncedFromOffline).length;
    return { total, safetyCalls: safetyCalls.length, belowFloor, uniqueTools, offlineSynced };
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
        <div className="flex items-center gap-2.5">
          {/* Live indicator */}
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full border cursor-pointer transition-all duration-300 ${
              autoRefresh
                ? "text-emerald-700 bg-emerald-50 border-emerald-200/70"
                : "text-[var(--ink-faint)] bg-[var(--surface-sunken)] border-[var(--line)]"
            }`}
            title={autoRefresh ? "Auto-refresh ON (every 5s)" : "Auto-refresh paused"}
          >
            {autoRefresh && (
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
            )}
            <span>{autoRefresh ? "LIVE" : "Paused"}</span>
          </button>
          <Button variant="secondary" size="sm" onClick={refresh} disabled={refreshing}>
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            {refreshing ? "Refreshing" : "Refresh"}
          </Button>
        </div>
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
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
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
          <StatCard
            icon={<Clock size={16} />}
            label="Synced from offline"
            value={stats.offlineSynced}
            tone={stats.offlineSynced > 0 ? "cyan" : undefined}
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
            <AuditEntryCard
              key={entry.id}
              entry={entry}
              isNew={newIds.has(entry.id)}
            />
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
  tone?: "amber" | "cyan";
}) {
  return (
    <Card>
      <div className="flex items-center gap-2 text-[var(--ink-muted)]">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      <p
        className={`mt-3 text-3xl font-semibold tracking-tight ${
          tone === "amber" && value > 0
            ? "text-[var(--amber)]"
            : tone === "cyan" && value > 0
              ? "text-cyan-600"
              : "text-[var(--ink)]"
        }`}
      >
        {value}
      </p>
    </Card>
  );
}

function AuditEntryCard({ entry, isNew }: { entry: AuditLogEntry; isNew: boolean }) {
  const syncedOffline = isSyncedFromOffline(entry);

  // Calculate sync delay for offline entries
  let syncDelay = "";
  if (syncedOffline && entry.received_at) {
    const created = new Date(entry.created_at).getTime();
    const received = new Date(entry.received_at).getTime();
    const delaySec = Math.round((received - created) / 1000);
    if (delaySec < 60) {
      syncDelay = `${delaySec}s`;
    } else {
      syncDelay = `${Math.floor(delaySec / 60)}m ${delaySec % 60}s`;
    }
  }

  return (
    <div
      className={`bg-[var(--surface)] border rounded-[var(--radius-md)] p-5 transition-all duration-700 ${
        isNew
          ? "border-emerald-400 ring-2 ring-emerald-300/50 shadow-[0_0_16px_rgba(16,185,129,0.15)]"
          : syncedOffline
            ? "border-cyan-300/70"
            : "border-[var(--line)]"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 flex-wrap">
          <Badge tone={TOOL_BADGE_TONE[entry.tool_name]}>
            <span className="flex items-center gap-1.5">
              {TOOL_ICONS[entry.tool_name]}
              {TOOL_LABELS[entry.tool_name]}
            </span>
          </Badge>
          {entry.tool_name === "safety_procedure" ? <ConfidenceBadge entry={entry} /> : null}
          {syncedOffline && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold text-cyan-700 bg-cyan-50 border border-cyan-200/70 rounded-full uppercase tracking-wide">
              <Clock size={10} />
              Synced from offline
              {syncDelay && <span className="font-normal">({syncDelay} delay)</span>}
            </span>
          )}
          {isNew && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200/70 rounded-full uppercase tracking-wide animate-pulse">
              ● NEW
            </span>
          )}
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
