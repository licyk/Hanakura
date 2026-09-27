<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query';
import { computed, reactive, ref, watch } from 'vue';
import { api, unwrap } from '@/api/client';
import { useCreateDownload } from '@/api/queries/downloads';
import { keys } from '@/api/queries/keys';
import { useModelSearch, useSources, type SearchParams } from '@/api/queries/sources';
import type { ModelFile, ModelSummary } from '@/api/types';
import DestinationPicker, { type Destination } from '@/components/DestinationPicker.vue';
import FilterBar from '@/components/FilterBar.vue';
import ModelCard from '@/components/ModelCard.vue';
import ModelDetailDialog from '@/components/ModelDetailDialog.vue';
import ModelGrid from '@/components/ModelGrid.vue';
import { formatCount } from '@/format';
import { useI18n } from '@/i18n';
import { useDownloadsStore } from '@/stores/downloads';
import { usePreferencesStore } from '@/stores/preferences';
import { AppButton, EmptyState, IconButton, Skeleton, icons, useSnackbar } from '@/ui';
import { useViewQuery } from '@/viewState';

const { t, kindLabel } = useI18n();
const route = useViewQuery();
const qc = useQueryClient();
const prefs = usePreferencesStore();
const downloads = useDownloadsStore();
const snackbar = useSnackbar();
const sources = useSources();

// The query lives in the URL, so a search can be reloaded and shared.
const str = (v: unknown) => (typeof v === 'string' && v ? v : null);
const source = ref(str(route.query.source) ?? prefs.prefs.lastSource);
const draft = ref(str(route.query.q) ?? '');
const params = reactive<SearchParams>({ query: draft.value, kind: str(route.query.kind), base_model: str(route.query.base), sort: str(route.query.sort) });

watch(source, (s, old) => {
  prefs.prefs.lastSource = s;
  if (old !== undefined) Object.assign(params, { kind: null, base_model: null, sort: null });
});
watch([source, params], () => {
  route.replace({ source: source.value, q: params.query || undefined, kind: params.kind ?? undefined, base: params.base_model ?? undefined, sort: params.sort ?? undefined });
});
// A shared link opened while this view is already showing must move it, not only fill it on first load.
route.onChange((q) => {
  const next = { query: str(q.q) ?? '', kind: str(q.kind), base_model: str(q.base), sort: str(q.sort) };
  if (str(q.source) && str(q.source) !== source.value) source.value = str(q.source)!;
  if (JSON.stringify(next) !== JSON.stringify({ query: params.query, kind: params.kind, base_model: params.base_model, sort: params.sort })) {
    Object.assign(params, next);
    draft.value = next.query;
  }
});
watch(
  () => sources.data.value,
  (list) => {
    if (list?.length && !list.some((s) => s.id === source.value && s.enabled)) source.value = list.find((s) => s.enabled)?.id ?? list[0].id;
  },
);

const search = useModelSearch(source, () => ({ ...params }));
const items = computed(() => search.data.value?.pages.flatMap((p) => p.items) ?? []);
const sourceName = computed(() => sources.data.value?.find((s) => s.id === source.value)?.name ?? source.value);

// Detail dialog
const detailOpen = ref(false);
const detailId = ref<string | null>(null);
const detailRect = ref<DOMRect | null>(null);
function openDetail(item: ModelSummary, rect: DOMRect | null) {
  detailId.value = item.id;
  detailRect.value = rect;
  detailOpen.value = true;
}

// Download flow: pick the file, then the destination.
const pickerOpen = ref(false);
const pending = ref<{ modelId: string; versionId: string; file: ModelFile; kind: string | null; name: string } | null>(null);
const create = useCreateDownload();

async function quickDownload(item: ModelSummary) {
  try {
    const detail = await qc.fetchQuery({
      queryKey: keys.model(source.value, item.id),
      queryFn: () => unwrap(api.GET('/api/v1/sources/{source}/models/{model_id}', { params: { path: { source: source.value, model_id: item.id } } })),
      staleTime: 120_000,
    });
    const version = detail.versions[0];
    const file = version?.files.find((f) => f.primary) ?? version?.files[0];
    if (!version || !file) {
      snackbar.error(t('detail.noFiles'));
      return;
    }
    pending.value = { modelId: item.id, versionId: version.id, file, kind: item.kind ?? null, name: item.name };
    pickerOpen.value = true;
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}

function downloadFromDetail(payload: { file: ModelFile; versionId: string; kind: string | null; name: string }) {
  pending.value = { modelId: detailId.value!, ...payload };
  pickerOpen.value = true;
}

function queue(dest: Destination) {
  const p = pending.value;
  if (!p) return;
  create.mutate(
    { source_file: { source: source.value, model_id: p.modelId, version_id: p.versionId, file_id: p.file.id, file_name: p.file.name }, ...dest },
    {
      onSuccess: () => {
        pickerOpen.value = false;
        if (dest.root_id) prefs.prefs.lastRoot = dest.root_id;
        snackbar.show(t('browse.queued', { name: p.name }), { actionLabel: t('browse.openDownloads'), action: () => (downloads.drawerOpen = true) });
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}
</script>

<template>
  <div class="browse">
    <div class="top">
      <FilterBar
        v-model:source="source"
        v-model:query="draft"
        v-model:kind="params.kind"
        v-model:base-model="params.base_model"
        v-model:sort="params.sort"
        :sources="sources.data.value ?? []"
        @search="params.query = $event"
      />
    </div>

    <div v-if="search.isPending.value" class="skeletons">
      <div v-for="i in 12" :key="i" class="skeleton-card">
        <Skeleton height="240px" shape="medium" />
        <Skeleton width="70%" />
        <Skeleton width="40%" height="12px" />
      </div>
    </div>
    <EmptyState v-else-if="search.isError.value" :icon="icons.AlertTriangle" :title="t('browse.sourceError', { source: sourceName })" :text="(search.error.value as Error)?.message">
      <AppButton variant="tonal" :icon="icons.RefreshCw" @click="search.refetch()">{{ t('common.retry') }}</AppButton>
    </EmptyState>
    <EmptyState v-else-if="!items.length" :icon="icons.Search" :title="t('browse.emptyTitle')" :text="t('browse.emptyText')" />
    <ModelGrid
      v-else
      :items="items"
      :item-key="(m) => m.id"
      :has-more="search.hasNextPage.value"
      :loading-more="search.isFetchingNextPage.value"
      @load-more="search.fetchNextPage()"
    >
      <template #default="{ item }">
        <ModelCard
          :title="item.name"
          :subtitle="[item.creator, item.stats.downloads ? `↓ ${formatCount(item.stats.downloads)}` : null].filter(Boolean).join(' · ')"
          :preview="item.preview_url"
          :preview-is-video="item.preview_is_video"
          :nsfw-level="item.nsfw_level"
          :kind="kindLabel(item.kind)"
          :base="item.base_model_label"
          @activate="openDetail(item, $event)"
        >
          <template #actions>
            <IconButton :icon="icons.Download" :label="t('common.download')" @click="quickDownload(item)" />
            <IconButton :icon="icons.Info" :label="t('browse.viewInfo')" @click="openDetail(item, null)" />
          </template>
        </ModelCard>
      </template>
    </ModelGrid>

    <ModelDetailDialog v-model:open="detailOpen" :source="source" :model-id="detailId" :from-rect="detailRect" @download="downloadFromDetail" />
    <DestinationPicker v-model:open="pickerOpen" :kind="pending?.kind" :file-label="pending?.file.name" :loading="create.isPending.value" @confirm="queue" />
  </div>
</template>

<style scoped>
.browse { display: flex; flex-direction: column; gap: var(--app-space-4); padding: var(--app-space-4) var(--app-space-6) var(--app-space-6); }
.top { position: sticky; top: calc(-1 * var(--app-space-4)); z-index: 5; padding: var(--app-space-4) 0 var(--app-space-2); margin-top: calc(-1 * var(--app-space-4)); background: var(--md-sys-color-surface-container-low); }
.skeletons { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--app-space-3); }
.skeleton-card { display: flex; flex-direction: column; gap: var(--app-space-2); }
@media (max-width: 599px) {
  .browse { padding: var(--app-space-3); }
}
</style>
