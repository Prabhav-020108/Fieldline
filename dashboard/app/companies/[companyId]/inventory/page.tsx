"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";

import {
  createInventoryItem,
  deleteInventoryItem,
  listInventory,
  updateInventoryItem,
  type InventoryPayload,
} from "@/lib/api";
import type { InventoryItem } from "@/lib/types";
import { Button, EmptyState, Field, Input, Modal, Spinner } from "@/components/ui";

const emptyPayload: InventoryPayload = {
  part_number: "",
  name: "",
  location: "",
  quantity: 0,
};

export default function InventoryPage() {
  const params = useParams<{ companyId: string }>();
  return <InventoryPageInner key={params.companyId} companyId={params.companyId} />;
}

function InventoryPageInner({ companyId }: { companyId: string }) {
  const [items, setItems] = useState<InventoryItem[] | null>(null);
  const [modalTarget, setModalTarget] = useState<InventoryItem | "new" | null>(null);

  const refresh = () => listInventory(companyId).then(setItems);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const handleDelete = async (item: InventoryItem) => {
    if (!confirm(`Delete ${item.name}?`)) return;
    await deleteInventoryItem(companyId, item.id);
    await refresh();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-base font-semibold text-[var(--ink)]">Inventory</h2>
          <p className="text-sm text-[var(--ink-muted)] mt-0.5">
            Parts the inventory_lookup tool searches by part number or name.
          </p>
        </div>
        <Button onClick={() => setModalTarget("new")}>
          <Plus size={16} />
          Add item
        </Button>
      </div>

      {items === null ? (
        <div className="flex items-center gap-2 text-sm text-[var(--ink-muted)] py-10">
          <Spinner /> Loading inventory...
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="No inventory yet"
          description="Add the first part so inventory_lookup has something to find."
          action={<Button onClick={() => setModalTarget("new")}>Add item</Button>}
        />
      ) : (
        <div className="bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-md)] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-sunken)] text-[var(--ink-muted)] text-xs">
              <tr>
                <th className="text-left font-medium px-4 py-3">Part number</th>
                <th className="text-left font-medium px-4 py-3">Name</th>
                <th className="text-left font-medium px-4 py-3">Location</th>
                <th className="text-left font-medium px-4 py-3">Qty</th>
                <th className="text-right font-medium px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-t border-[var(--line)]">
                  <td className="px-4 py-3 font-mono text-[13px] text-[var(--ink)]">
                    {item.part_number}
                  </td>
                  <td className="px-4 py-3 text-[var(--ink)]">{item.name}</td>
                  <td className="px-4 py-3 text-[var(--ink-muted)]">{item.location}</td>
                  <td className="px-4 py-3 text-[var(--ink)]">{item.quantity}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => setModalTarget(item)} title="Edit">
                        <Pencil size={14} />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(item)} title="Delete">
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
        <InventoryModal
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

function InventoryModal({
  companyId,
  target,
  onClose,
  onSaved,
}: {
  companyId: string;
  target: InventoryItem | "new";
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = target === "new";
  const [form, setForm] = useState<InventoryPayload>(() =>
    isNew
      ? emptyPayload
      : {
          part_number: target.part_number,
          name: target.name,
          location: target.location,
          quantity: target.quantity,
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
        await createInventoryItem(companyId, form);
      } else {
        await updateInventoryItem(companyId, target.id, form);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save item.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={isNew ? "Add inventory item" : "Edit inventory item"}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Part number">
            <Input
              value={form.part_number}
              onChange={(e) => setForm({ ...form, part_number: e.target.value })}
              placeholder="LC1D18"
              required
            />
          </Field>
          <Field label="Quantity">
            <Input
              type="number"
              min={0}
              value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })}
              required
            />
          </Field>
        </div>
        <Field label="Name">
          <Input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Schneider contactor"
            required
          />
        </Field>
        <Field label="Location">
          <Input
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            placeholder="bin 14C, site store room"
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
            {isNew ? "Add item" : "Save changes"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}