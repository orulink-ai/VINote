import { useState, type Dispatch, type SetStateAction } from "react";
import { useAuthStore } from "@/stores/authStore";

export function useViewState<T>(
  name: string,
  initial: T,
): [T, Dispatch<SetStateAction<T>>] {
  const owner = useAuthStore((s) => s.user?.id);
  const key = `vinote:view:${owner}:${name}`;
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  return [
    value,
    (next) =>
      setValue((current) => {
        const result =
          typeof next === "function"
            ? (next as (value: T) => T)(current)
            : next;
        try {
          sessionStorage.setItem(key, JSON.stringify(result));
        } catch {
          /* View preference is optional. */
        }
        return result;
      }),
  ];
}
