// Deployment domains for taxonomy v2 (issue #23). A conversation's domain is a
// KNOWN attribute (the source site), so the UI maps the four site codes the
// backend stores to their display names for the queue's domain filter and the
// domain-scoped taxonomy pickers.

export interface DomainOption {
  code: string;
  label: string;
}

export const DOMAINS: DomainOption[] = [
  { code: "dmv", label: "DMV" },
  { code: "ssa", label: "Social Security" },
  { code: "va", label: "Veterans Affairs" },
  { code: "studentaid", label: "Student Aid" },
];

/** Display name for a domain code (falls back to the code, or "" for null). */
export function domainLabel(code: string | null | undefined): string {
  return DOMAINS.find((d) => d.code === code)?.label ?? code ?? "";
}
