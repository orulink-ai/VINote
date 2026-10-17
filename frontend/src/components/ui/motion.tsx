import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

/** CSS adaptation of Amicro FadeUp/TextReveal; see frontend/THIRD_PARTY_NOTICES.md. */
export function FadeUp({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("vinote-fade-up", className)} {...props} />;
}
export function TextReveal({ children }: { children: ReactNode }) {
  return (
    <span className="vinote-text-reveal">
      <span>{children}</span>
    </span>
  );
}
/** JkHuger's Uiverse wave-menu, adapted for processing, never audio amplitude. */
export function ProcessingWave({ label = "正在处理", decorative = false }: { label?: string; decorative?: boolean }) {
  return (
    <span role={decorative ? undefined : 'status'} aria-hidden={decorative || undefined} aria-label={decorative ? undefined : label} className="processing-wave">
      <i />
      <i />
      <i />
      <i />
      {!decorative && <span className="sr-only">{label}</span>}
    </span>
  );
}
