/** Auth contracts shared by auth-service and graph-collab-service.
 *  The actual provider fetch lives in auth-service; here we keep the types
 *  and a header/token helper so the ws handshake and HTTP routes agree. */

export type AuthProvider = "gitlab" | "github";

export interface AuthUser {
  id: string;
  username: string;
  token: string;
}

export interface AuthConfig {
  provider: AuthProvider;
  /** Base URL of the git host API (self-hosted GitLab, github.com, …). */
  gitUrl: string;
  cookieTokenName: string;
  /** Static token the agent (mcp-service) presents to join rooms. */
  agentServiceToken: string;
}

/** Pull a bearer/cookie/query token out of a request's headers. */
export function tokenFromHeaders(
  headers: Record<string, string | string[] | undefined>,
  cookieName: string,
): string | null {
  const auth = headers["authorization"];
  const authStr = Array.isArray(auth) ? auth[0] : auth;
  if (authStr?.toLowerCase().startsWith("bearer ")) return authStr.slice(7).trim();

  const cookie = headers["cookie"];
  const cookieStr = Array.isArray(cookie) ? cookie[0] : cookie;
  if (cookieStr) {
    for (const part of cookieStr.split(";")) {
      const [k, ...rest] = part.trim().split("=");
      if (k === cookieName) return decodeURIComponent(rest.join("="));
    }
  }
  return null;
}

/** The `actor` string stamped into journal entries. */
export const humanActor = (u: AuthUser): string => `user:${u.username}`;
export const AGENT_ACTOR = "agent:claude";
