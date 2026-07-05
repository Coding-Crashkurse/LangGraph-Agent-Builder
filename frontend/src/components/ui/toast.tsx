import { create } from "zustand";

import { cn } from "@/lib/utils";

interface Toast {
  id: number;
  message: string;
  tone: "info" | "error" | "success";
}

interface ToastStore {
  toasts: Toast[];
  push: (message: string, tone?: Toast["tone"]) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToasts = create<ToastStore>((set) => ({
  toasts: [],
  push: (message, tone = "info") => {
    const id = nextId++;
    set((state) => ({ toasts: [...state.toasts, { id, message, tone }] }));
    setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
    }, 4200);
  },
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  info: (message: string) => useToasts.getState().push(message, "info"),
  error: (message: string) => useToasts.getState().push(message, "error"),
  success: (message: string) => useToasts.getState().push(message, "success"),
};

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2">
      {toasts.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => dismiss(item.id)}
          className={cn(
            "gf-animate-in pointer-events-auto rounded-lg border px-3.5 py-2.5 text-left text-xs",
            "shadow-lg shadow-black/50 backdrop-blur transition-opacity",
            item.tone === "error" && "border-red-800/60 bg-red-950/90 text-red-200",
            item.tone === "success" && "border-emerald-800/60 bg-emerald-950/90 text-emerald-200",
            item.tone === "info" && "border-surface-700 bg-surface-800/95 text-zinc-200",
          )}
        >
          {item.message}
        </button>
      ))}
    </div>
  );
}
