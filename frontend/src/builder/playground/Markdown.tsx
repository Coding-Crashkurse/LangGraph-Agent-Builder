/** Assistant-message markdown (§11.7): react-markdown + GFM, code blocks in
 * mono on surface-2 with a copy button. Streamed tokens re-render this without
 * animation — the text simply grows. */

import { isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { CopyButton } from "./CopyButton";

/** Plain text of a rendered React subtree (for the code copy button). */
function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="min-w-0 break-words text-[13px] leading-[1.45] text-text-1">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="my-1 first:mt-0 last:mb-0">{children}</p>,
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-accent underline decoration-accent/50 underline-offset-2 hover:decoration-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
            >
              {children}
            </a>
          ),
          ul: ({ children }) => <ul className="my-1 list-disc pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-1 list-decimal pl-5">{children}</ol>,
          li: ({ children }) => <li className="my-0.5">{children}</li>,
          h1: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h3>,
          h2: ({ children }) => <h4 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h4>,
          h3: ({ children }) => <h5 className="mb-1 mt-1.5 text-[13px] font-semibold first:mt-0">{children}</h5>,
          h4: ({ children }) => <h6 className="mb-0.5 mt-1.5 text-[13px] font-semibold first:mt-0">{children}</h6>,
          blockquote: ({ children }) => (
            <blockquote className="my-1 border-l-2 border-border-strong pl-2.5 text-text-2">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-2 border-border" />,
          table: ({ children }) => (
            <div className="my-1.5 overflow-x-auto">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border bg-surface-2 px-1.5 py-0.5 text-left font-medium text-text-2">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-border px-1.5 py-0.5 align-top">{children}</td>
          ),
          pre: ({ children }) => (
            <div className="group relative my-1.5">
              <CopyButton
                text={textOf(children)}
                label="Copy code"
                className="absolute right-1 top-1 bg-surface-2/80"
              />
              <pre className="overflow-x-auto rounded-lg border border-border bg-surface-2 p-2.5 pr-8 font-mono text-xs leading-relaxed text-text-1">
                {children}
              </pre>
            </div>
          ),
          code: ({ children, className }) =>
            className?.includes("language-") ? (
              <code className={`${className} font-mono`}>{children}</code>
            ) : (
              <code className="rounded bg-surface-2 px-1 py-px font-mono text-xs">
                {children}
              </code>
            ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
