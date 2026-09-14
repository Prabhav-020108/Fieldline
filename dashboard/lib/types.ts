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