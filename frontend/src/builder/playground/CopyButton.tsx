/** Icon copy-to-clipboard button with transient "copied" feedback (§11.6). */

import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { copyToClipboard } from "@/lib/utils";
import { cn } from "@/lib/utils";

export function CopyButton({
  text,
  label = "Copy to clipboard",
  className,
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await copyToClipboard(text);
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (non-secure context) — nothing to signal */
    }
  };

  return (
    <button
      type="button"
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      onClick={copy}
      className={cn(
        "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
        "text-text-3 transition-colors hover:bg-surface-3 hover:text-text-1",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        copied && "text-success hover:text-success",
        className,
      )}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5" strokeWidth={1.75} />
      ) : (
        <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
      )}
    </button>
  );
}
