"use client";

import { useEffect, useRef, useState } from "react";
import { Radio, Wifi, WifiOff, Zap } from "lucide-react";
import { checkBackendHealth, type ConnectivityStatus, type HealthResult } from "@/lib/api";

/**
 * Connectivity Indicator -- Phase 11 rewrite for demo day.
 *
 * Three key improvements over the Phase 10 version:
 * 1. Polls every 3s (was 15s) so the kill-switch flip is near-instant
 * 2. CSS transition animations on status change -- green→red is dramatic
 * 3. "Large" variant for the company header that's visible from across the room
 */

// --- Shared connectivity state so multiple instances stay in sync ---
type Listener = () => void;
let _health: HealthResult | null = null;
let _prevStatus: ConnectivityStatus | null = null;
let _statusChangedAt: number = Date.now();
let _listeners: Listener[] = [];
let _intervalId: ReturnType<typeof setInterval> | null = null;

function subscribe(fn: Listener) {
  _listeners.push(fn);
  if (_intervalId === null) {
    // Start the shared poll
    const probe = async () => {
      const res = await checkBackendHealth();
      if (_health === null || res.status !== _health.status) {
        _prevStatus = _health?.status ?? null;
        _statusChangedAt = Date.now();
      }
      _health = res;
      _listeners.forEach((l) => l());
    };
    probe();
    _intervalId = setInterval(probe, 3000);
  }
  return () => {
    _listeners = _listeners.filter((l) => l !== fn);
    if (_listeners.length === 0 && _intervalId !== null) {
      clearInterval(_intervalId);
      _intervalId = null;
    }
  };
}

function useHealth() {
  const [, rerender] = useState(0);
  useEffect(() => {
    return subscribe(() => rerender((n) => n + 1));
  }, []);
  return { health: _health, prevStatus: _prevStatus, changedAt: _statusChangedAt };
}

// --- Time-ago helper ---
function timeAgo(ts: number): string {
  const delta = Math.round((Date.now() - ts) / 1000);
  if (delta < 5) return "just now";
  if (delta < 60) return `${delta}s ago`;
  const mins = Math.floor(delta / 60);
  return `${mins}m ago`;
}

// --- Main component ---
export function ConnectivityIndicator({
  compact = false,
  variant = "default",
}: {
  compact?: boolean;
  variant?: "default" | "banner";
}) {
  const { health, prevStatus, changedAt } = useHealth();
  const [elapsed, setElapsed] = useState("");
  const flashRef = useRef(false);

  // Update elapsed timer every second
  useEffect(() => {
    const tick = () => setElapsed(timeAgo(changedAt));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [changedAt]);

  // Detect status change for flash animation
  const didChange = prevStatus !== null && health !== null && prevStatus !== health.status;
  if (didChange && !flashRef.current) flashRef.current = true;

  // Clear flash after animation
  useEffect(() => {
    if (flashRef.current) {
      const timer = setTimeout(() => {
        flashRef.current = false;
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [changedAt]);

  if (health === null) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs text-[var(--ink-faint)] rounded-full border border-[var(--line)] bg-[var(--surface-sunken)]">
        <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-pulse" />
        <span>Checking...</span>
      </div>
    );
  }

  if (variant === "banner") {
    return <BannerIndicator health={health} elapsed={elapsed} />;
  }

  const status = health.status;

  if (status === "edge") {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full transition-all duration-500
          text-cyan-700 bg-cyan-50 border border-cyan-200/70
          ${flashRef.current ? "ring-2 ring-cyan-400 ring-offset-1 scale-105" : ""}`}
        title={`Edge stack • ${health.latencyMs}ms • ${elapsed}`}
      >
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500" />
        </span>
        <Radio size={12} className="shrink-0 text-cyan-600" />
        <span>{compact ? "Edge" : "Edge Stack"}</span>
        {!compact && (
          <span className="text-cyan-500/70 text-[10px] font-normal">{health.latencyMs}ms</span>
        )}
      </div>
    );
  }

  if (status === "online") {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full transition-all duration-500
          text-emerald-700 bg-emerald-50 border border-emerald-200/70
          ${flashRef.current ? "ring-2 ring-emerald-400 ring-offset-1 scale-105" : ""}`}
        title={`Cloud connected • ${health.latencyMs}ms • ${elapsed}`}
      >
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        <Wifi size={12} className="shrink-0 text-emerald-600" />
        <span>{compact ? "Cloud" : "Cloud Connected"}</span>
      </div>
    );
  }

  // Offline
  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full transition-all duration-500
        text-red-700 bg-red-50 border border-red-300/70
        ${flashRef.current ? "ring-2 ring-red-400 ring-offset-1 scale-110 animate-pulse" : ""}`}
      title={`Backend offline since ${elapsed} • Sync queue active`}
    >
      <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
      <WifiOff size={12} className="shrink-0 text-red-600" />
      <span>{compact ? "Offline" : "Backend Offline"}</span>
      {!compact && (
        <span className="text-red-500/70 text-[10px] font-normal">{elapsed}</span>
      )}
    </div>
  );
}

// --- Large banner variant for the company header ---
function BannerIndicator({ health, elapsed }: { health: HealthResult; elapsed: string }) {
  const status = health.status;

  if (status === "edge") {
    return (
      <div className="flex items-center gap-3 px-4 py-2.5 rounded-[var(--radius-md)] bg-gradient-to-r from-cyan-500/10 to-teal-500/10 border border-cyan-300/50 transition-all duration-700">
        <div className="relative">
          <span className="animate-ping absolute inline-flex h-3.5 w-3.5 rounded-full bg-cyan-400 opacity-50" />
          <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-cyan-500" />
        </div>
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <Zap size={14} className="text-cyan-600" />
            <span className="text-sm font-semibold text-cyan-800 tracking-tight">
              Edge Stack Active
            </span>
          </div>
          <span className="text-[11px] text-cyan-600/80">
            Local LLM • {health.latencyMs}ms latency • {elapsed}
          </span>
        </div>
      </div>
    );
  }

  if (status === "online") {
    return (
      <div className="flex items-center gap-3 px-4 py-2.5 rounded-[var(--radius-md)] bg-gradient-to-r from-emerald-500/10 to-green-500/10 border border-emerald-300/50 transition-all duration-700">
        <span className="inline-flex rounded-full h-3.5 w-3.5 bg-emerald-500" />
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <Wifi size={14} className="text-emerald-600" />
            <span className="text-sm font-semibold text-emerald-800 tracking-tight">
              Cloud Connected
            </span>
          </div>
          <span className="text-[11px] text-emerald-600/80">
            {health.latencyMs}ms latency • {elapsed}
          </span>
        </div>
      </div>
    );
  }

  // Offline -- the dramatic red banner judges can see from across the room
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 rounded-[var(--radius-md)] bg-gradient-to-r from-red-500/15 to-rose-500/15 border-2 border-red-400/70 animate-pulse transition-all duration-700">
      <span className="inline-flex rounded-full h-3.5 w-3.5 bg-red-500 animate-ping" />
      <div className="flex flex-col">
        <div className="flex items-center gap-2">
          <WifiOff size={14} className="text-red-600" />
          <span className="text-sm font-bold text-red-800 tracking-tight uppercase">
            No Internet — Running Offline
          </span>
        </div>
        <span className="text-[11px] text-red-600/80 font-medium">
          Voice + AI continue locally • Sync queue active • {elapsed}
        </span>
      </div>
    </div>
  );
}
