import { create } from "zustand";
import { ApiError, apiFetch, apiJson } from "../lib/api";
import { useModelProfileStore } from "./modelProfileStore";
import { useNoteLibraryStore } from "./noteLibraryStore";
import { useTeamStore } from "./teamStore";
import { useSTTProfileStore } from './sttProfileStore';
import { useWorkspaceStore } from './workspaceStore';
import { setModelConnectionOwner } from '../lib/vilabConnectionIdentity';

export interface AuthUser {
  id: string;
  email: string;
}

interface SessionResponse {
  authenticated: boolean;
  user: AuthUser | null;
}

interface AuthState {
  status: "checking" | "authenticated" | "offline-known" | "expired" | "signed-out";
  sessionError: string;
  user: AuthUser | null;
  loading: boolean;
  initialized: boolean;
  initialize: () => Promise<void>;
  signUp: (
    email: string,
    password: string,
  ) => Promise<{ error: Error | null; user: AuthUser | null }>;
  signIn: (
    email: string,
    password: string,
  ) => Promise<{ error: Error | null; user: AuthUser | null }>;
  signOut: () => Promise<void>;
}

const clearUserState = () => {
  useModelProfileStore.getState().reset();
  useNoteLibraryStore.getState().reset();
  useTeamStore.getState().reset();
  useSTTProfileStore.getState().reset();
  useWorkspaceStore.getState().reset();
};

// A late session response must never restore the account that just signed out.
let sessionEpoch = 0;
let sessionRequest: Promise<void> | undefined;
export const useAuthStore = create<AuthState>((set, get) => ({
  status: "checking",
  sessionError: "",
  user: null,
  loading: false,
  initialized: false,
  initialize: async () => {
    if (sessionRequest) return sessionRequest;
    const epoch = sessionEpoch;
    set({ sessionError: "" });
    const request = (async () => { try {
      const session = await apiJson<SessionResponse>("/api/auth/session");
      if (epoch !== sessionEpoch) return;
      if (!session.authenticated || !session.user) {
        const expired = !!get().user;
        clearUserState();
        set({ user: null, initialized: true, status: expired ? "expired" : "signed-out" });
        return;
      }

      if (get().user && get().user?.id !== session.user.id) clearUserState();
      set({ user: session.user, initialized: true, status: "authenticated" });
    } catch (error) {
      if (epoch !== sessionEpoch) return;
      if (error instanceof ApiError && error.status === 401) {
        clearUserState();
        set({ user: null, initialized: true, status: "expired", sessionError: "登录已过期，请重新登录。" });
      } else {
        // Only an identity verified in this process may retain its local UI.
        // Do not trust a user id copied from localStorage on a cold start.
        set({ initialized: true, status: get().user ? "offline-known" : "checking",
          sessionError: "暂时无法验证登录。原有内容未删除，请检查连接后重试。" });
      }
    } })();
    sessionRequest = request;
    try { await request; } finally { if (sessionRequest === request) sessionRequest = undefined; }
  },
  signUp: async (email, password) => {
    const epoch = ++sessionEpoch;
    set({ loading: true });
    try {
      const user = await apiJson<AuthUser>("/api/auth/sign-up", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (epoch !== sessionEpoch) return { error: new Error("账号操作已变更，请重试"), user: null };
      clearUserState();
      set({ loading: false, user, initialized: true, status: "authenticated", sessionError: "" });
      return { error: null, user };
    } catch (error) {
      if (epoch === sessionEpoch) set({ loading: false });
      return {
        error: error instanceof Error ? error : new Error("Sign up failed"),
        user: null,
      };
    }
  },
  signIn: async (email, password) => {
    const epoch = ++sessionEpoch;
    set({ loading: true });
    try {
      const user = await apiJson<AuthUser>("/api/auth/sign-in", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (epoch !== sessionEpoch) return { error: new Error("账号操作已变更，请重试"), user: null };
      clearUserState();
      set({ loading: false, user, initialized: true, status: "authenticated", sessionError: "" });
      return { error: null, user };
    } catch (error) {
      if (epoch === sessionEpoch) set({ loading: false });
      return {
        error: error instanceof Error ? error : new Error("Sign in failed"),
        user: null,
      };
    }
  },
  signOut: async () => {
    const response = await apiFetch("/api/auth/sign-out", { method: "POST" });
    if (!response.ok) throw new Error("退出未完成，请重试；当前账号仍保持登录");
    ++sessionEpoch;
    clearUserState();
    set({ user: null, status: "signed-out", sessionError: "" });
  },
}));

// Register after creation, rather than reading this store during a dependent
// module's initialization (which is unsafe in a circular ESM import).
setModelConnectionOwner(useAuthStore.getState().user?.id);
useAuthStore.subscribe(state => setModelConnectionOwner(state.user?.id));
