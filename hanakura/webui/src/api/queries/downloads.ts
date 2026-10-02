import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/vue-query';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';
import type { DownloadCreate, DownloadJob } from '@/api/types';

export const useDownloads = () => useQuery({ queryKey: keys.downloads, queryFn: () => unwrap(api.GET('/api/v1/downloads')) });

/** Replace or insert one job in the cached list (used by socket events and mutations). */
export function upsertJob(list: DownloadJob[] | undefined, job: DownloadJob): DownloadJob[] {
  const rest = (list ?? []).filter((j) => j.id !== job.id);
  return [job, ...rest].sort((a, b) => b.id - a.id);
}

/**
 * When the socket last reported each job, so an older answer cannot undo a newer event.
 *
 * A REST answer describes the job as it was when the server received the request. The worker
 * claims a new job within a millisecond of ``POST /downloads`` returning, so ``download_started``
 * regularly reaches the browser first; writing the answer afterwards put the row back to
 * "queued" for the whole download, with only the final event moving it on.
 */
const lastEvent = new Map<number, number>();
const now = () => (typeof performance === 'undefined' ? Date.now() : performance.now());

/** Apply a job carried by a socket event: its state is the newest there is. */
export function applyJobEvent(qc: QueryClient, job: DownloadJob): void {
  lastEvent.set(job.id, now());
  qc.setQueryData<DownloadJob[]>(keys.downloads, (old) => upsertJob(old, job));
}

/** Apply a job answered to a request sent at ``sentAt``, unless an event has overtaken it. */
export function applyJobAnswer(qc: QueryClient, job: DownloadJob, sentAt: number): void {
  if ((lastEvent.get(job.id) ?? -1) > sentAt) return;
  qc.setQueryData<DownloadJob[]>(keys.downloads, (old) => upsertJob(old, job));
}

/**
 * Progress proves the job is running, whatever happened to its start event.
 *
 * Writes only the first time, so the four events a second each job sends stay out of the query
 * cache; the bytes and the speed live in the downloads store.
 */
export function markRunning(qc: QueryClient, id: number): void {
  const list = qc.getQueryData<DownloadJob[]>(keys.downloads);
  const job = list?.find((j) => j.id === id);
  if (!job || job.state !== 'queued') return;
  lastEvent.set(id, now());
  qc.setQueryData<DownloadJob[]>(keys.downloads, upsertJob(list, { ...job, state: 'running' }));
}

export function forgetJobs(ids: number[]): void {
  for (const id of ids) lastEvent.delete(id);
}

export function useCreateDownload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DownloadCreate) => unwrap(api.POST('/api/v1/downloads', { body })),
    onMutate: () => ({ sentAt: now() }),
    onSuccess: (job, _body, context) => applyJobAnswer(qc, job, context.sentAt),
  });
}

type Action = 'pause' | 'resume' | 'cancel' | 'restart';

export function useJobAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: Action }) =>
      unwrap(api.POST(`/api/v1/downloads/{job_id}/${action}` as '/api/v1/downloads/{job_id}/pause', { params: { path: { job_id: id } } })),
    onMutate: () => ({ sentAt: now() }),
    onSuccess: (job, _vars, context) => applyJobAnswer(qc, job, context.sentAt),
  });
}

export function useRemoveJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE('/api/v1/downloads/{job_id}', { params: { path: { job_id: id } } })),
    onSuccess: (_d, id) => {
      forgetJobs([id]);
      qc.setQueryData<DownloadJob[]>(keys.downloads, (old) => (old ?? []).filter((j) => j.id !== id));
    },
  });
}

export function useClearFinished() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/downloads/clear-finished')),
    onSuccess: (ids) => {
      forgetJobs(ids);
      qc.setQueryData<DownloadJob[]>(keys.downloads, (old) => (old ?? []).filter((j) => !ids.includes(j.id)));
    },
  });
}
