import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

type BadgeVariant = "secondary" | "outline" | "plain";

const VARIANTS: Record<BadgeVariant, string> = {
  secondary: "bg-secondary text-secondary-foreground border-transparent",
  outline: "border-border text-foreground",
  plain: "border-transparent",
};

export function Badge({
  children,
  variant = "secondary",
  className,
  title,
  onClick,
}: {
  children: ReactNode;
  variant?: BadgeVariant;
  className?: string;
  title?: string;
  onClick?: () => void;
}) {
  return (
    <span
      title={title}
      onClick={onClick}
      className={cn(
        "inline-flex items-center rounded-md border px-1.5 py-0 text-xs h-5 font-medium whitespace-nowrap",
        onClick && "cursor-pointer select-none transition-colors",
        VARIANTS[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
