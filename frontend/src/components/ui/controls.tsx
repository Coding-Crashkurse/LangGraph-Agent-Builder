import type { ReactNode, SelectHTMLAttributes } from "react";
import { Check, ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Native select styled to the input surface, with a lucide chevron.
 * `className` sizes the wrapper (width/height/margin/text-size); the inner
 * select fills it and inherits the font.
 */
export function Select({
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }) {
  return (
    <div className={cn("relative h-8.5 w-full text-[13px]", className)}>
      <select
        className={cn(
          "peer h-full w-full cursor-pointer appearance-none rounded-lg border border-border-strong",
          "bg-surface-2 pl-2.5 pr-7 text-text-1 outline-none transition-colors duration-150",
          "focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
          "disabled:cursor-not-allowed disabled:opacity-45",
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-text-3 peer-disabled:opacity-45"
        strokeWidth={1.75}
        aria-hidden="true"
      />
    </div>
  );
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  label?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        "disabled:cursor-not-allowed disabled:opacity-45",
        checked ? "bg-accent" : "bg-surface-3",
      )}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 transform rounded-full bg-text-1 transition-transform duration-150",
          checked ? "translate-x-[18px]" : "translate-x-[3px]",
        )}
      />
    </button>
  );
}

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  disabled,
  className,
}: {
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  label?: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        "disabled:cursor-not-allowed disabled:opacity-45",
        checked
          ? "border-accent bg-accent text-canvas"
          : "border-border-strong bg-surface-2 hover:border-accent/60",
        className,
      )}
    >
      {checked ? <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden="true" /> : null}
    </button>
  );
}

/**
 * Range slider: flat border-strong track with an accent fill up to the
 * current value, 12px thumb, tabular-mono readout right-aligned.
 */
export function Slider({
  value,
  min = 0,
  max = 100,
  step = 1,
  onChange,
  disabled,
  className,
  "aria-label": ariaLabel,
}: {
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
}) {
  const clamped = Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : min;
  const pct = max > min ? ((clamped - min) / (max - min)) * 100 : 0;
  return (
    <div className={cn("flex w-full items-center gap-2", className)}>
      <input
        type="range"
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        value={clamped}
        disabled={disabled}
        onChange={(event) => onChange(parseFloat(event.target.value))}
        style={{
          background: `linear-gradient(to right, var(--color-accent) ${pct}%, var(--color-border-strong) ${pct}%)`,
        }}
        className={cn(
          "h-1 w-full cursor-pointer appearance-none rounded-full outline-none",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          "disabled:cursor-not-allowed disabled:opacity-45",
          "[&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none",
          "[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-text-1",
          "[&::-moz-range-thumb]:h-3 [&::-moz-range-thumb]:w-3 [&::-moz-range-thumb]:rounded-full",
          "[&::-moz-range-thumb]:border-none [&::-moz-range-thumb]:bg-text-1",
        )}
      />
      <span className="min-w-10 text-right font-mono text-xs tabular-nums text-text-2">
        {clamped}
      </span>
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T;
  onChange: (value: T) => void;
  items: { value: T; label: ReactNode }[];
}) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-1 p-0.5">
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onChange(item.value)}
          className={cn(
            "rounded-md px-3 py-1 text-xs font-medium transition-colors duration-150",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
            value === item.value ? "bg-surface-3 text-text-1" : "text-text-3 hover:text-text-1",
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
