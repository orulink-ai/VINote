import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";

export function VersionCompare({
  left,
  right,
  leftLabel = "历史版本",
  rightLabel = "当前内容",
}: {
  left: string;
  right: string;
  leftLabel?: string;
  rightLabel?: string;
}) {
  // Linear-space paragraph comparison keeps long transcripts responsive.
  const rows = useMemo(() => {
    const a = left.split(/\n\s*\n/),
      b = right.split(/\n\s*\n/);
    return Array.from({ length: Math.max(a.length, b.length) }, (_, i) => ({
      a: a[i] || "",
      b: b[i] || "",
      changed: a[i] !== b[i],
    }));
  }, [left, right]);
  return (
    <section aria-label="版本逐段比较" className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-4 text-sm font-medium">
        <p>{leftLabel}</p>
        <p>{rightLabel}</p>
      </div>
      {rows.map((row, i) => (
        <div
          key={i}
          className="border-t py-3"
          style={{
            contentVisibility: "auto",
            containIntrinsicSize: "auto 100px",
          }}
        >
          <Badge variant={row.changed ? "outline" : "secondary"}>
            {row.changed ? "有差异" : "相同"} · 段落 {i + 1}
          </Badge>
          <div className="mt-2 grid grid-cols-1 gap-4 md:grid-cols-2">
            <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6">
              {row.a || "（空）"}
            </pre>
            <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6">
              {row.b || "（空）"}
            </pre>
          </div>
        </div>
      ))}
    </section>
  );
}
