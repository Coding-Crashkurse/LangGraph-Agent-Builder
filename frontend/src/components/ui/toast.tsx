import { create } from "zustand";
import { AlertTriangle, CheckCircle2, Info, X, XCircle, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type Tone = "info" | "success" | "warning" | "error";

interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

interface ToastStore {
  toasts: Toast[];
  push: (message: string, tone?: Tone) => void;
  dismiss: (id: number) => void;
  pause: (id: number) => void;
  resume: (id: number) => void;
}

/** Errors linger longer so they can actually be read (design brief). */
const DURATION: Record<Tone, number> = {
  info: 4200,
  success: 4200,
  warning: 6000,
  error: 8000,
};

interface Timer {
  handle: ReturnType<typeof setTimeout> | null;
  remaining: number;
  startedAt: number;
}

const timers = new Map<number, Timer>();
let nextId = 1;

function schedule(id: number, remaining: number, dismiss: (id: number) => void) {
  timers.set(id, {
    handle: setTimeout(() => {
      timers.delete(id);
      dismiss(id);
    }, remaining),
    remaining,
    startedAt: Date.now(),
  });
}

export const useToasts = create<ToastStore>((set, get) => ({
  toasts: [],
  push: (message, tone = "info") => {
    const id = nextId++;
    set((state) => ({ toasts: [...state.toasts, { id, message, tone }] }));
    schedule(id, DURATION[tone], get().dismiss);
  },
  dismiss: (id) => {
    const timer = timers.get(id);
    if (timer?.handle) clearTimeout(timer.handle);
    timers.delete(id);
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },
  pause: (id) => {
    const timer = timers.get(id);
    if (!timer?.handle) return;
    clearTimeout(timer.handle);
    timer.handle = null;
    timer.remaining = Math.max(1000, timer.remaining - (Date.now() - timer.startedAt));
  },
  resume: (id) => {
    const timer = timers.get(id);
    if (!timer || timer.handle) return;
    schedule(id, timer.remaining, get().dismiss);
  },
}));

export const toast = {
  info: (message: string) => useToasts.getState().push(message, "info"),
  success: (message: string) => useToasts.getState().push(message, "success"),
  warning: (message: string) => useToasts.getState().push(message, "warning"),
  error: (message: string) => useToasts.getState().push(message, "error"),
};

const ICONS: Record<Tone, LucideIcon> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
};

const TONE_STYLES: Record<Tone, { border: string; icon: string }> = {
  info: { border: "border-border", icon: "text-text-2" },
  success: { border: "border-success/40", icon: "text-success" },
  warning: { border: "border-warning/40", icon: "text-warning" },
  error: { border: "border-danger/40", icon: "text-danger" },
};

export function Toaster() {
  const { toasts, dismiss, pause, resume } = useToasts();
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[100] flex max-w-sm flex-col items-end gap-2"
    >
      {toasts.map((item) => {
        const Icon = ICONS[item.tone];
        const style = TONE_STYLES[item.tone];
        return (
          <div
            key={item.id}
            role={item.tone === "error" ? "alert" : undefined}
            onMouseEnter={() => pause(item.id)}
            onMouseLeave={() => resume(item.id)}
            className={cn(
              "gf-animate-in pointer-events-auto flex w-fit max-w-full items-start gap-2.5",
              "rounded-lg border bg-surface-1/95 px-3.5 py-2.5 shadow-lg shadow-black/50 backdrop-blur",
              style.border,
            )}
          >
            <Icon
              className={cn("mt-px h-4 w-4 shrink-0", style.icon)}
              strokeWidth={1.75}
              aria-hidden="true"
            />
            <span className="text-[12.5px] leading-snug text-text-1">{item.message}</span>
            <button
              type="button"
              onClick={() => dismiss(item.id)}
              aria-label="Dismiss notification"
              className={cn(
                "-mr-1 -mt-0.5 rounded p-0.5 text-text-3 transition-colors duration-150",
                "hover:bg-surface-2 hover:text-text-1",
                "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
              )}
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
