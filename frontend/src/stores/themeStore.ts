import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark" | "system";

interface ThemeState {
  theme: Theme;
  resolvedTheme: "light" | "dark";
  setTheme: (theme: Theme) => void;
  reduceMotion: boolean;
  fontScale: "normal" | "large";
  setReduceMotion: (value: boolean) => void;
  setFontScale: (value: "normal" | "large") => void;
}

const getSystemTheme = (): "light" | "dark" => {
  if (typeof window !== "undefined") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return "light";
};

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "system",
      resolvedTheme: getSystemTheme(),
      reduceMotion: false,
      fontScale: "normal",
      setReduceMotion: (value) => set({ reduceMotion: value }),
      setFontScale: (value) => set({ fontScale: value }),
      setTheme: (theme) => {
        const resolved = theme === "system" ? getSystemTheme() : theme;
        set({ theme, resolvedTheme: resolved });
        document.documentElement.classList.toggle("dark", resolved === "dark");
      },
    }),
    {
      name: "vinote-theme",
    },
  ),
);
