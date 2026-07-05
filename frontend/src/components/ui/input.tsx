import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const base =
  "w-full rounded-md border border-surface-700 bg-surface-900 px-2.5 text-sm text-zinc-100 " +
  "placeholder:text-zinc-600 focus:border-accent-500 focus:outline-none disabled:opacity-50";

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
    className={cn(base, "py-2 font-mono text-xs leading-relaxed", className)}
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
      <span className="text-xs font-medium tracking-wide text-zinc-400">{children}</span>
      {hint ? <span className="text-[10px] text-zinc-600">{hint}</span> : null}
    </div>
  );
}
