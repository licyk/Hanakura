<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query';
import { computed, ref, watch } from 'vue';
import { previewUrl, saveFile } from '@/api/client';
import { useMeta } from '@/api/queries/app';
import { keys } from '@/api/queries/keys';
import { fetchModelHash, useModelInfo } from '@/api/queries/library';
import { useIdentify } from '@/api/queries/sources';
import type { IdentifyResult } from '@/api/types';
import PreviewImage from '@/components/PreviewImage.vue';
import { fileExtensionLabel, formatBytes, formatDate } from '@/format';
import { useI18n } from '@/i18n';
import { AppButton, AppDialog, AppIcon, Badge, Divider, Skeleton, icons, useSnackbar } from '@/ui';

/** Detection result, hash, sidecars and a lookup on the sources by hash, for one local model. */
const props = defineProps<{ rootId: string | null; path: string | null; fromRect?: DOMRect | null }>();
const open = defineModel<boolean>('open', { default: false });
const { t, kindLabel, locale } = useI18n();
const qc = useQueryClient();
const snackbar = useSnackbar();
const info = useModelInfo(
  () => (open.value ? props.rootId : null),
  () => props.path,
);
const hashing = ref(false);
const identify = useIdentify();
const results = ref<IdentifyResult[] | null>(null);
watch(open, (v) => v && (results.value = null));

const meta = useMeta();
const baseLabel = (id: string | null | undefined) => (id ? (meta.data.value?.base_models.find((b) => b.value === id)?.label ?? id) : '—');
const entry = computed(() => info.data.value?.entry);
const det = computed(() => entry.value?.detection);

async function computeHash() {
  if (!props.rootId || !props.path) return;
  hashing.value = true;
  try {
    await fetchModelHash(props.rootId, props.path);
    await qc.invalidateQueries({ queryKey: keys.modelInfo(props.rootId, props.path) });
  } catch (e) {
    snackbar.error((e as Error).message);
  } finally {
    hashing.value = false;
  }
}

async function lookup() {
  if (!props.rootId || !props.path) return;
  hashing.value = true;
  try {
    const sha = info.data.value?.sha256 ?? (await fetchModelHash(props.rootId, props.path));
    if (!sha) return;
    await qc.invalidateQueries({ queryKey: keys.modelInfo(props.rootId, props.path) });
    results.value = await identify.mutateAsync(sha);
  } catch (e) {
    snackbar.error((e as Error).message);
  } finally {
    hashing.value = false;
  }
}

const rows = computed(() => {
  const e = entry.value;
  if (!e) return [];
  const common = [
    [t('info.path'), e.path],
    [t('info.size'), formatBytes(e.size)],
    [t('info.modified'), formatDate(e.mtime, locale.value)],
  ];
  // A plain file was never detected, so the detection rows would all read "—".
  if (!e.is_model) return [...common, [t('info.kind'), fileExtensionLabel(e.name) ?? t('library.file')]];
  return [
    ...common,
    [t('info.kind'), kindLabel(det.value?.kind)],
    [t('info.base'), baseLabel(det.value?.base_model)],
    [t('info.prediction'), det.value?.prediction_type ?? '—'],
    [t('info.confidence'), det.value ? `${Math.round(det.value.confidence * 100)}%` : '—'],
    [t('info.rule'), det.value?.rule_id ?? '—'],
    [t('info.folderKind'), e.folder_kind ? kindLabel(e.folder_kind) : '—'],
    [t('info.sidecar'), e.sidecar ? `${e.sidecar.source}: ${e.sidecar.kind ? kindLabel(e.sidecar.kind) : '—'} / ${baseLabel(e.sidecar.base_model)}` : '—'],
  ];
});
</script>

<template>
  <AppDialog v-model:open="open" :title="entry?.name ?? path ?? ''" :from-rect="fromRect" width="large" :close-label="t('common.close')">
    <div v-if="info.isPending.value" class="loading"><Skeleton height="200px" /><Skeleton width="60%" /></div>
    <p v-else-if="info.error.value" class="error">{{ (info.error.value as Error).message }}</p>
    <div v-else-if="entry" class="layout">
      <div class="preview">
        <PreviewImage :src="entry.preview && rootId ? previewUrl(rootId, entry.preview, 768) : null" :alt="entry.name" />
      </div>
      <div class="facts">
        <div v-if="entry.mismatch" class="warning type-body-medium">
          <AppIcon :icon="icons.AlertTriangle" :size="20" />
          <span><strong>{{ t('library.mismatch') }}.</strong> {{ t('library.mismatchText') }}</span>
        </div>
        <dl class="table">
          <template v-for="[k, v] in rows" :key="k">
            <dt class="type-label-large muted">{{ k }}</dt>
            <dd class="type-body-medium">{{ v }}</dd>
          </template>
          <dt class="type-label-large muted">{{ t('info.sha256') }}</dt>
          <dd class="type-body-medium mono">
            <template v-if="info.data.value?.sha256">{{ info.data.value.sha256 }}</template>
            <AppButton v-else-if="!entry.is_dir" variant="text" :icon="icons.Hash" :loading="hashing" @click="computeHash">{{ t('info.computeHash') }}</AppButton>
            <template v-else>—</template>
          </dd>
        </dl>
        <div v-if="!entry.is_dir" class="actions">
          <!-- No source knows a plain file, so asking one about it only wastes a hash. -->
          <AppButton v-if="entry.is_model" variant="tonal" :icon="icons.Fingerprint" :loading="hashing || identify.isPending.value" @click="lookup">{{ t('library.identify') }}</AppButton>
          <AppButton variant="text" :icon="icons.Download" @click="rootId && saveFile(rootId, entry.path)">{{ t('library.download') }}</AppButton>
        </div>
        <div v-if="results" class="results">
          <p v-if="!results.length" class="type-body-medium muted">{{ t('library.identifyNone') }}</p>
          <a v-for="r in results" :key="r.source + r.model.id" class="result" :href="r.model.page_url ?? undefined" target="_blank" rel="noopener noreferrer">
            <Badge tone="primary" :value="r.source" />
            <span class="type-title-small">{{ r.model.name }}</span>
            <span v-if="r.model.base_model_label" class="type-body-small muted">{{ r.model.base_model_label }}</span>
            <AppIcon :icon="icons.ExternalLink" :size="18" />
          </a>
        </div>
      </div>
    </div>
    <template v-if="info.data.value">
      <Divider class="divider" />
      <section v-if="info.data.value.webui && Object.keys(info.data.value.webui).length" class="section">
        <h3 class="type-title-small">{{ t('info.webui') }}</h3>
        <dl class="table">
          <template v-for="(v, k) in info.data.value.webui" :key="k">
            <dt class="type-label-large muted">{{ k }}</dt>
            <dd class="type-body-medium">{{ v }}</dd>
          </template>
        </dl>
      </section>
      <section v-if="info.data.value.sdmodelhub" class="section">
        <h3 class="type-title-small">{{ t('info.source') }}</h3>
        <p class="type-body-medium">
          {{ info.data.value.sdmodelhub.name ?? info.data.value.sdmodelhub.url }}
          <template v-if="info.data.value.sdmodelhub.version_name"> · {{ info.data.value.sdmodelhub.version_name }}</template>
          <a v-if="info.data.value.sdmodelhub.page_url" :href="String(info.data.value.sdmodelhub.page_url)" target="_blank" rel="noopener noreferrer" class="link">{{ t('detail.openPage') }}</a>
        </p>
        <p v-if="(info.data.value.sdmodelhub.trained_words as string[] | undefined)?.length" class="type-body-medium">
          {{ t('detail.triggerWords') }}: {{ (info.data.value.sdmodelhub.trained_words as string[]).join(', ') }}
        </p>
      </section>
      <section v-if="info.data.value.description" class="section">
        <h3 class="type-title-small">{{ t('detail.description') }}</h3>
        <p class="type-body-medium pre">{{ info.data.value.description }}</p>
      </section>
      <section v-if="Object.keys(info.data.value.header_metadata).length" class="section">
        <h3 class="type-title-small">{{ t('info.metadata') }}</h3>
        <dl class="table">
          <template v-for="(v, k) in info.data.value.header_metadata" :key="k">
            <dt class="type-label-large muted">{{ k }}</dt>
            <dd class="type-body-medium">{{ String(v).slice(0, 300) }}</dd>
          </template>
        </dl>
      </section>
      <section v-if="entry?.companions.length" class="section">
        <h3 class="type-title-small">{{ t('info.companions') }}</h3>
        <p class="type-body-medium muted">{{ entry.companions.join(', ') }}</p>
      </section>
    </template>
  </AppDialog>
</template>

<style scoped>
.loading { display: flex; flex-direction: column; gap: var(--app-space-2); }
.layout { display: grid; grid-template-columns: minmax(0, 220px) minmax(0, 1fr); gap: var(--app-space-4); align-items: start; }
.preview { border-radius: var(--md-sys-shape-corner-medium); overflow: hidden; }
.facts { display: flex; flex-direction: column; gap: var(--app-space-3); min-width: 0; }
.warning { display: flex; gap: var(--app-space-2); align-items: flex-start; padding: var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-error-container); color: var(--md-sys-color-on-error-container); }
/* Header metadata brings keys of any length: the label column may shrink and wrap rather than
   push the value column out of the dialog. */
.table { display: grid; grid-template-columns: minmax(0, max-content) minmax(0, 1fr); gap: var(--app-space-1) var(--app-space-4); margin: 0; }
dt { overflow-wrap: anywhere; }
dd { margin: 0; overflow-wrap: anywhere; }
.mono { font-family: ui-monospace, monospace; font-size: var(--md-sys-typescale-body-small-size); }
.actions { display: flex; flex-wrap: wrap; gap: var(--app-space-2); }
.results { display: flex; flex-direction: column; gap: var(--app-space-2); }
.result { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2); padding: var(--app-space-2) var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); color: inherit; text-decoration: none; }
.result > span { min-width: 0; overflow-wrap: anywhere; }
.divider { margin: var(--app-space-4) 0; }
.section { margin-bottom: var(--app-space-4); }
.section h3 { margin: 0 0 var(--app-space-2); }
.section p { margin: 0 0 var(--app-space-1); }
.pre { white-space: pre-line; }
.link { margin-left: var(--app-space-2); color: var(--md-sys-color-primary); }
.error { color: var(--md-sys-color-error); }
@media (max-width: 599px) {
  .layout { grid-template-columns: minmax(0, 1fr); }
  .preview { max-width: 240px; margin-inline: auto; }
  /* Two columns leave nothing for a path or a hash: label over value instead. */
  .table { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .table dt { margin-top: var(--app-space-2); }
  .table dt:first-child { margin-top: 0; }
}
</style>
