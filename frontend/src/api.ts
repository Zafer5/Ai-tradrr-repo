export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch("/api" + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (r.status === 401 && path !== "/auth/login") window.dispatchEvent(new Event("unauthorized"));
  if (!r.ok) {
    let msg = r.statusText || "Hata";
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* gövde yok */
    }
    throw new ApiError(msg, r.status);
  }
  return r.json() as Promise<T>;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type J = any;

export const api = {
  get: <T = J>(p: string) => req<T>("GET", p),
  post: <T = J>(p: string, b?: unknown) => req<T>("POST", p, b ?? {}),
  put: <T = J>(p: string, b: unknown) => req<T>("PUT", p, b),
  patch: <T = J>(p: string, b: unknown) => req<T>("PATCH", p, b),
  del: <T = J>(p: string) => req<T>("DELETE", p),
};
