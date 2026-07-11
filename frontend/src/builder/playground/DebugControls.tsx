/** Debug-mode step bar (§11.7): step / continue / abort / inspect state. */

import { Braces, Play, Square, StepForward } from "lucide-react";

import { Button } from "@/components/ui/button";

export function DebugControls({
  onStep,
  onContinue,
  onAbort,
  onInspectState,
}: {
  onStep: () => void;
  onContinue: () => void;
  onAbort: () => void;
  onInspectState: () => void;
}) {
  return (
    <div className="flex items-center gap-1.5 border-t border-border px-3 py-1.5">
      <span className="text-[11px] uppercase tracking-widest text-text-3">debug</span>
      <Button variant="ghost" className="!h-6 !px-2 !text-xs" onClick={onStep}>
        <StepForward className="h-3.5 w-3.5" strokeWidth={1.75} />
        Step
      </Button>
      <Button variant="ghost" className="!h-6 !px-2 !text-xs" onClick={onContinue}>
        <Play className="h-3.5 w-3.5" strokeWidth={1.75} />
        Continue
      </Button>
      <Button variant="ghost" className="!h-6 !px-2 !text-xs" onClick={onAbort}>
        <Square className="h-3.5 w-3.5" strokeWidth={1.75} />
        Abort
      </Button>
      <Button variant="ghost" className="!h-6 !px-2 !text-xs" onClick={onInspectState}>
        <Braces className="h-3.5 w-3.5" strokeWidth={1.75} />
        State
      </Button>
    </div>
  );
}
