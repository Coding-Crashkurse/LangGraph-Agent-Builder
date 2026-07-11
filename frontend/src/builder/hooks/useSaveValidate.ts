/** Single save/validate orchestrator for the builder (SPEC §11.6/§18.1).
 *
 * Previously draft persistence lived in four call sites (manual Save, the
 * autosave effect, the silent-validate effect, PublishDialog's beforePublish)
 * with different post-behavior: manual Save rebuilt the canvas via loadFlow —
 * wiping the undo stack — and the two debounced effects could fire overlapping
 * PATCH requests racing each other. This hook is the one path:
 *
 * - `saveDraft()` is serialized (at most one PATCH in flight, ever) and marks
 *   the store saved WITHOUT rebuilding the canvas, so undo history survives.
 *   If the graph changes while the PATCH is in flight, `dirty` stays set and
 *   the next save picks the edits up.
 * - `validate()` chains after `saveDraft()` instead of PATCHing independently;
 *   stale responses are dropped (latest validation wins).
 * - Autosave and the debounced silent validation subscribe to the store
 *   directly (no render churn) and both funnel into the same queue.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/api/client";
import { toast } from "@/components/ui/toast";

import { useBuilder } from "../store";
import { useServerConfig } from "./useServerConfig";

const VALIDATE_DEBOUNCE_MS = 600;

export interface SaveValidate {
  /** Manual Save (toolbar button, Ctrl+S, beforePublish). Toasts on result. */
  save: () => Promise<void>;
  /** Silent, serialized draft persistence. Rejects on failure. */
  saveDraft: () => Promise<void>;
  /** Persist-if-dirty, then POST /validate. `silent` skips toasts+coercions. */
  validate: (deep?: boolean, silent?: boolean) => Promise<void>;
  /** True while edits have not been re-validated yet (gates Publish). */
  needsValidation: boolean;
}

export function useSaveValidate(): SaveValidate {
  const [needsValidation, setNeedsValidation] = useState(true);
  const config = useServerConfig();
  const configRef = useRef(config);
  configRef.current = config;

  // ------------------------------------------------ serialized draft queue
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const saveDraft = useCallback(() => {
    const run = async () => {
      const before = useBuilder.getState();
      if (!before.flow || !before.dirty) return;
      const { nodes, edges, baseSpec } = before;
      await api.flows.update(before.flow.id, before.currentSpec());
      const after = useBuilder.getState();
      // Only clear "dirty" if nothing changed while the PATCH was in flight —
      // otherwise the amber badge stays and the next save catches up.
      if (after.nodes === nodes && after.edges === edges && after.baseSpec === baseSpec) {
        after.markSaved();
      }
    };
    // serialize: next save starts only after the previous settled
    const next = queueRef.current.then(run, run);
    queueRef.current = next.then(
      () => undefined,
      () => undefined,
    );
    return next;
  }, []);

  const save = useCallback(async () => {
    try {
      await saveDraft();
      toast.success("saved");
    } catch (error) {
      // a 422 carries structured diagnostics — surface them in the panel
      if (error instanceof ApiError && error.diagnostics?.length) {
        useBuilder.getState().setDiagnostics(error.diagnostics);
      }
      toast.error(`save failed: ${(error as Error).message}`);
    }
  }, [saveDraft]);

  // ------------------------------------------------ validation (latest wins)
  const validateSeq = useRef(0);
  const validate = useCallback(
    async (deep = false, silent = false) => {
      const flowId = useBuilder.getState().flow?.id;
      if (!flowId) return;
      const seq = ++validateSeq.current;
      try {
        if (useBuilder.getState().dirty) await saveDraft();
        const result = await api.flows.validate(flowId, deep);
        if (seq !== validateSeq.current) return; // superseded by a newer call
        const store = useBuilder.getState();
        store.setDiagnostics(result.diagnostics);
        // Applying coercions rewrites edges; skip in silent auto-validate so
        // the debounced subscription does not re-trigger itself.
        if (!silent && result.compile_report?.coercions) {
          store.applyCoercions(result.compile_report.coercions);
        }
        setNeedsValidation(false);
        if (!silent) {
          const errors = result.diagnostics.filter((d) => d.severity === "error").length;
          if (errors === 0) toast.success(`valid — ${result.diagnostics.length} diagnostics`);
          else toast.error(`${errors} error(s)`);
        }
      } catch (error) {
        if (!silent) toast.error(`validate failed: ${(error as Error).message}`);
      }
    },
    [saveDraft],
  );
  const validateRef = useRef(validate);
  validateRef.current = validate;
  const saveDraftRef = useRef(saveDraft);
  saveDraftRef.current = saveDraft;

  // ----------------------- edits → mark unvalidated + debounced silent check
  // Publishing is gated on a CURRENT, clean validation (SPEC §11.6). Every
  // edit marks the graph unvalidated; a debounced silent validation refreshes
  // diagnostics so Publish reflects reality without a manual Validate click.
  useEffect(() => {
    let timer: number | undefined;
    const unsub = useBuilder.subscribe((state, prev) => {
      const loaded = state.flow !== null && state.flow !== prev.flow;
      const edited =
        state.dirty &&
        (state.nodes !== prev.nodes ||
          state.edges !== prev.edges ||
          state.baseSpec !== prev.baseSpec);
      if (!loaded && !edited) return;
      setNeedsValidation(true);
      window.clearTimeout(timer);
      timer = window.setTimeout(
        () => void validateRef.current(false, true),
        VALIDATE_DEBOUNCE_MS,
      );
    });
    return () => {
      unsub();
      window.clearTimeout(timer);
    };
  }, []);

  // ------------------------------------------------ autosave (LGA_AUTO_SAVING)
  useEffect(() => {
    let timer: number | undefined;
    const unsub = useBuilder.subscribe((state, prev) => {
      if (!configRef.current.auto_saving || !state.flow || !state.dirty) return;
      const changed =
        state.dirty !== prev.dirty ||
        state.nodes !== prev.nodes ||
        state.edges !== prev.edges ||
        state.baseSpec !== prev.baseSpec;
      if (!changed) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        // silent — the amber "unsaved" badge stays until a save succeeds
        void saveDraftRef.current().catch(() => {});
      }, configRef.current.auto_saving_interval_ms);
    });
    return () => {
      unsub();
      window.clearTimeout(timer);
    };
  }, []);

  return { save, saveDraft, validate, needsValidation };
}
