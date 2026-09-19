import type { AuditLogEntry, Company, InventoryItem, Job, SafetyProcedure } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "fieldline_token";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string> | undefined) },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // response body wasn't JSON -- keep the default statusText
    }
    throw new Error(detail || `Request to ${path} failed (${res.status})`);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Auth (Phase 7)
// ---------------------------------------------------------------------------

export async function login(
  username: string,
  password: string
): Promise<{ access_token: string; token_type: string; role: string; company_id: string }> {
  const body = new URLSearchParams();
  body.set("username", username);
  body.set("password", password);

  const res = await fetch(`${API_BASE}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const errBody = await res.json();
      if (errBody && typeof errBody.detail === "string") detail = errBody.detail;
    } catch {
      // ignore
    }
    throw new Error(detail || "Login failed.");
  }

  return await res.json();
}

export function logout(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function isLoggedIn(): boolean {
  return getToken() !== null;
}

export const getCurrentUser = () =>
  request<{ username: string; role: string; company_id: string }>("/auth/me");

// ---------------------------------------------------------------------------
// Companies
// ---------------------------------------------------------------------------

export const listCompanies = () => request<Company[]>("/companies");

export const getCompany = (companyId: string) =>
  request<Company>(`/companies/${companyId}`);

export const createCompany = (data: {
  id: string;
  name: string;
  industry: string;
  language_preference: string;
}) =>
  request<Company>("/companies", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateCompany = (
  companyId: string,
  data: Partial<Pick<Company, "name" | "industry" | "language_preference">>
) =>
  request<Company>(`/companies/${companyId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const syncCompanyNow = (companyId: string) =>
  request<{ synced_documents: number }>(`/companies/${companyId}/sync`, {
    method: "POST",
  });

export const getCallRoleToken = (companyId: string) =>
  request<{ token: string; role: string }>(`/companies/${companyId}/call-role-token`, {
    method: "POST",
  });

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export type JobPayload = {
  equipment_id: string;
  site_id: string;
  fault_description: string;
  resolution?: string | null;
  status: "open" | "closed";
};

export const listJobs = (companyId: string) =>
  request<Job[]>(`/companies/${companyId}/jobs`);

export const createJob = (companyId: string, data: JobPayload) =>
  request<Job>(`/companies/${companyId}/jobs`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateJob = (companyId: string, jobId: string, data: JobPayload) =>
  request<Job>(`/companies/${companyId}/jobs/${jobId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const deleteJob = (companyId: string, jobId: string) =>
  request<void>(`/companies/${companyId}/jobs/${jobId}`, { method: "DELETE" });

export const rerouteJob = (companyId: string, jobId: string) =>
  request<Job>(`/companies/${companyId}/jobs/${jobId}/reroute`, {
    method: "POST",
  });

// ---------------------------------------------------------------------------
// Inventory
// ---------------------------------------------------------------------------

export type InventoryPayload = {
  part_number: string;
  name: string;
  location: string;
  quantity: number;
};

export const listInventory = (companyId: string) =>
  request<InventoryItem[]>(`/companies/${companyId}/inventory`);

export const createInventoryItem = (companyId: string, data: InventoryPayload) =>
  request<InventoryItem>(`/companies/${companyId}/inventory`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateInventoryItem = (
  companyId: string,
  itemId: string,
  data: InventoryPayload
) =>
  request<InventoryItem>(`/companies/${companyId}/inventory/${itemId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const deleteInventoryItem = (companyId: string, itemId: string) =>
  request<void>(`/companies/${companyId}/inventory/${itemId}`, {
    method: "DELETE",
  });

// ---------------------------------------------------------------------------
// Safety procedures
// ---------------------------------------------------------------------------

export type SafetyProcedurePayload = {
  equipment_type: string;
  section: string;
  text: string;
  source_manual: string;
};

export const listSafetyProcedures = (companyId: string) =>
  request<SafetyProcedure[]>(`/companies/${companyId}/safety-procedures`);

export const createSafetyProcedure = (
  companyId: string,
  data: SafetyProcedurePayload
) =>
  request<SafetyProcedure>(`/companies/${companyId}/safety-procedures`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateSafetyProcedure = (
  companyId: string,
  procedureId: string,
  data: SafetyProcedurePayload
) =>
  request<SafetyProcedure>(
    `/companies/${companyId}/safety-procedures/${procedureId}`,
    { method: "PUT", body: JSON.stringify(data) }
  );

export const deleteSafetyProcedure = (companyId: string, procedureId: string) =>
  request<void>(`/companies/${companyId}/safety-procedures/${procedureId}`, {
    method: "DELETE",
  });

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

export const listAuditLog = (companyId: string, limit = 200) =>
  request<AuditLogEntry[]>(
    `/companies/${companyId}/audit-log?limit=${limit}`
  );