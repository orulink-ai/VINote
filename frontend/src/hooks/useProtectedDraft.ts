import { useEffect, useState } from "react";
import { useAuthStore } from "@/stores/authStore";

export type TextDraft = {
  title: string;
  content: string;
  baseRevision?: number | string;
  updatedAt: string;
};
export function readTextDraft(owner: string, key: string): TextDraft | null {
  const raw = localStorage.getItem(`vinote:draft:${owner}:${key}`);
  if (!raw) return null;
  const draft = JSON.parse(raw);
  return typeof draft?.title === "string" && typeof draft?.content === "string"
    ? draft
    : null;
}
export function removeTextDraft(owner: string, key: string) {
  localStorage.removeItem(`vinote:draft:${owner}:${key}`);
}
export function useProtectedDraft(
  key: string,
  title: string,
  content: string,
  dirty: boolean,
  baseRevision?: number | string,
) {
  const owner = useAuthStore((s) => s.user?.id);
  const [status, setStatus] = useState("");
  useEffect(() => {
    if (!owner || !key) return;
    const persist = () => {
      if (!dirty) return;
      try {
        localStorage.setItem(
          `vinote:draft:${owner}:${key}`,
          JSON.stringify({
            title,
            content,
            baseRevision,
            updatedAt: new Date().toISOString(),
          }),
        );
        setStatus("草稿已保存到本机");
      } catch {
        setStatus("草稿保护失败：本机存储不可用，请保存或导出后再离开");
      }
    };
    persist();
    const requestLeave = (to: string) => {
      let protectedDraft = false;
      try { const draft = readTextDraft(owner, key); protectedDraft = draft?.title === title && draft?.content === content; } catch { /* Keep the editor open. */ }
      window.dispatchEvent(new CustomEvent('vinote:draft-navigation', { detail: { to, protectedDraft } }));
    };
    const checkNavigation = (event: Event) => {
      if (!dirty) return;
      event.preventDefault();
      requestLeave((event as CustomEvent<{ to: string }>).detail.to);
    };
    const navigate = (event: MouseEvent) => {
      if (!dirty || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest('a[href]') as HTMLAnchorElement | null : null;
      if (!link || link.target === '_blank' || link.hasAttribute('download')) return;
      const destination = new URL(link.href, window.location.href);
      if (destination.origin !== window.location.origin || destination.pathname === window.location.pathname && destination.search === window.location.search) return;
      event.preventDefault(); event.stopPropagation();
      requestLeave(destination.pathname + destination.search);
    };
    const guard = (event: BeforeUnloadEvent) => {
      if (dirty) {
        persist();
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    document.addEventListener('click', navigate, true);
    window.addEventListener('vinote:check-navigation', checkNavigation);
    return () => {
      window.removeEventListener("beforeunload", guard);
      document.removeEventListener('click', navigate, true);
      window.removeEventListener('vinote:check-navigation', checkNavigation);
    };
  }, [owner, key, title, content, dirty, baseRevision]);
  return dirty ? status || "正在保护草稿…" : "";
}
