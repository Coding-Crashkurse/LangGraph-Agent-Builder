import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/utils";

type Variant = "default" | "secondary" | "ghost" | "destructive" | "outline";
type Size = "sm" | "md" | "icon";

const variants: Record<Variant, string> = {
  default:
    "bg-gradient-to-b from-accent-500 to-accent-600 text-white " +
    "shadow-md shadow-accent-600/25 hover:shadow-lg hover:shadow-accent-500/35 " +
    "hover:brightness-110 active:scale-[0.98] disabled:from-surface-700 disabled:to-surface-700 disabled:shadow-none",
  secondary:
    "bg-surface-800 text-zinc-200 border border-surface-700 " +
    "hover:bg-surface-700 hover:border-surface-600 hover:text-white active:scale-[0.98]",
  ghost: "text-zinc-400 hover:text-zinc-100 hover:bg-surface-800",
  outline: "border border-surface-700 text-zinc-300 hover:bg-surface-800 hover:border-surface-600",
  destructive:
    "bg-red-900/60 text-red-200 border border-red-800/60 hover:bg-red-900 hover:text-red-100 active:scale-[0.98]",
};

const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs",
  md: "h-8.5 px-3.5 text-sm",
  icon: "h-7 w-7",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium",
        "transition-all duration-150 focus-visible:outline-2 focus-visible:outline-accent-500",
        "disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
