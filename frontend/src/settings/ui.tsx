/** Shared chrome for the Settings sections: headers, empty/loading states,
 * copy-with-feedback and danger-styled delete confirmation (design brief:
 * tokens only, lucide icons, visible focus rings). */

import { Check, Copy, Trash2, type LucideIcon } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { cn, copyToClipboard } from "@/lib/utils";

export function SectionHeader({
  title,
  description,
}: {
  title: string;
  description: ReactNode;
}) {
  return (
    <div className="mb-4">
      <h2 className="text-sm font-semibold text-text-1">{title}</h2>
      <p className="mt-1 max-w-xl text-xs leading-relaxed text-text-3">{description}</p>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  headline,
  hint,
}: {
  icon: LucideIcon;
  headline: string;
  hint: string;
}) {
  return (
    <div className="flex flex-col items-center gap-1.5 rounded-lg border border-dashed border-border px-6 py-10 text-center">
      <Icon size={20} strokeWidth={1.75} className="text-text-3" aria-hidden />
      <p className="text-[13px] text-text-2">{headline}</p>
      <p className="text-xs text-text-3">{hint}</p>
    </div>
  );
}

export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-9 w-full animate-pulse rounded-md bg-surface-2" />
      ))}
    </div>
  );
}

/** 11px uppercase column header cell (design brief: table chrome). */
export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <th
      className={cn(
        "px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-text-3",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className="rounded p-1 text-text-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
      onClick={async () => {
        try {
          await copyToClipboard(text);
          setCopied(true);
        } catch {
          toast.error("copy failed — clipboard unavailable");
        }
      }}
    >
      {copied ? (
        <Check size={13} strokeWidth={1.75} className="text-success" aria-hidden />
      ) : (
        <Copy size={13} strokeWidth={1.75} aria-hidden />
      )}
    </button>
  );
}

/** Danger-styled confirmation for destructive actions. */
export function ConfirmDelete({
  target,
  title,
  description,
  verb = "Delete",
  confirmLabel = "Delete",
  onClose,
  onConfirm,
}: {
  target: string | null; // subject name; null = closed
  title: string;
  description: ReactNode;
  verb?: string;
  confirmLabel?: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={target !== null} onClose={onClose} title={title}>
      <div className="space-y-4">
        <p className="text-sm text-text-2">
          {verb} <span className="font-mono font-semibold text-text-1">{target}</span>?
        </p>
        <p className="text-xs text-text-3">{description}</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              onConfirm();
              onClose();
            }}
          >
            <Trash2 size={14} strokeWidth={1.75} aria-hidden />
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** Icon-only per-row delete trigger. */
export function RowDeleteButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className="rounded p-1 text-text-3 hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
      onClick={onClick}
    >
      <Trash2 size={13} strokeWidth={1.75} aria-hidden />
    </button>
  );
}
