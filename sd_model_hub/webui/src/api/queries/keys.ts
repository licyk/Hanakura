/**
 * Stands for "every root" where a root id is expected; the server refuses it as a real root's id.
 * The combined listing is cached under it, so invalidating any root must invalidate it too.
 */
export const COMBINED_VIEW_ID = '*';

/** Query keys, shared by the query modules and the socket handlers. */
export const keys = {
  meta: ['app', 'meta'] as const,
  health: ['app', 'health'] as const,
  settings: ['settings'] as const,
  clientState: (key: string) => ['client-state', key] as const,
  sources: ['sources'] as const,
  civitaiAuth: ['auth', 'civitai'] as const,
  search: (source: string, params: Record<string, unknown>) => ['sources', source, 'search', params] as const,
  model: (source: string, id: string) => ['sources', source, 'model', id] as const,
  hubs: ['hubs'] as const,
  hubSearch: (hub: string, params: Record<string, unknown>) => ['hubs', hub, 'search', params] as const,
  repo: (hub: string, id: string, revision: string | null) => ['hubs', hub, 'repo', id, revision] as const,
  downloads: ['downloads'] as const,
  roots: ['library', 'roots'] as const,
  entries: (rootId: string, path?: string, kind?: string | null) => (path === undefined ? (['library', 'entries', rootId] as const) : (['library', 'entries', rootId, path, kind ?? null] as const)),
  tree: (rootId: string) => ['library', 'tree', rootId] as const,
  modelInfo: (rootId: string, path: string) => ['library', 'model', rootId, path] as const,
};
