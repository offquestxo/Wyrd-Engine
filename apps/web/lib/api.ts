// Backend client. The browser calls the API through the web app's own origin: Next.js
// forwards /api/* to the FastAPI server on 127.0.0.1:8000 (next.config.ts). That keeps one
// port to expose later (e.g. `tailscale serve` of :3000 for phone access, SPEC §13).
// NEXT_PUBLIC_API_URL can still point the browser straight at the API.

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ""

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    })
  } catch {
    throw new ApiError("Can't reach the engine API. Is `make dev` running?", 0)
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === "string") detail = body.detail
    } catch {
      // keep statusText
    }
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const fetcher = <T>(path: string) => api<T>(path)
