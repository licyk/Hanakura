import createClient, { type Middleware } from 'openapi-fetch';
import { BASE_URL } from '@/api/baseUrl';
import type { paths } from '@/api/schema';
import { useAuthStore } from '@/stores/auth';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = useAuthStore().token;
    if (token) request.headers.set('Authorization', `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401) useAuthStore().needed = true;
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: BASE_URL });
api.use(auth);

type Result<T> = { data?: T; error?: unknown; response: Response };

function toError(error: unknown, response: Response): ApiError {
  if (error && typeof error === 'object') {
    const e = error as { code?: string; message?: string; detail?: unknown };
    if (typeof e.message === 'string') return new ApiError(response.status, e.code ?? 'error', e.message, (e.detail as Record<string, unknown>) ?? {});
    if (Array.isArray(e.detail)) {
      const first = e.detail[0] as { msg?: string; loc?: unknown[] } | undefined;
      return new ApiError(response.status, 'invalid_input', first?.msg ?? 'Invalid input', { errors: e.detail });
    }
  }
  return new ApiError(response.status, 'error', `${response.status} ${response.statusText}`);
}

/** Await an openapi-fetch call and return its data, or throw an ApiError with the server's message. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) throw toError(error, response);
  return data as T;
}

/** URL of a library preview thumbnail. The token cookie authenticates the <img> request. */
export function previewUrl(rootId: string, path: string, size = 384): string {
  const q = new URLSearchParams({ path, size: String(size) });
  return `${BASE_URL}/api/v1/library/roots/${encodeURIComponent(rootId)}/preview?${q}`;
}

/** URL of a library file served as an attachment. Like a preview, the token cookie authenticates it. */
export function fileUrl(rootId: string, path: string): string {
  const q = new URLSearchParams({ path });
  return `${BASE_URL}/api/v1/library/roots/${encodeURIComponent(rootId)}/file?${q}`;
}

/**
 * Save a library file through the browser's own download manager. A link is followed rather than
 * the file fetched, because a model runs to gigabytes and a Blob would hold all of it in memory.
 */
export function saveFile(rootId: string, path: string): void {
  const link = document.createElement('a');
  link.href = fileUrl(rootId, path);
  link.download = path.split('/').pop() ?? '';
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
}

/**
 * Upload one file with the raw request body, reporting progress. fetch() cannot report upload
 * progress, so this uses XMLHttpRequest.
 */
export function uploadFile(
  params: { rootId: string; dir: string; name: string; onConflict?: 'error' | 'rename' },
  file: Blob,
  onProgress: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<{ root_id: string; path: string }> {
  return new Promise((resolve, reject) => {
    const q = new URLSearchParams({ root_id: params.rootId, path: params.dir, name: params.name, on_conflict: params.onConflict ?? 'error' });
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', `${BASE_URL}/api/v1/library/upload?${q}`);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    const token = useAuthStore().token;
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : file.size);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as { root_id: string; path: string });
      else reject(toError(body, new Response(null, { status: xhr.status, statusText: xhr.statusText })));
    };
    xhr.onerror = () => reject(new ApiError(0, 'network', 'Network error'));
    xhr.onabort = () => reject(new ApiError(0, 'aborted', 'Upload cancelled'));
    signal?.addEventListener('abort', () => xhr.abort());
    xhr.send(file);
  });
}
