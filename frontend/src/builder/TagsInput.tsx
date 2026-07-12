/**
 * Comma-separated tags input. Keeps the raw text locally so typing a comma
 * (or trailing spaces) is not eaten by the parse→join round-trip; the parsed
 * list is emitted on every change.
 */

import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";

function parseTags(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

function sameTags(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((tag, i) => tag === b[i]);
}

export function TagsInput({
  value,
  onChange,
  placeholder,
}: {
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState(() => value.join(", "));

  // Resync when the tags change from outside (flow load, import) — but keep
  // the raw text while it still parses to the same list (mid-typing commas).
  useEffect(() => {
    setText((current) => (sameTags(parseTags(current), value) ? current : value.join(", ")));
  }, [value]);

  return (
    <Input
      value={text}
      placeholder={placeholder}
      onChange={(e) => {
        setText(e.target.value);
        onChange(parseTags(e.target.value));
      }}
    />
  );
}
