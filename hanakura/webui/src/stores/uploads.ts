import { defineStore } from 'pinia';
import { computed, reactive } from 'vue';
import { ApiError, uploadFile } from '@/api/client';

export interface UploadItem {
  id: number;
  rootId: string;
  dir: string;
  name: string;
  size: number;
  loaded: number;
  state: 'queued' | 'uploading' | 'done' | 'failed' | 'cancelled';
  error?: string;
  file: File;
  controller: AbortController;
}

let nextId = 1;
const CONCURRENCY = 2;

/** Files dropped into the library, uploaded one request per file with per-file progress. */
export const useUploadsStore = defineStore('uploads', () => {
  const items = reactive<UploadItem[]>([]);
  const active = computed(() => items.filter((i) => i.state === 'queued' || i.state === 'uploading').length);
  const listeners = new Set<(item: UploadItem) => void>();

  function onFinished(fn: (item: UploadItem) => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function enqueue(rootId: string, dir: string, files: { file: File; relativePath: string }[]) {
    for (const f of files) {
      items.unshift({ id: nextId++, rootId, dir, name: f.relativePath, size: f.file.size, loaded: 0, state: 'queued', file: f.file, controller: new AbortController() });
    }
    pump();
  }

  function pump() {
    const running = items.filter((i) => i.state === 'uploading').length;
    const next = items.filter((i) => i.state === 'queued').reverse().slice(0, Math.max(0, CONCURRENCY - running));
    for (const item of next) start(item);
  }

  async function start(item: UploadItem) {
    item.state = 'uploading';
    try {
      await uploadFile({ rootId: item.rootId, dir: item.dir, name: item.name }, item.file, (loaded) => (item.loaded = loaded), item.controller.signal);
      item.state = 'done';
      item.loaded = item.size;
    } catch (e) {
      const err = e as ApiError;
      item.state = err.code === 'aborted' ? 'cancelled' : 'failed';
      item.error = err.message;
    }
    listeners.forEach((fn) => fn(item));
    pump();
  }

  function cancel(id: number) {
    const item = items.find((i) => i.id === id);
    if (!item) return;
    if (item.state === 'queued') item.state = 'cancelled';
    else item.controller.abort();
  }

  function clearFinished() {
    for (let i = items.length - 1; i >= 0; i--) if (!['queued', 'uploading'].includes(items[i].state)) items.splice(i, 1);
  }

  /** The server also reports progress; used only as a fallback when the browser gives none. */
  function onServerProgress(rootId: string, relPath: string, bytes: number, done: boolean) {
    const item = items.find((i) => i.rootId === rootId && relPath.endsWith(i.name) && i.state === 'uploading');
    if (item && bytes > item.loaded) item.loaded = bytes;
    if (item && done) item.loaded = item.size;
  }

  return { items, active, enqueue, cancel, clearFinished, onServerProgress, onFinished };
});
