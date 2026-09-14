// Mirrors the Pydantic schemas in backend/main.py -- keep these in sync if
// you add a field on one side.

export type Industry =
  | "electrical"
  | "hvac"
  | "elevator_amc"
  | "telecom_tower"
  | "other";

export type LanguagePreference = "english" | "hindi" | "hinglish";

export interface Company {
  id: string;
  name: string;
  industry: Industry;
  language_preference: LanguagePreference;
  moss_index_name: string;
}

export interface Job {
  id: string;
  company_id: string;
  equipment_id: string;
  site_id: string;
  fault_description: string;
  resolution: string | null;
  status: "open" | "closed";
  priority: boolean;
}

export interface InventoryItem {
  id: string;
  company_id: string;
  part_number: string;
  name: string;
  location: string;
  quantity: number;
}

export interface SafetyProcedure {
  id: string;
  company_id: string;
  equipment_type: string;
  section: string;
  text: string;
  source_manual: string;
}

// Phase 6: one row per tool call the voice agent makes. Written by
// agent/src/audit_log.py, read by the "Audit log" dashboard tab.
export type ToolName =
  | "fault_history"
  | "safety_procedure"
  | "inventory_lookup"
  | "dispatch_status"
  | "log_job_note";

export interface AuditLogEntry {
  id: string;
  company_id: string;
  tool_name: ToolName;
  query_text: string;
  response_text: string;
  source_citation: string | null;
  confidence_score: number | null;
  below_confidence_floor: boolean;
  created_at: string; // ISO 8601 UTC
}

export const INDUSTRIES: { value: Industry; label: string }[] = [
  { value: "electrical", label: "Electrical maintenance" },
  { value: "hvac", label: "HVAC" },
  { value: "elevator_amc", label: "Elevator AMC" },
  { value: "telecom_tower", label: "Telecom tower" },
  { value: "other", label: "Other" },
];

export const LANGUAGES: { value: LanguagePreference; label: string }[] = [
  { value: "hinglish", label: "Hinglish" },
  { value: "hindi", label: "Hindi" },
  { value: "english", label: "English" },
];

export const TOOL_LABELS: Record<ToolName, string> = {
  fault_history: "Fault history",
  safety_procedure: "Safety procedure",
  inventory_lookup: "Inventory lookup",
  dispatch_status: "Dispatch status",
  log_job_note: "Job note logged",
};