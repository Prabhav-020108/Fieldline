"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowUpCircle, Pencil, Plus, Trash2 } from "lucide-react";

import {
  createJob,
  deleteJob,
  listJobs,
  rerouteJob,
  updateJob,
  type JobPayload,
} from "@/lib/api";
import type { Job } from "@/lib/types";
import { Badge, Button, EmptyState, Field, Input, Modal, Select, Spinner } from "@/components/ui";

const emptyPayload: JobPayload = {
  equipment_id: "",
  site_id: "",
  fault_description: "",
  resolution: "",
  status: "open",
};

export default function JobsPage() {
  const params = useParams<{ companyId: string }>();
  // Keying by companyId forces a full remount when the technician switches
  // companies, so state below always starts fresh -- no manual "reset to
  // null" call needed before the next fetch.
  return <JobsPageInner key={params.companyId} companyId={params.companyId} />;
}

function JobsPageInner({ companyId }: { companyId: string }) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [modalTarget, setModalTarget] = useState<Job | "new" | null>(null);
  const [reroutingId, setReroutingId] = useState<string | null>(null);

  const refresh = () => listJobs(companyId).then(setJobs);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const handleReroute = async (job: Job) => {
    setReroutingId(job.id);
    try {
      await rerouteJob(companyId, job.id);
      await refresh();
    } finally {
      setReroutingId(null);
    }
  };

  const handleDelete = async (job: Job) => {
    if (!confirm(`Delete job for ${job.equipment_id}? This can't be undone.`)) return;
    await deleteJob(companyId, job.id);
    await refresh();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-base font-semibold text-[var(--ink)]">Jobs</h2>
          <p className="text-sm text-[var(--ink-muted)] mt-0.5">
            Fault history the fault_history and dispatch_status tools read from.
          </p>
        </div>
        <Button onClick={() => setModalTarget("new")}>
          <Plus size={16} />
          Add job
        </Button>
      </div>

      {jobs === null ? (
        <div className="flex items-center gap-2 text-sm text-[var(--ink-muted)] py-10">
          <Spinner /> Loading jobs...
        </div>
      ) : jobs.length === 0 ? (
        <EmptyState
          title="No jobs yet"
          description="Add the first job so fault_history and dispatch_status have something to find."
          action={<Button onClick={() => setModalTarget("new")}>Add job</Button>}
        />
      ) : (
        <div className="bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-md)] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-sunken)] text-[var(--ink-muted)] text-xs">
              <tr>
                <th className="text-left font-medium px-4 py-3">Equipment</th>
                <th className="text-left font-medium px-4 py-3">Fault</th>
                <th className="text-left font-medium px-4 py-3">Resolution</th>
                <th className="text-left font-medium px-4 py-3">Status</th>
                <th className="text-right font-medium px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} className="border-t border-[var(--line)] align-top">
                  <td className="px-4 py-3">
                    <div className="font-medium text-[var(--ink)] font-mono text-[13px]">
                      {job.equipment_id}
                    </div>
                    <div className="text-xs text-[var(--ink-faint)] mt-0.5">{job.site_id}</div>
                  </td>
                  <td className="px-4 py-3 max-w-xs text-[var(--ink)]">{job.fault_description}</td>
                  <td className="px-4 py-3 max-w-xs text-[var(--ink-muted)]">
                    {job.resolution || <span className="text-[var(--ink-faint)]">-- open --</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-1.5 items-start">
                      <Badge tone={job.status === "open" ? "info" : "success"}>{job.status}</Badge>
                      {job.priority ? <Badge tone="warning">priority</Badge> : null}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      {job.status === "open" && !job.priority ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleReroute(job)}
                          disabled={reroutingId === job.id}
                          title="Reroute to priority"
                        >
                          {reroutingId === job.id ? <Spinner size={14} /> : <ArrowUpCircle size={15} />}
                        </Button>
                      ) : null}
                      <Button variant="ghost" size="sm" onClick={() => setModalTarget(job)} title="Edit">
                        <Pencil size={14} />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(job)} title="Delete">
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalTarget ? (
        <JobModal
          key={modalTarget === "new" ? "new" : modalTarget.id}
          companyId={companyId}
          target={modalTarget}
          onClose={() => setModalTarget(null)}
          onSaved={() => {
            setModalTarget(null);
            refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function JobModal({
  companyId,
  target,
  onClose,
  onSaved,
}: {
  companyId: string;
  target: Job | "new";
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = target === "new";
  const [form, setForm] = useState<JobPayload>(() =>
    isNew
      ? emptyPayload
      : {
          equipment_id: target.equipment_id,
          site_id: target.site_id,
          fault_description: target.fault_description,
          resolution: target.resolution ?? "",
          status: target.status,
        }
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload: JobPayload = {
        ...form,
        resolution: form.resolution?.trim() ? form.resolution : null,
      };
      if (isNew) {
        await createJob(companyId, payload);
      } else {
        await updateJob(companyId, target.id, payload);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save job.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={isNew ? "Add job" : "Edit job"}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Equipment ID">
            <Input
              value={form.equipment_id}
              onChange={(e) => setForm({ ...form, equipment_id: e.target.value })}
              placeholder="unit-12"
              required
            />
          </Field>
          <Field label="Site ID">
            <Input
              value={form.site_id}
              onChange={(e) => setForm({ ...form, site_id: e.target.value })}
              placeholder="site-demo"
            />
          </Field>
        </div>
        <Field label="Fault description">
          <Input
            value={form.fault_description}
            onChange={(e) => setForm({ ...form, fault_description: e.target.value })}
            placeholder="Recurring low-refrigerant flag"
            required
          />
        </Field>
        <Field label="Resolution" hint="Leave blank while the job is still open.">
          <Input
            value={form.resolution ?? ""}
            onChange={(e) => setForm({ ...form, resolution: e.target.value })}
            placeholder="Breaker reset, monitored 48h"
          />
        </Field>
        <Field label="Status">
          <Select
            value={form.status}
            onChange={(e) => setForm({ ...form, status: e.target.value as JobPayload["status"] })}
          >
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </Select>
        </Field>

        {error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? <Spinner size={14} /> : null}
            {isNew ? "Add job" : "Save changes"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}