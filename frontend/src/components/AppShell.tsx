/**
 * Application shell: a persistent left sidebar around the content-area routes
 * (Home, Flows, and the resource managers). The flow canvas at
 * `/flows/:name` renders OUTSIDE this shell — editing stays full-screen.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Boxes,
  Database,
  ExternalLink,
  Hexagon,
  Home,
  type LucideIcon,
  Plug,
  Workflow,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "@/api/client";
import type { RuntimeHealth } from "@/api/types";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { to: "/", label: "Home", icon: Home },
  { to: "/flows", label: "Flows", icon: Workflow },
  { to: "/models", label: "Models", icon: Boxes },
  { to: "/knowledge-bases", label: "Knowledge Bases", icon: Database },
  { to: "/tools", label: "Tools", icon: Plug },
];

function runtimeTone(health: RuntimeHealth | undefined): {
  color: string;
  label: string;
} {
  if (!health || !health.configured)
    return { color: "bg-text-3", label: "No runtime configured" };
  if (health.reachable) return { color: "bg-success", label: "Runtime connected" };
  return { color: "bg-danger", label: "Runtime unreachable" };
}

function RuntimeStatus() {
  const health = useQuery({
    queryKey: ["runtime-health"],
    queryFn: api.runtime.health,
    refetchInterval: 15_000,
    retry: false,
  });
  const { color, label } = runtimeTone(health.data);
  return (
    <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-text-3" title={label}>
      <span className={cn("h-2 w-2 shrink-0 rounded-full", color)} aria-hidden />
      <span className="truncate">{label}</span>
    </div>
  );
}

export function AppShell() {
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.get });

  return (
    <div className="flex h-screen bg-canvas">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-surface-1">
        <div className="flex h-12 items-center gap-2 px-4">
          <Hexagon size={18} strokeWidth={2} className="text-accent" />
          <span className="text-sm font-semibold text-text-1">Agent Builder</span>
        </div>

        <nav className="flex flex-col gap-0.5 px-2 py-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors",
                  isActive
                    ? "bg-surface-2 text-text-1"
                    : "text-text-2 hover:bg-surface-2 hover:text-text-1",
                )
              }
            >
              <Icon size={15} strokeWidth={1.75} className="shrink-0" />
              <span className="truncate">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto border-t border-border pt-1">
          {config.data?.registry_ui_url && (
            <a
              href={config.data.registry_ui_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2.5 px-3 py-2 text-[13px] text-text-2 transition-colors hover:text-text-1"
            >
              <ExternalLink size={15} strokeWidth={1.75} className="shrink-0" />
              <span className="truncate">Registry</span>
            </a>
          )}
          <RuntimeStatus />
          {config.data && (
            <p className="px-3 pb-2 text-[10px] text-text-3">v{config.data.version}</p>
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
