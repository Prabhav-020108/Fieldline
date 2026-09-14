"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Pencil, Plus, ShieldAlert, Trash2 } from "lucide-react";

import {
  createSafetyProcedure,
  deleteSafetyProcedure,
  listSafetyProcedures,
  updateSafetyProcedure,
  type SafetyProcedurePayload,
} from "@/lib/api";
import type { SafetyProcedure } from "@/lib/types";
import { Button, EmptyState, Field, Input, Modal, Spinner, Textarea } from "@/components/ui";

const emptyPayload: SafetyProcedurePayload = {
  equipment_type: "",
  section: "",
  text: "",
  source_manual: "Site Safety Manual",
};

export default function SafetyPage() {
  const params = useParams<{ companyId: string }>();
  return <SafetyPageInner key={params.companyId} companyId={params.companyId} />;
}

function SafetyPageInner({ companyId }: { companyId: string }) {
  const [procedures, setProcedures] = useState<SafetyProcedure[] | null>(null);
  const [modalTarget, setModalTarget] = useState<SafetyProcedure | "new" | null>(null);

  const refresh = () => listSafetyProcedures(companyId).then(setProcedures);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const handleDelete = async (proc: SafetyProcedure) => {
    if (!confirm(`Delete the ${proc.equipment_type} section ${proc.section} procedure?`)) return;
    await deleteSafetyProcedure(companyId, proc.id);
    await refresh();
  };

  return (
    <div>
      <div className="flex items-start justify-between mb-5 gap-4">
        <div>
          <h2 className="text-base font-semibold text-[var(--ink)]">Safety procedures</h2>
          <p className="text-sm text-[var(--ink-muted)] mt-0.5 max-w-lg">
            The agent reads this text back to a technician close to word for word,
            with a citation. Write it exactly as it should be spoken.
          </p>
        </div>
        <Button onClick={() => setModalTarget("new")}>
          <Plus size={16} />
          Add procedure
        </Button>
      </div>

      <div className="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-[var(--amber)]/25 bg-[var(--amber-tint)] px-4 py-3 mb-5 text-sm text-[var(--amber)]">
        <ShieldAlert size={16} className="mt-0.5 shrink-0" />
        <span>
          Safety-critical: keep wording exact and complete. The agent will not
          paraphrase or shorten this text on a call.
        </span>
      </div>

      {procedures === null ? (
        <div className="flex items-center gap-2 text-sm text-[var(--ink-muted)] py-10">
          <Spinner /> Loading safety procedures...
        </div>
      ) : procedures.length === 0 ? (
        <EmptyState
          title="No safety procedures yet"
          description="Add the first lockout / safety procedure so safety_procedure has something to retrieve."
          action={<Button onClick={() => setModalTarget("new")}>Add procedure</Button>}
        />
      ) : (
        <div className="space-y-3">
          {procedures.map((proc) => (
            <div
              key={proc.id}
              className="bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-md)] p-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-[var(--ink)] font-mono">
                    {proc.equipment_type} &middot; Section {proc.section}
                  </p>
                  <p className="text-xs text-[var(--ink-faint)] mt-0.5">{proc.source_manual}</p>
                </div>
                <div className="flex gap-1 shrink-0">
                  <Button variant="ghost" size="sm" onClick={() => setModalTarget(proc)} title="Edit">
                    <Pencil size={14} />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(proc)} title="Delete">
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>
              <p className="mt-3 text-sm text-[var(--ink-muted)] leading-relaxed whitespace-pre-wrap">
                {proc.text}
              </p>
            </div>
          ))}
        </div>
      )}

      {modalTarget ? (
        <SafetyModal
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

function SafetyModal({
  companyId,
  target,
  onClose,
  onSaved,
}: {
  companyId: string;
  target: SafetyProcedure | "new";
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = target === "new";
  const [form, setForm] = useState<SafetyProcedurePayload>(() =>
    isNew
      ? emptyPayload
      : {
          equipment_type: target.equipment_type,
          section: target.section,
          text: target.text,
          source_manual: target.source_manual,
        }
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (isNew) {
        await createSafetyProcedure(companyId, form);
      } else {
        await updateSafetyProcedure(companyId, target.id, form);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save procedure.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={isNew ? "Add safety procedure" : "Edit safety procedure"}
      width="lg"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Equipment type">
            <Input
              value={form.equipment_type}
              onChange={(e) => setForm({ ...form, equipment_type: e.target.value })}
              placeholder="panel-b"
              required
            />
          </Field>
          <Field label="Section">
            <Input
              value={form.section}
              onChange={(e) => setForm({ ...form, section: e.target.value })}
              placeholder="4.2"
              required
            />
          </Field>
        </div>
        <Field label="Source manual">
          <Input
            value={form.source_manual}
            onChange={(e) => setForm({ ...form, source_manual: e.target.value })}
            placeholder="Site Electrical Safety Manual"
          />
        </Field>
        <Field
          label="Procedure text"
          hint="Exact, verbatim steps -- this is read back close to word for word."
        >
          <Textarea
            value={form.text}
            onChange={(e) => setForm({ ...form, text: e.target.value })}
            placeholder="Section 4.2 - Panel B Lockout: (1) Notify affected personnel..."
            required
          />
        </Field>

        {error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? <Spinner size={14} /> : null}
            {isNew ? "Add procedure" : "Save changes"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}