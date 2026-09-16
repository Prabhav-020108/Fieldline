"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, Boxes, ShieldCheck } from "lucide-react";

import { getCompany, isLoggedIn, listInventory, listJobs, listSafetyProcedures, updateCompany } from "@/lib/api";
import { INDUSTRIES, LANGUAGES, type Company } from "@/lib/types";
import { Button, Card, Field, Select, Spinner } from "@/components/ui";

export default function CompanyOverviewPage() {
  const params = useParams<{ companyId: string }>();
  return <CompanyOverviewPageInner key={params.companyId} companyId={params.companyId} />;
}

function CompanyOverviewPageInner({ companyId }: { companyId: string }) {
  const [company, setCompany] = useState<Company | null>(null);
  const [openJobs, setOpenJobs] = useState<number | null>(null);
  const [priorityJobs, setPriorityJobs] = useState<number | null>(null);
  const [inventoryCount, setInventoryCount] = useState<number | null>(null);
  const [safetyCount, setSafetyCount] = useState<number | null>(null);

  useEffect(() => {
    getCompany(companyId).then(setCompany);
    listJobs(companyId).then((jobs) => {
      setOpenJobs(jobs.filter((j) => j.status === "open").length);
      setPriorityJobs(jobs.filter((j) => j.priority).length);
    });
    listInventory(companyId).then((items) => setInventoryCount(items.length));
    listSafetyProcedures(companyId).then((procs) => setSafetyCount(procs.length));
  }, [companyId]);

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          icon={<AlertTriangle size={16} />}
          label="Open jobs"
          value={openJobs}
          sublabel={priorityJobs ? `${priorityJobs} flagged priority` : undefined}
        />
        <StatCard icon={<Boxes size={16} />} label="Inventory items" value={inventoryCount} />
        <StatCard icon={<ShieldCheck size={16} />} label="Safety procedures" value={safetyCount} />
      </div>

      {company ? (
        <ProfileForm key={company.id} company={company} onSaved={setCompany} />
      ) : (
        <Spinner />
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  sublabel,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | null;
  sublabel?: string;
}) {
  return (
    <Card>
      <div className="flex items-center gap-2 text-[var(--ink-muted)]">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      <p className="mt-3 text-3xl font-semibold text-[var(--ink)] tracking-tight">
        {value === null ? <span className="text-[var(--ink-faint)]">--</span> : value}
      </p>
      {sublabel ? <p className="mt-1 text-xs text-[var(--amber)]">{sublabel}</p> : null}
    </Card>
  );
}

function ProfileForm({
  company,
  onSaved,
}: {
  company: Company;
  onSaved: (company: Company) => void;
}) {
  const [name, setName] = useState(company.name);
  const [industry, setIndustry] = useState(company.industry);
  const [language, setLanguage] = useState(company.language_preference);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loggedIn = isLoggedIn();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const updated = await updateCompany(company.id, {
        name,
        industry,
        language_preference: language,
      });
      onSaved(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not save changes -- please try again."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <h2 className="text-base font-semibold text-[var(--ink)] mb-4">Company profile</h2>
      {!loggedIn ? (
        <p className="text-sm text-[var(--ink-muted)] mb-4 bg-[var(--surface-sunken)] border border-[var(--line)] rounded-[var(--radius-sm)] px-3 py-2">
          Viewing only -- sign in from the sidebar to edit this company&apos;s profile.
        </p>
      ) : null}
      <form onSubmit={handleSubmit} className="space-y-4 max-w-md">
        <Field label="Company name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={!loggedIn}
            className="w-full rounded-[var(--radius-sm)] border border-[var(--line-strong)] bg-white px-3 py-2 text-sm text-[var(--ink)] focus:border-[var(--brand)] disabled:bg-[var(--surface-sunken)] disabled:text-[var(--ink-faint)]"
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Industry">
            <Select
              value={industry}
              onChange={(e) => setIndustry(e.target.value as typeof industry)}
              disabled={!loggedIn}
            >
              {INDUSTRIES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Language preference">
            <Select
              value={language}
              onChange={(e) => setLanguage(e.target.value as typeof language)}
              disabled={!loggedIn}
            >
              {LANGUAGES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null}

        <div className="flex items-center gap-3 pt-1">
          <Button type="submit" disabled={saving || !loggedIn}>
            {saving ? <Spinner size={14} /> : null}
            Save changes
          </Button>
          {saved ? <span className="text-sm text-[var(--success)]">Saved.</span> : null}
        </div>
      </form>
    </Card>
  );
}