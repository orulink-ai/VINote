import type { ReactNode } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ProcessingWave } from "@/components/ui/motion";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";

export function LoadingState({
  label = "正在读取…",
  rows = 3,
}: {
  label?: string;
  rows?: number;
}) {
  return (
    <section
      role="status"
      aria-busy="true"
      aria-label={label}
      className="flex flex-col gap-4 py-4"
    >
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <ProcessingWave decorative />
        {label}
      </p>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </section>
  );
}
export function ErrorState({
  error,
  onRetry,
  busy,
  title = "操作未完成",
  retryLabel = "重试",
}: {
  error: string;
  onRetry?: () => void;
  busy?: boolean;
  title?: string;
  retryLabel?: string;
}) {
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
        <span className="min-w-0 break-words">{error}</span>
        {onRetry && (
          <Button variant="outline" disabled={busy} onClick={onRetry}>
            <RefreshCw data-icon="inline-start" />
            {busy ? "处理中…" : retryLabel}
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}
export function EmptyState({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      {children}
    </Empty>
  );
}
