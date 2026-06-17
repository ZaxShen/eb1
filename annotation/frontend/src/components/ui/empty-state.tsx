import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** Centered icon + message for empty panes (no selection, no results). */
export function EmptyState({
  icon: Icon,
  title,
  hint,
  className,
}: {
  icon: LucideIcon;
  title: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex h-full flex-col items-center justify-center gap-2 px-6 text-center",
        className,
      )}
    >
      <span className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="size-5" />
      </span>
      <p className="text-sm font-medium text-foreground/80">{title}</p>
      {hint && (
        <p className="max-w-[24ch] text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}
