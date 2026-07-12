/**
 * OIDC Authorization Code + PKCE against the shared Keycloak realm (SPEC §2.7).
 *
 * `auth_mode=none` (local dev): every helper is a no-op and requests carry no
 * Authorization header. With `oidc`, the access token lives in sessionStorage
 * and is attached to every backend call; the backend forwards it to the
 * runtime. 401 responses trigger a fresh login redirect.
 */

import type { FrontendConfig } from "./types";

const TOKEN_KEY = "builder.access_token";
const VERIFIER_KEY = "builder.pkce_verifier";
const RETURN_KEY = "builder.return_to";

let config: FrontendConfig | null = null;

export function setAuthConfig(next: FrontendConfig): void {
  config = next;
}

export function authMode(): "none" | "oidc" {
  return config?.auth_mode ?? "none";
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

function base64Url(bytes: Uint8Array): string {
  let text = "";
  for (const b of bytes) text += String.fromCharCode(b);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sha256(text: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return new Uint8Array(digest);
}

function redirectUri(): string {
  return `${window.location.origin}/auth/callback`;
}

/** Begin the code+PKCE flow: remember where we were, go to the issuer. */
export async function beginLogin(): Promise<void> {
  if (!config || config.auth_mode !== "oidc") return;
  const verifier = base64Url(crypto.getRandomValues(new Uint8Array(48)));
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(RETURN_KEY, window.location.pathname + window.location.search);
  const challenge = base64Url(await sha256(verifier));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.oidc_client_id,
    redirect_uri: redirectUri(),
    scope: "openid profile",
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  const issuer = config.oidc_issuer.replace(/\/$/, "");
  window.location.assign(`${issuer}/protocol/openid-connect/auth?${params}`);
}

/** Handle /auth/callback: exchange the code, store the token, return target. */
export async function completeLogin(): Promise<string> {
  if (!config || config.auth_mode !== "oidc") return "/";
  const code = new URLSearchParams(window.location.search).get("code");
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!code || !verifier) throw new Error("login callback without code/verifier");
  const issuer = config.oidc_issuer.replace(/\/$/, "");
  const response = await fetch(`${issuer}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.oidc_client_id,
      redirect_uri: redirectUri(),
      code,
      code_verifier: verifier,
    }),
  });
  if (!response.ok) throw new Error(`token exchange failed: ${response.status}`);
  const payload = (await response.json()) as { access_token?: string };
  if (!payload.access_token) throw new Error("token endpoint returned no access_token");
  sessionStorage.setItem(TOKEN_KEY, payload.access_token);
  sessionStorage.removeItem(VERIFIER_KEY);
  const target = sessionStorage.getItem(RETURN_KEY) ?? "/";
  sessionStorage.removeItem(RETURN_KEY);
  return target;
}

/** Attach the bearer token (oidc mode) to request headers. */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** React to a 401 from the backend: drop the stale token and re-login. */
export async function onUnauthorized(): Promise<void> {
  clearToken();
  await beginLogin();
}
