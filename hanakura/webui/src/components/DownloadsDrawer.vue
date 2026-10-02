<script setup lang="ts">
import { computed } from 'vue';
import { useClearFinished, useDownloads } from '@/api/queries/downloads';
import DownloadItem from '@/components/DownloadItem.vue';
import { formatBytes } from '@/format';
import { useI18n } from '@/i18n';
import { useDownloadsStore } from '@/stores/downloads';
import { useUploadsStore } from '@/stores/uploads';
import { AppButton, AppIcon, EmptyState, IconButton, ProgressBar, SideSheet, icons } from '@/ui';

/** All jobs with progress, speed, and pause, resume and cancel; plus uploads from drag and drop. */
const { t } = useI18n();
const store = useDownloadsStore();
const uploads = useUploadsStore();
const jobs = useDownloads();
const clear = useClearFinished();
const hasFinished = computed(() => (jobs.data.value ?? []).some((j) => j.state === 'completed' || j.state === 'cancelled') || uploads.items.some((u) => u.state === 'done' || u.state === 'cancelled' || u.state === 'failed'));

function clearAll() {
  clear.mutate();
  uploads.clearFinished();
}
</script>

<template>
  <SideSheet v-model:open="store.drawerOpen" :title="t('downloads.title')" :close-label="t('common.close')">
    <template #header-actions>
      <AppButton v-if="hasFinished" variant="text" @click="clearAll">{{ t('downloads.clearFinished') }}</AppButton>
    </template>

    <section v-if="uploads.items.length" class="group">
      <h3 class="type-title-small muted">{{ t('downloads.uploads') }}</h3>
      <TransitionGroup name="list" tag="div" class="list">
        <article v-for="u in uploads.items" :key="`u${u.id}`" class="upload">
          <AppIcon :icon="icons.Upload" :size="20" />
          <div class="main">
            <span class="type-title-small name" :title="u.name">{{ u.name }}</span>
            <span class="type-body-small muted">{{ t(`downloads.states.${u.state}`) }} · {{ formatBytes(u.loaded) }} / {{ formatBytes(u.size) }}</span>
            <ProgressBar v-if="u.state === 'uploading' || u.state === 'queued'" :value="u.size ? u.loaded / u.size : null" />
            <span v-if="u.error" class="type-body-small error">{{ u.error }}</span>
          </div>
          <IconButton v-if="u.state === 'uploading' || u.state === 'queued'" :icon="icons.X" :label="t('downloads.cancel')" @click="uploads.cancel(u.id)" />
        </article>
      </TransitionGroup>
    </section>

    <section class="group">
      <h3 v-if="uploads.items.length" class="type-title-small muted">{{ t('downloads.title') }}</h3>
      <EmptyState v-if="!jobs.data.value?.length && !uploads.items.length" :icon="icons.Download" :title="t('downloads.emptyTitle')" :text="t('downloads.emptyText')" />
      <TransitionGroup name="list" tag="div" class="list">
        <DownloadItem v-for="job in jobs.data.value ?? []" :key="job.id" :job="job" />
      </TransitionGroup>
    </section>
  </SideSheet>
</template>

<style scoped>
.group { display: flex; flex-direction: column; gap: var(--app-space-2); margin-bottom: var(--app-space-4); }
.group h3 { margin: 0; }
.list { position: relative; display: flex; flex-direction: column; gap: var(--app-space-2); }
.upload { display: flex; align-items: flex-start; gap: var(--app-space-3); padding: var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: var(--app-space-1); }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.error { color: var(--md-sys-color-error); }
</style>
