/**
 * Share = export canonical FlowDefinition YAML (SPEC §5): download or copy.
 * The file is importable here, deployable via `agentplane deploy`, and
 * git-safe (no secrets, deterministic order).
 */

import { Check, Copy, Download } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { copyToClipboard } from "@/lib/utils";

export function ShareDialog({
  flowName,
  open,
  onClose,
}: {
  flowName: string;
  open: boolean;
  onClose: () => void;
}) {
  const [yamlText, setYamlText] = useState<string>("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) return;
    setCopied(false);
    api.flows
      .exportText(flowName, "yaml")
      .then(setYamlText)
      .catch((err: unknown) =>
        setYamlText(`# export failed: ${err instanceof Error ? err.message : String(err)}`),
      );
  }, [open, flowName]);

  const download = () => {
    const blob = new Blob([yamlText], { type: "application/yaml" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${flowName}.flow.yaml`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Dialog open={open} onClose={onClose} title={`Share ${flowName}`} className="max-w-2xl">
      <p className="text-xs leading-relaxed text-text-3">
        Canonical FlowDefinition YAML — import it here, deploy it with{" "}
        <code className="font-mono text-text-2">agentplane deploy</code>, or commit it to git.
        Resources are referenced by name; the file never contains credentials.
      </p>
      <pre className="mt-3 max-h-80 overflow-auto rounded-lg border border-border bg-canvas p-3 font-mono text-[11px] leading-relaxed text-text-2">
        {yamlText || "…"}
      </pre>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" onClick={download}>
          <Download size={13} /> Download .flow.yaml
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            void copyToClipboard(yamlText).then(() => setCopied(true));
          }}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </Dialog>
  );
}
