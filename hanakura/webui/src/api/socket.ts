import type { QueryClient } from '@tanstack/vue-query';
import { io, type Socket } from 'socket.io-client';
import { BASE_PATH, BASE_URL } from '@/api/baseUrl';
import { applyJobEvent, forgetJobs, markRunning } from '@/api/queries/downloads';
import { COMBINED_VIEW_ID, keys } from '@/api/queries/keys';
import type { DownloadJob, ServerEvents } from '@/api/types';
import { useAuthStore } from '@/stores/auth';
import { useDownloadsStore } from '@/stores/downloads';
import { useUploadsStore } from '@/stores/uploads';

type Listeners = { [K in keyof ServerEvents]: (payload: ServerEvents[K]) => void };

let socket: Socket<Listeners> | null = null;

const JOB_EVENTS = ['download_queued', 'download_started', 'download_completed', 'download_failed', 'download_cancelled', 'download_paused'] as const;

/**
 * Connect once. REST stays the source of truth: events patch or invalidate the query cache, and a
 * reconnect refetches the download list and the library.
 */
export function connectSocket(qc: QueryClient): Socket<Listeners> {
  if (socket) return socket;
  const downloads = useDownloadsStore();
  const uploads = useUploadsStore();
  socket = io(new URL(BASE_URL).origin, {
    path: `${BASE_PATH}/ws/socket.io`,
    auth: (cb) => cb({ token: useAuthStore().token }),
    transports: ['websocket', 'polling'],
    // The server restarting is routine in development; back off instead of hammering it.
    reconnectionDelay: 1000,
    reconnectionDelayMax: 10_000,
  });

  for (const name of JOB_EVENTS) {
    socket.on(name, (payload: { job: DownloadJob }) => {
      applyJobEvent(qc, payload.job);
      downloads.onJob(payload.job);
      if (name === 'download_completed' && payload.job.root_id) {
        qc.invalidateQueries({ queryKey: keys.entries(payload.job.root_id) });
        qc.invalidateQueries({ queryKey: keys.entries(COMBINED_VIEW_ID) });
      }
    });
  }
  socket.on('download_progress', (p) => {
    downloads.onProgress(p.job_id, p.bytes_done, p.total_bytes ?? null, p.speed);
    markRunning(qc, p.job_id);
  });
  socket.on('download_removed', (p) => {
    forgetJobs(p.job_ids);
    qc.setQueryData<DownloadJob[]>(keys.downloads, (old) => (old ?? []).filter((j) => !p.job_ids.includes(j.id)));
  });
  socket.on('library_changed', (p) => {
    qc.invalidateQueries({ queryKey: keys.entries(p.root_id) });
    qc.invalidateQueries({ queryKey: keys.entries(COMBINED_VIEW_ID) });
    qc.invalidateQueries({ queryKey: keys.tree(p.root_id) });
  });
  socket.on('import_progress', (p) => uploads.onServerProgress(p.root_id, p.rel_path, p.bytes_done, p.done));
  socket.io.on('reconnect', () => {
    qc.invalidateQueries({ queryKey: keys.downloads });
    qc.invalidateQueries({ queryKey: ['library'] });
  });
  return socket;
}

export function disconnectSocket() {
  socket?.disconnect();
  socket = null;
}
