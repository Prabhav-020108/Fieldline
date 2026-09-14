"use client";

import { X } from "lucide-react";
import { useEffect } from "react";
import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
}

const buttonVariantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--brand)] text-white hover:bg-[var(--brand-strong)] disabled:opacity-50",
  secondary:
    "bg-white text-[var(--ink)] border border-[var(--line-strong)] hover:bg-[var(--surface-sunken)] disabled:opacity-50",
  ghost:
    "bg-transparent text-[var(--ink-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--ink)] disabled:opacity-50",
  danger:
    "bg-white text-[var(--danger)] border border-[var(--danger)]/30 hover:bg-[var(--danger-tint)] disabled:opacity-50",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  const sizeClasses = size === "sm" ? "h-8 px-3 text-sm gap-1.5" : "h-10 px-4 text-sm gap-2";
  return (
    <button
      className={`inline-flex items-center justify-center rounded-[var(--radius-sm)] font-medium transition-colors cursor-pointer disabled:cursor-not-allowed ${sizeClasses} ${buttonVariantClasses[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export function Card({
  children,
  className = "",
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={`bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-md)] shadow-[var(--shadow-card)] ${padded ? "p-6" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

type BadgeTone = "neutral" | "brand" | "success" | "warning" | "danger" | "info";

const badgeToneClasses: Record<BadgeTone, string> = {
  neutral: "bg-[var(--surface-sunken)] text-[var(--ink-muted)] border-[var(--line)]",
  brand: "bg-[var(--brand-tint)] text-[var(--brand-strong)] border-[var(--brand)]/20",
  success: "bg-[var(--success-tint)] text-[var(--success)] border-[var(--success)]/20",
  warning: "bg-[var(--amber-tint)] text-[var(--amber)] border-[var(--amber)]/25",
  danger: "bg-[var(--danger-tint)] text-[var(--danger)] border-[var(--danger)]/20",
  info: "bg-[var(--info-tint)] text-[var(--info)] border-[var(--info)]/20",
};

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: BadgeTone;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${badgeToneClasses[tone]}`}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Form controls
// ---------------------------------------------------------------------------

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-[var(--ink)] mb-1.5">{label}</span>
      {children}
      {hint ? <span className="block text-xs text-[var(--ink-faint)] mt-1.5">{hint}</span> : null}
    </label>
  );
}

const inputBaseClasses =
  "w-full rounded-[var(--radius-sm)] border border-[var(--line-strong)] bg-white px-3 py-2 text-sm text-[var(--ink)] placeholder:text-[var(--ink-faint)] focus:border-[var(--brand)] transition-colors";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputBaseClasses} ${props.className ?? ""}`} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`${inputBaseClasses} min-h-[140px] leading-relaxed font-mono text-[13px] ${props.className ?? ""}`}
    />
  );
}

export function Select(
  props: SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }
) {
  return (
    <select
      {...props}
      className={`${inputBaseClasses} appearance-none bg-white ${props.className ?? ""}`}
    >
      {props.children}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  width = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  width?: "sm" | "md" | "lg";
}) {
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  if (!open) return null;

  const widthClass = width === "sm" ? "max-w-md" : width === "lg" ? "max-w-2xl" : "max-w-lg";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto py-10 px-4">
      <div
        className="fixed inset-0 bg-[var(--ink)]/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        className={`relative w-full ${widthClass} bg-[var(--surface)] rounded-[var(--radius-lg)] shadow-[var(--shadow-modal)] border border-[var(--line)]`}
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-4 border-b border-[var(--line)]">
          <div>
            <h2 className="text-lg font-semibold text-[var(--ink)]">{title}</h2>
            {description ? (
              <p className="text-sm text-[var(--ink-muted)] mt-1">{description}</p>
            ) : null}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-[var(--ink-faint)] hover:text-[var(--ink)] rounded-full p-1 -mt-1 -mr-1 cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <p className="text-base font-medium text-[var(--ink)]">{title}</p>
      {description ? (
        <p className="text-sm text-[var(--ink-muted)] mt-1.5 max-w-sm">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Spinner
// ---------------------------------------------------------------------------

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      style={{ width: size, height: size, borderWidth: Math.max(2, size / 8) }}
      className="inline-block rounded-full border-[var(--line-strong)] border-t-[var(--brand)] animate-spin"
    />
  );
}

// ---------------------------------------------------------------------------
// Inline banner (success / error feedback after an action)
// ---------------------------------------------------------------------------

export function InlineNote({
  tone,
  children,
}: {
  tone: "success" | "danger";
  children: ReactNode;
}) {
  const toneClasses =
    tone === "success"
      ? "bg-[var(--success-tint)] text-[var(--success)] border-[var(--success)]/20"
      : "bg-[var(--danger-tint)] text-[var(--danger)] border-[var(--danger)]/20";
  return (
    <span className={`inline-flex items-center rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm ${toneClasses}`}>
      {children}
    </span>
  );
}