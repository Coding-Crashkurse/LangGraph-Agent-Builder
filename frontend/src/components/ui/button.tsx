import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/utils";

/**
 * Canonical variants (design brief): primary · ghost · outline · danger,
 * plus "secondary" (surface-2 filled) for mid-emphasis actions.
 */
type Variant = "primary" | "secondary" | "ghost" | "outline" | "danger";
type Size = "sm" | "md" | "icon";

const variants: Record<Variant, string> = {
  primary:
    "bg-accent text-canvas " +
    "hover:bg-[color-mix(in_srgb,var(--color-accent)_86%,white)] " +
    "active:bg-[color-mix(in_srgb,var(--color-accent)_76%,white)]",
  secondary:
    "border border-border bg-surface-2 text-text-1 " +
    "hover:border-border-strong hover:bg-surface-3 active:bg-surface-3",
  ghost: "text-text-2 hover:bg-surface-2 hover:text-text-1 active:bg-surface-3",
  outline:
    "border border-border text-text-2 " +
    "hover:border-border-strong hover:bg-surface-2 hover:text-text-1 active:bg-surface-3",
  danger: "bg-danger/15 text-danger hover:bg-danger/25 active:bg-danger/30",
};

const sizes: Record<Size, string> = {
  sm: "h-7 gap-1 px-2.5 text-xs",
  md: "h-8.5 px-3 text-[13px]",
  icon: "h-7 w-7 p-0",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium",
        "transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        "disabled:pointer-events-none disabled:opacity-45",
        "[&_svg]:shrink-0",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
