import { AlertTriangle } from "lucide-react";
import { Component, lazy, Suspense, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import { beginLogin, completeLogin, getToken, setAuthConfig } from "@/api/auth";
import { Button } from "@/components/ui/button";

import { FlowsPage } from "./builder/FlowsPage";

// Route-level code splitting: the flows list must not pay for the whole
// react-flow builder bundle on first paint.
const BuilderPage = lazy(() =>
  import("./builder/BuilderPage").then((m) => ({ default: m.BuilderPage })),
);

/** Skeleton shown while a lazy route chunk loads (never a bare "loading…"). */
function RouteFallback() {
  return (
    <div className="flex h-screen flex-col bg-canvas" aria-busy="true" aria-label="Loading page">
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <div className="h-4 w-24 animate-pulse rounded-md bg-surface-2" />
        <div className="ml-auto flex items-center gap-2">
          <div className="h-7 w-20 animate-pulse rounded-md bg-surface-2" />
          <div className="h-7 w-20 animate-pulse rounded-md bg-surface-2" />
        </div>
      </div>
      <div className="min-h-0 flex-1 p-6">
        <div className="h-full animate-pulse rounded-xl bg-surface-1" />
      </div>
    </div>
  );
}

interface ErrorBoundaryState {
  error: Error | null;
}

/** Top-level error boundary: render errors get a readable panel with a retry
 * instead of a white screen (design brief: never console-only). */
class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen items-center justify-center bg-canvas p-6">
          <div
            role="alert"
            className="w-full max-w-md rounded-lg border border-border border-l-2 border-l-danger bg-surface-1 p-4 shadow-xl shadow-black/30"
          >
            <p className="flex items-center gap-2 text-sm font-semibold text-text-1">
              <AlertTriangle size={16} strokeWidth={1.75} className="text-danger" />
              Something went wrong
            </p>
            <p className="mt-1.5 break-words font-mono text-xs text-text-2">
              {this.state.error.message || String(this.state.error)}
            </p>
            <div className="mt-3 flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => this.setState({ error: null })}>
                Try again
              </Button>
              <Button size="sm" variant="ghost" onClick={() => window.location.assign("/")}>
                Back to flows
              </Button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/** OIDC callback target: exchange the code, then return to where we were. */
function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    completeLogin()
      .then((target) => navigate(target, { replace: true }))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [navigate]);
  if (error) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-danger">
        Login failed: {error}
      </div>
    );
  }
  return <RouteFallback />;
}

/**
 * Bootstrap gate (SPEC §2.7): load /config; with auth_mode=oidc and no token,
 * redirect to the shared Keycloak realm (Code + PKCE) before rendering.
 */
function AuthGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("Loading…");
  const isCallback = window.location.pathname.startsWith("/auth/callback");
  useEffect(() => {
    api.config
      .get()
      .then(async (config) => {
        setAuthConfig(config);
        if (config.auth_mode === "oidc" && !getToken() && !isCallback) {
          setMessage("Redirecting to sign-in…");
          await beginLogin();
          return;
        }
        setReady(true);
      })
      .catch(() => {
        // config unreachable (backend down) — render anyway; queries will error visibly
        setReady(true);
      });
  }, [isCallback]);
  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-text-3">
        {message}
      </div>
    );
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthGate>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<FlowsPage />} />
            <Route path="/flows/:flowName" element={<BuilderPage />} />
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AuthGate>
    </ErrorBoundary>
  );
}
