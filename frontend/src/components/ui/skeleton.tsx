import { cn } from "@/lib/utils";

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("vinote-skeleton rounded-lg bg-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
