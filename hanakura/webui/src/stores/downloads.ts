import { defineStore } from 'pinia';
import { reactive, ref } from 'vue';
import type { DownloadJob } from '@/api/types';

export interface LiveProgress {
  bytes: number;
  total: number | null;
  speed: number;
}

/** High-frequency progress lives here, not in the query cache, so lists do not re-render on every tick. */
export const useDownloadsStore = defineStore('downloads', () => {
  const progress = reactive(new Map<number, LiveProgress>());
  const drawerOpen = ref(false);

  function onProgress(id: number, bytes: number, total: number | null, speed: number) {
    progress.set(id, { bytes, total, speed });
  }
  function onJob(job: DownloadJob) {
    if (job.state !== 'running') progress.delete(job.id);
    else progress.set(job.id, { bytes: job.bytes_done, total: job.total_bytes ?? null, speed: job.speed });
  }
  return { progress, drawerOpen, onProgress, onJob };
});
