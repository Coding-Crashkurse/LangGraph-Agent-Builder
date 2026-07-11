import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const base =
  "w-full rounded-lg border border-border-strong bg-surface-2 px-2.5 text-[13px] text-text-1 " +
  "outline-none transition-colors duration-150 placeholder:text-text-3 " +
  "focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent " +
  "disabled:cursor-not-allowed disabled:opacity-45";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(base, "h-8.5", className)} {...props} />
  ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, rows = 4, ...props }, ref) => (
  <textarea
    ref={ref}
    rows={rows}
    className={cn(base, "resize-y py-2 font-mono text-xs leading-relaxed", className)}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export function Label({
  className,
  children,
  hint,
}: {
  className?: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className={cn("mb-1 flex items-baseline justify-between", className)}>
      <span className="text-xs font-medium tracking-wide text-text-2">{children}</span>
      {hint ? <span className="text-[11px] text-text-3">{hint}</span> : null}
    </div>
  );
}
