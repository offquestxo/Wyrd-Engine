// Backend client. The API binds to 127.0.0.1:8000 (see Makefile).

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"

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
    throw new ApiError("Can't reach the engine API on 127.0.0.1:8000. Is `make dev` running?", 0)
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
  return (await res.json()) as T
}

export const fetcher = <T>(path: string) => api<T>(path)
