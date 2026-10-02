<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useJobAction, useRemoveJob } from '@/api/queries/downloads';
import { locatePath } from '@/api/queries/library';
import type { DownloadJob } from '@/api/types';
import { formatBytes, formatEta } from '@/format';
import { useI18n } from '@/i18n';
import { useDownloadsStore } from '@/stores/downloads';
import { AppIcon, IconButton, PathText, ProgressBar, icons, useSnackbar } from '@/ui';

const props = defineProps<{ job: DownloadJob }>();
const { t } = useI18n();
const router = useRouter();
const live = useDownloadsStore();
const action = useJobAction();
const remove = useRemoveJob();
const snackbar = useSnackbar();

const progress = computed(() => {
  const p = live.progress.get(props.job.id);
  return { bytes: p?.bytes ?? props.job.bytes_done, total: p?.total ?? props.job.total_bytes ?? null, speed: p?.speed ?? props.job.speed };
});
const fraction = computed(() => {
  if (props.job.state === 'completed') return 1;
  const { bytes, total } = progress.value;
  if (!total) return props.job.state === 'running' ? null : 0;
  return Math.min(1, bytes / total);
});
const detail = computed(() => {
  const { bytes, total, speed } = progress.value;
  const parts = [total ? `${formatBytes(bytes)} / ${formatBytes(total)}` : formatBytes(bytes)];
  if (props.job.state === 'running' && speed) {
    parts.push(t('downloads.speed', { speed: formatBytes(speed) }));
    if (total) parts.push(formatEta(total - bytes, speed));
  }
  return parts.filter(Boolean).join(' · ');
});
const stateIcon = computed(
  () => ({ completed: icons.Check, failed: icons.AlertTriangle, cancelled: icons.X, paused: icons.Pause, queued: icons.Loader2, running: icons.ArrowDownToLine })[props.job.state],
);

/**
 * Open the folder the file landed in. A job started with an absolute folder carries no root, so
 * the server is asked which root holds it; one outside every root cannot be shown.
 */
async function openFolder() {
  try {
    const dest = props.job.root_id ? { root_id: props.job.root_id, path: props.job.rel_dir } : await locatePath(props.job.dest_dir);
    live.drawerOpen = false;
    router.push({ path: '/library', query: { root: dest.root_id, path: dest.path || undefined } });
  } catch {
    snackbar.error(t('downloads.openFolderFailed', { path: props.job.dest_dir }));
  }
}

function run(kind: 'pause' | 'resume' | 'cancel' | 'restart') {
  action.mutate({ id: props.job.id, action: kind }, { onError: (e) => snackbar.error((e as Error).message) });
}
</script>

<template>
  <article class="item" :class="job.state">
    <span class="state-icon"><AppIcon :icon="stateIcon" :size="20" :spin="job.state === 'queued'" /></span>
    <div class="main">
      <h3 class="type-title-small title" :title="job.title">{{ job.title }}</h3>
      <p class="type-body-small muted sub">
        <span>{{ t(`downloads.states.${job.state}`) }}</span>
        <span v-if="job.state !== 'queued'"> · {{ detail }}</span>
      </p>
      <ProgressBar v-if="job.state === 'running' || job.state === 'paused' || job.state === 'queued'" :value="job.state === 'queued' ? 0 : fraction" class="bar" />
      <p v-if="job.error" class="type-body-small error">{{ job.error }}</p>
      <p v-if="!job.can_pause && job.state === 'running'" class="type-body-small muted">{{ t('hubs.noPause') }}</p>
      <PathText v-if="job.final_path && job.state === 'completed'" :path="job.final_path" class="type-body-small muted" />
    </div>
    <div class="actions">
      <IconButton v-if="job.state === 'running' && job.can_pause" :icon="icons.Pause" :label="t('downloads.pause')" @click="run('pause')" />
      <IconButton v-if="job.state === 'paused' || (job.state === 'failed' && job.can_pause)" :icon="icons.Play" :label="t('downloads.resume')" @click="run('resume')" />
      <IconButton v-if="job.state === 'failed' || job.state === 'cancelled'" :icon="icons.RotateCcw" :label="`${t('downloads.restart')} (${t('downloads.restartFromZero')})`" @click="run('restart')" />
      <IconButton v-if="job.state === 'completed'" :icon="icons.FolderOpen" :label="t('downloads.openFolder')" @click="openFolder" />
      <IconButton v-if="job.state === 'running' || job.state === 'queued' || job.state === 'paused'" :icon="icons.X" :label="t('downloads.cancel')" @click="run('cancel')" />
      <IconButton v-else :icon="icons.Trash2" :label="t('downloads.remove')" @click="remove.mutate(job.id)" />
    </div>
  </article>
</template>

<style scoped>
.item { display: flex; gap: var(--app-space-3); padding: var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); }
.state-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 50%; flex: none; background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); }
.completed .state-icon { background: var(--md-sys-color-primary-container); color: var(--md-sys-color-on-primary-container); }
.failed .state-icon { background: var(--md-sys-color-error-container); color: var(--md-sys-color-on-error-container); }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: var(--app-space-1); }
.title { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub, .error { margin: 0; }
.error { color: var(--md-sys-color-error); overflow-wrap: anywhere; }
.bar { margin-top: var(--app-space-1); }
.actions { display: flex; align-items: flex-start; }
</style>
