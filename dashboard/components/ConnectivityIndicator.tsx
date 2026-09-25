"use client";

import { useEffect, useState } from "react";
import { Radio, Wifi, WifiOff } from "lucide-react";
import { checkBackendHealth, type ConnectivityStatus } from "@/lib/api";

export function ConnectivityIndicator({ compact = false }: { compact?: boolean }) {
  const [status, setStatus] = useState<ConnectivityStatus | null>(null);
  const [apiUrl, setApiUrl] = useState<string>("");

  useEffect(() => {
    let mounted = true;

    const probe = async () => {
      const res = await checkBackendHealth();
      if (mounted) {
        setStatus(res.status);
        setApiUrl(res.url);
      }
    };

    probe();
    const interval = setInterval(probe, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  if (status === null) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs text-[var(--ink-faint)] rounded-full border border-[var(--line)] bg-[var(--surface-sunken)]">
        <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-pulse" />
        <span>Checking...</span>
      </div>
    );
  }

  if (status === "edge") {
    return (
      <div
        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-cyan-700 bg-cyan-50 border border-cyan-200/70 rounded-full"
        title={`Edge stack active at ${apiUrl}. Self-hosted LiveKit, Ollama, & SQLite operational.`}
      >
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500" />
        </span>
        <Radio size={12} className="shrink-0 text-cyan-600" />
        <span>{compact ? "Edge" : "Edge Stack (Local)"}</span>
      </div>
    );
  }

  if (status === "online") {
    return (
      <div
        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200/70 rounded-full"
        title={`Connected to cloud backend at ${apiUrl}.`}
      >
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        <Wifi size={12} className="shrink-0 text-emerald-600" />
        <span>{compact ? "Cloud" : "Cloud Connected"}</span>
      </div>
    );
  }

  return (
    <div
      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-amber-800 bg-amber-50 border border-amber-200/70 rounded-full"
      title={`Backend unreachable at ${apiUrl}. Offline fallback and durable sync queue are engaged.`}
    >
      <span className="h-2 w-2 rounded-full bg-amber-500" />
      <WifiOff size={12} className="shrink-0 text-amber-600" />
      <span>{compact ? "Offline" : "Backend Offline (Queuing)"}</span>
    </div>
  );
}
