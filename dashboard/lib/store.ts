import { create } from "zustand";
import { getCurrentUser, isLoggedIn, listCompanies, logout as apiLogout } from "./api";
import type { Company } from "./types";

export interface CurrentUser {
  username: string;
  role: string;
  company_id: string;
}

interface AppState {
  currentUser: CurrentUser | null;
  companies: Company[] | null;
  companiesLoading: boolean;
  companiesError: string | null;

  fetchCurrentUser: () => Promise<void>;
  fetchCompanies: () => Promise<void>;
  logout: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentUser: null,
  companies: null,
  companiesLoading: false,
  companiesError: null,

  fetchCurrentUser: async () => {
    if (!isLoggedIn()) {
      set({ currentUser: null });
      return;
    }
    try {
      const user = await getCurrentUser();
      set({ currentUser: user });
    } catch {
      apiLogout();
      set({ currentUser: null });
    }
  },

  fetchCompanies: async () => {
    set({ companiesLoading: true });
    try {
      const data = await listCompanies();
      set({ companies: data, companiesLoading: false, companiesError: null });
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : "Failed to load companies";
      set({ companies: [], companiesLoading: false, companiesError: errorMsg });
    }
  },

  logout: () => {
    apiLogout();
    set({ currentUser: null });
  },
}));
