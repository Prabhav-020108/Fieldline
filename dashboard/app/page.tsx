"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, Plus } from "lucide-react";

import { createCompany, listCompanies } from "@/lib/api";
import { INDUSTRIES, LANGUAGES, type Company } from "@/lib/types";
import { Badge, Button, EmptyState, Field, Input, Modal, Select, Spinner } from "@/components/ui";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

const industryLabel = (value: string) =>
  INDUSTRIES.find((i) => i.value === value)?.label ?? value;

export default function CompaniesPage() {
  const router = useRouter();
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = () => {
    listCompanies()
      .then((data) => {
        setCompanies(data);
        setLoadError(null);
      })
      .catch((err: Error) => setLoadError(err.message));
  };

  useEffect(refresh, []);

  return (
    <div className="max-w-5xl mx-auto px-8 py-10">
      <div className="flex items-start justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--ink)] tracking-tight">Companies</h1>
          <p className="text-sm text-[var(--ink-muted)] mt-1.5 max-w-xl">
            Every company here gets its own Moss index -- job history, safety
            procedures, and inventory stay isolated, even though the same
            FieldLine agent serves all of them.
          </p>
        </div>
        <Button onClick={() => setModalOpen(true)}>
          <Plus size={16} />
          Add company
        </Button>
      </div>

      {loadError ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--danger)]/25 bg-[var(--danger-tint)] px-5 py-4 text-sm text-[var(--danger)]">
          Couldn&apos;t reach the FieldLine backend at{" "}
          <code className="font-mono">
            {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
          </code>
          . Start it with <code className="font-mono">python -m uvicorn main:app --reload --port 8000</code>{" "}
          from the <code className="font-mono">backend/</code> folder, then reload this page.
        </div>
      ) : companies === null ? (
        <div className="flex items-center gap-2 text-sm text-[var(--ink-muted)] py-10">
          <Spinner /> Loading companies...
        </div>
      ) : companies.length === 0 ? (
        <EmptyState
          title="No companies yet"
          description="Add your first company to start entering jobs, safety procedures, and inventory for it."
          action={<Button onClick={() => setModalOpen(true)}>Add company</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {companies.map((company) => (
            <button
              key={company.id}
              onClick={() => router.push(`/companies/${company.id}`)}
              className="text-left bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-md)] p-5 hover:border-[var(--brand)]/40 hover:shadow-[var(--shadow-card)] transition-all cursor-pointer"
            >
              <div className="flex items-start justify-between gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--brand-tint)] text-[var(--brand-strong)]">
                  <Building2 size={16} />
                </span>
                <Badge tone="neutral">{industryLabel(company.industry)}</Badge>
              </div>
              <p className="mt-3.5 text-base font-semibold text-[var(--ink)]">{company.name}</p>
              <p className="mt-1 text-xs font-mono text-[var(--ink-faint)]">
                {company.moss_index_name}
              </p>
            </button>
          ))}
        </div>
      )}

      <AddCompanyModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(company) => {
          setModalOpen(false);
          refresh();
          router.push(`/companies/${company.id}`);
        }}
      />
    </div>
  );
}

function AddCompanyModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (company: Company) => void;
}) {
  const [name, setName] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [id, setId] = useState("");
  const [industry, setIndustry] = useState(INDUSTRIES[0].value);
  const [language, setLanguage] = useState(LANGUAGES[0].value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const autoId = useMemo(() => slugify(name), [name]);
  const effectiveId = idTouched ? id : autoId;

  const reset = () => {
    setName("");
    setId("");
    setIdTouched(false);
    setIndustry(INDUSTRIES[0].value);
    setLanguage(LANGUAGES[0].value);
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !effectiveId.trim()) {
      setError("Name and ID are both required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const company = await createCompany({
        id: effectiveId,
        name: name.trim(),
        industry,
        language_preference: language,
      });
      reset();
      onCreated(company);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create company.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Add a company"
      description="Each company gets its own Moss index, so its data never mixes with another company's."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Company name">
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Elevator AMC"
          />
        </Field>

        <Field
          label="Company ID"
          hint="Used in the Moss index name and the room name the agent listens for (fieldline-<id>). Lowercase letters, numbers, and hyphens."
        >
          <Input
            value={effectiveId}
            onChange={(e) => {
              setIdTouched(true);
              setId(slugify(e.target.value));
            }}
            placeholder="acme-elevator"
          />
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Industry">
            <Select value={industry} onChange={(e) => setIndustry(e.target.value as typeof industry)}>
              {INDUSTRIES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Language preference">
            <Select value={language} onChange={(e) => setLanguage(e.target.value as typeof language)}>
              {LANGUAGES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? <Spinner size={14} /> : null}
            Create company
          </Button>
        </div>
      </form>
    </Modal>
  );
}