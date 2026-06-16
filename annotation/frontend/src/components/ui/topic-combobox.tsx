import * as React from "react";

import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

interface TopicComboboxProps {
  value: string;
  suggestions: string[];
  onChange: (value: string) => void;
  onCommit?: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  label?: (suggestion: string) => string;
}

/**
 * Free-text topic input with an open-vocab suggestions popover. Suggestions are
 * filtered by the typed text (substring, case-insensitive); Enter or a click
 * commits, and any arbitrary name the user types is allowed. Built on the shared
 * Input so it inherits the app's field styling rather than a bespoke control.
 */
function TopicCombobox({
  value,
  suggestions,
  onChange,
  onCommit,
  placeholder,
  ariaLabel,
  label = (s) => s,
}: TopicComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const filtered = React.useMemo(() => {
    const q = value.trim().toLowerCase();
    const seen = new Set<string>();
    const out: string[] = [];
    for (const s of suggestions) {
      if (seen.has(s)) continue;
      seen.add(s);
      if (q === "" || s.toLowerCase().includes(q)) out.push(s);
    }
    return out;
  }, [suggestions, value]);

  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const commit = (next: string) => {
    onChange(next);
    onCommit?.(next);
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative">
      <Input
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-autocomplete="list"
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit(value);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        className="h-8 text-sm"
      />
      {open && filtered.length > 0 && (
        <ul
          role="listbox"
          className="absolute z-50 mt-1 max-h-48 w-full overflow-y-auto rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10"
        >
          {filtered.map((s) => (
            <li key={s}>
              <button
                type="button"
                role="option"
                aria-selected={s === value}
                onClick={() => commit(s)}
                className={cn(
                  "flex w-full items-center rounded-md px-2 py-1 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent",
                  s === value && "bg-accent",
                )}
              >
                {label(s)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export { TopicCombobox };
