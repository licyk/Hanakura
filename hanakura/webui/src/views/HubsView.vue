<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useCreateDownload } from '@/api/queries/downloads';
import { useHubs, useRepo, useRepoSearch } from '@/api/queries/hubs';
import DestinationPicker, { type Destination } from '@/components/DestinationPicker.vue';
import MarkdownContent from '@/components/MarkdownContent.vue';
import ModelGrid from '@/components/ModelGrid.vue';
import RepoFileTree from '@/components/RepoFileTree.vue';
import { formatBytes, formatCount, formatDate } from '@/format';
import { useI18n } from '@/i18n';
import { useDownloadsStore } from '@/stores/downloads';
import { usePreferencesStore } from '@/stores/preferences';
import { AppButton, AppIcon, Badge, EmptyState, ExpansionPanel, IconButton, SearchField, SelectField, Skeleton, Tabs, TextField, icons, useSnackbar } from '@/ui';

const { t, locale } = useI18n();
const prefs = usePreferencesStore();
const downloads = useDownloadsStore();
const snackbar = useSnackbar();
const hubs = useHubs();

type HubId = 'huggingface' | 'modelscope';
const hub = ref<HubId>((prefs.prefs.lastHub as HubId) ?? 'huggingface');
const direction = ref(1);
watch(hub, (h, old) => {
  prefs.prefs.lastHub = h;
  direction.value = h === 'modelscope' && old === 'huggingface' ? 1 : -1;
  repoId.value = null;
});
const hubTabs = computed(() => (hubs.data.value ?? [{ id: 'huggingface', name: 'Hugging Face' }, { id: 'modelscope', name: 'ModelScope' }]).map((h) => ({ value: h.id as HubId, label: h.name })));
const hubInfo = computed(() => hubs.data.value?.find((h) => h.id === hub.value));

const draft = ref('');
const query = ref('');
const sort = ref<string | null>(null);
const sortOptions = computed(() => (hubInfo.value?.sorts ?? []).map((s) => ({ value: s, label: s })));
const search = useRepoSearch(hub, query, sort);
const items = computed(() => search.data.value?.pages.flatMap((p) => p.items) ?? []);

// Opening a repository
const repoId = ref<string | null>(null);
// The pane slides in from the right and back out the same way, and its column stays until it is
// gone, so the list widens once the pane has left rather than under it.
const paneDir = ref(1);
const paneLeaving = ref(false);
const revision = ref<string | null>(null);
const revisionDraft = ref('');
const repo = useRepo(hub, repoId, revision);
const selection = ref<string[]>([]);
const direct = ref('');

watch(
  () => repo.data.value,
  (r) => {
    if (!r) return;
    revisionDraft.value = r.revision;
    // Default selection: the whole repository for diffusers folders, else the safetensors files.
    const hasIndex = r.files.some((f) => f.path === 'model_index.json');
    const st = r.files.filter((f) => f.path.endsWith('.safetensors')).map((f) => f.path);
    selection.value = hasIndex || !st.length ? r.files.map((f) => f.path) : st;
  },
);

function openRepo(id: string) {
  paneDir.value = 1;
  revision.value = null;
  repoId.value = id;
}

function closeRepo() {
  paneDir.value = -1;
  repoId.value = null;
}

function openDirect() {
  let text = direct.value.trim().replace(/\/+$/, '');
  const prefixes: [string, HubId][] = [
    ['https://huggingface.co/', 'huggingface'],
    ['https://hf-mirror.com/', 'huggingface'],
    ['https://modelscope.cn/models/', 'modelscope'],
    ['https://www.modelscope.cn/models/', 'modelscope'],
  ];
  let rev: string | null = null;
  for (const [prefix, h] of prefixes) {
    if (text.startsWith(prefix)) {
      hub.value = h;
      text = text.slice(prefix.length);
    }
  }
  const parts = text.split('/');
  if (parts.length < 2) {
    snackbar.error(t('hubs.openById'));
    return;
  }
  if (parts.length >= 4 && ['tree', 'blob', 'resolve', 'files'].includes(parts[2])) rev = parts[3];
  paneDir.value = 1;
  repoId.value = `${parts[0]}/${parts[1]}`;
  revision.value = rev;
}

const selectedSize = computed(() => (repo.data.value?.files ?? []).filter((f) => selection.value.includes(f.path)).reduce((a, f) => a + (f.size ?? 0), 0));
const readme = computed(() => (repo.data.value?.description ?? '').replace(/^---[\s\S]*?---\s*/, '').slice(0, 20000));
// The model card is Markdown with some HTML, rendered through MarkdownContent's sanitiser. It is
// what a repository is about, so it opens expanded for every repository shown.
const readmeOpen = ref(true);
watch(repoId, () => (readmeOpen.value = true));

const pickerOpen = ref(false);
const create = useCreateDownload();

function queue(dest: Destination) {
  const r = repo.data.value;
  if (!r) return;
  const all = selection.value.length === r.files.length;
  create.mutate(
    { hub: { hub: hub.value, repo_id: r.id, revision: revision.value, include: all ? [] : selection.value, exclude: [] }, ...dest },
    {
      onSuccess: () => {
        pickerOpen.value = false;
        snackbar.show(t('browse.queued', { name: r.id }), { actionLabel: t('browse.openDownloads'), action: () => (downloads.drawerOpen = true) });
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}
</script>

<template>
  <div class="hubs">
    <Tabs v-model="hub" :tabs="hubTabs" class="tabs" />
    <Transition name="shared-axis-x" mode="out-in">
      <div :key="hub" class="panes" :class="{ 'has-repo': !!repoId || paneLeaving }" :style="{ '--axis-dir': direction }">
        <section class="list-pane">
          <div class="controls">
            <SearchField v-model="draft" :placeholder="t('hubs.searchPlaceholder')" @search="query = $event" />
            <div class="row">
              <TextField v-model="direct" :label="t('hubs.openById')" :placeholder="t('hubs.openByIdPlaceholder')" :icon="icons.Link" @enter="openDirect" />
              <AppButton variant="tonal" :disabled="!direct.trim()" @click="openDirect">{{ t('hubs.open') }}</AppButton>
            </div>
            <SelectField v-if="sortOptions.length" v-model="sort" :label="t('hubs.sort')" :options="sortOptions" />
          </div>

          <div v-if="search.isPending.value" class="skeletons">
            <Skeleton v-for="i in 8" :key="i" height="64px" shape="medium" />
          </div>
          <EmptyState v-else-if="search.isError.value" :icon="icons.AlertTriangle" :title="t('common.error')" :text="(search.error.value as Error)?.message" />
          <EmptyState v-else-if="!items.length" :icon="icons.Search" :title="t('hubs.emptyTitle')" />
          <ModelGrid v-else :items="items" :item-key="(r) => r.id" layout="list" :has-more="search.hasNextPage.value" :loading-more="search.isFetchingNextPage.value" @load-more="search.fetchNextPage()">
            <template #default="{ item }">
              <button type="button" class="repo-row state-layer" :class="{ active: repoId === item.id }" @click="openRepo(item.id)">
                <AppIcon :icon="icons.Box" :size="24" class="repo-icon" />
                <span class="repo-text">
                  <span class="type-title-small repo-name">{{ item.id }}</span>
                  <span class="type-body-small muted">
                    {{ t('hubs.downloads', { n: formatCount(item.downloads) }) }} · {{ t('hubs.likes', { n: formatCount(item.likes) }) }}<template v-if="item.task"> · {{ item.task }}</template>
                  </span>
                </span>
                <Badge v-if="item.gated" tone="warning" :value="t('hubs.gated')" />
              </button>
            </template>
          </ModelGrid>
        </section>

        <Transition name="shared-axis-x" @before-leave="paneLeaving = true" @after-leave="paneLeaving = false">
        <section v-if="repoId" class="repo-pane" :style="{ '--axis-dir': paneDir }">
          <!-- Keyed on the repository, so picking another one from the list is a fade-through
               rather than a silent swap of everything but the pane. -->
          <Transition name="fade-through" mode="out-in">
          <div :key="repoId" class="repo-content">
          <header class="repo-head">
            <IconButton :icon="icons.ArrowLeft" :label="t('common.close')" class="back" @click="closeRepo" />
            <h2 class="type-title-large repo-title">{{ repoId }}</h2>
            <a v-if="repo.data.value" :href="repo.data.value.page_url" target="_blank" rel="noopener noreferrer" class="ext" :title="t('detail.openPage')">
              <AppIcon :icon="icons.ExternalLink" :size="20" :label="t('detail.openPage')" />
            </a>
          </header>
          <div v-if="repo.isPending.value" class="skeletons">
            <Skeleton height="40px" />
            <Skeleton height="280px" shape="medium" />
          </div>
          <EmptyState v-else-if="repo.isError.value" :icon="icons.AlertTriangle" :title="t('common.error')" :text="(repo.error.value as Error)?.message" />
          <template v-else-if="repo.data.value">
            <p class="type-body-small muted">
              {{ formatDate(repo.data.value.last_modified, locale) }}<template v-if="repo.data.value.license"> · {{ repo.data.value.license }}</template>
              · {{ formatBytes(repo.data.value.total_size) }}
            </p>
            <div class="row">
              <TextField v-model="revisionDraft" :label="t('hubs.revision')" @enter="revision = revisionDraft || null" />
              <AppButton variant="text" :icon="icons.RefreshCw" @click="revision = revisionDraft || null">{{ t('common.refresh') }}</AppButton>
            </div>
            <RepoFileTree v-model="selection" :files="repo.data.value.files" />
            <p class="type-body-small muted note"><AppIcon :icon="icons.Info" :size="18" /> {{ t('hubs.noPause') }}</p>
            <div class="download-row">
              <AppButton :icon="icons.Download" :disabled="!selection.length" @click="pickerOpen = true">
                {{ t('hubs.download') }} ({{ formatBytes(selectedSize) }})
              </AppButton>
            </div>
            <ExpansionPanel v-if="readme" v-model:open="readmeOpen" :label="t('hubs.readme')" :icon="icons.FileText">
              <MarkdownContent :text="readme" class="readme" />
            </ExpansionPanel>
          </template>
          </div>
          </Transition>
        </section>
        </Transition>
      </div>
    </Transition>

    <DestinationPicker v-model:open="pickerOpen" :kind="null" :file-label="repoId" :default-subfolder="repoId?.split('/')[1]" :loading="create.isPending.value" @confirm="queue">
      <p class="type-body-small muted">{{ t('hubs.noPause') }}</p>
    </DestinationPicker>
  </div>
</template>

<style scoped>
.hubs { display: flex; flex-direction: column; height: 100%; }
.tabs { flex: none; border-radius: var(--md-sys-shape-corner-large) var(--md-sys-shape-corner-large) 0 0; overflow: hidden; }
/* Both states declare two tracks so the widths interpolate: the list narrows while the pane
   arrives instead of jumping under it. */
.panes {
  position: relative; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 0fr); column-gap: 0; row-gap: var(--app-space-4);
  flex: 1; min-height: 0; padding: var(--app-space-4) var(--app-space-6);
  transition: grid-template-columns var(--md-sys-motion-duration-medium2) var(--md-sys-motion-easing-emphasized),
    column-gap var(--md-sys-motion-duration-medium2) var(--md-sys-motion-easing-emphasized);
}
.panes.has-repo { grid-template-columns: minmax(280px, 2fr) minmax(0, 3fr); column-gap: var(--app-space-4); }
.list-pane, .repo-pane {
  display: flex; flex-direction: column; gap: var(--app-space-3); min-width: 0; overflow: auto;
  /* Keep the scrollbar off the content, and reserve its width so nothing shifts when it appears. */
  padding-right: var(--app-space-3); scrollbar-gutter: stable;
}
.controls { display: flex; flex-direction: column; gap: var(--app-space-2); }
.row { display: flex; align-items: flex-start; gap: var(--app-space-2); }
.row > :first-child { flex: 1; }
.row :deep(md-filled-tonal-button), .row :deep(md-text-button) { margin-top: var(--app-space-2); }
.skeletons { display: flex; flex-direction: column; gap: var(--app-space-2); }
.repo-row {
  display: flex; align-items: center; gap: var(--app-space-3); width: 100%; padding: var(--app-space-3); border: 0; text-align: left; cursor: pointer; font: inherit;
  border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); color: var(--md-sys-color-on-surface);
}
.repo-row.active { background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); }
.repo-icon { color: var(--md-sys-color-on-surface-variant); }
.repo-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.repo-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.repo-pane { padding: var(--app-space-4); padding-right: var(--app-space-3); border-radius: var(--md-sys-shape-corner-large); background: var(--md-sys-color-surface); }
/* The shared-axis motion takes a leaving element out of flow across the whole width; here it
   leaves inside its own column instead. */
.repo-pane.shared-axis-x-leave-active { position: static; }
.repo-content { display: flex; flex-direction: column; gap: var(--app-space-3); min-width: 0; }
.repo-head { display: flex; align-items: center; gap: var(--app-space-2); }
.repo-title { flex: 1; margin: 0; overflow-wrap: anywhere; }
.ext { color: var(--md-sys-color-primary); display: inline-flex; }
.back { flex: none; }
.note { display: flex; align-items: center; gap: var(--app-space-1); margin: 0; }
.download-row { display: flex; justify-content: flex-end; }
.readme { max-height: 400px; overflow: auto; }
p { margin: 0; }
@media (max-width: 899px) {
  /* The list is hidden here, so the pane is the only item: it must land in the sized track. */
  .panes.has-repo { grid-template-columns: minmax(0, 1fr) minmax(0, 0fr); column-gap: 0; }
  .panes.has-repo .list-pane { display: none; }
}
@media (max-width: 599px) {
  .panes { padding: var(--app-space-3); }
}
</style>
