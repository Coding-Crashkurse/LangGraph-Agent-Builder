import { type ReactNode, useEffect } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Dialog({
  open,
  onClose,
  title,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-[3px]" onClick={onClose} />
      <div
        className={cn(
          "gf-zoom-in relative z-10 flex max-h-[85vh] w-[640px] max-w-[92vw] flex-col overflow-hidden",
          "rounded-xl border border-surface-700 bg-gradient-to-b from-surface-850 to-surface-900",
          "shadow-2xl shadow-black/70 ring-1 ring-accent-500/10",
          className,
        )}
        role="dialog"
        aria-modal
      >
        <div className="flex items-center justify-between border-b border-surface-800 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}
