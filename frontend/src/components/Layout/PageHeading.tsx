import type { ReactNode } from "react";
import { TextReveal } from "@/components/ui/motion";

export function PageHeading({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-heading flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-balance text-2xl font-medium">
          <TextReveal>{title}</TextReveal>
        </h1>
        {description && (
          <p className="text-pretty mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      )}
    </header>
  );
}
