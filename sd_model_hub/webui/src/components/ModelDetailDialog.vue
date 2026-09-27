<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useModelDetail } from '@/api/queries/sources';
import type { ModelFile } from '@/api/types';
import MarkdownContent from '@/components/MarkdownContent.vue';
import PreviewImage from '@/components/PreviewImage.vue';
import { formatBytes, formatCount } from '@/format';
import { useI18n } from '@/i18n';
import { AppButton, AppDialog, AppIcon, Badge, Divider, SelectField, Skeleton, icons } from '@/ui';

/** Description, versions, files with size and scan result, trigger words, and a download button per file. */
const props = defineProps<{ source: string | null; modelId: string | null; fromRect?: DOMRect | null }>();
const open = defineModel<boolean>('open', { default: false });
const emit = defineEmits<{ download: [{ file: ModelFile; versionId: string; kind: string | null; name: string }] }>();
const { t, kindLabel } = useI18n();
const detail = useModelDetail(
  () => (open.value ? props.source : null),
  () => props.modelId,
);
const versionId = ref<string | null>(null);
watch(
  () => detail.data.value,
  (d) => (versionId.value = d?.versions[0]?.id ?? null),
);
const version = computed(() => detail.data.value?.versions.find((v) => v.id === versionId.value) ?? detail.data.value?.versions[0]);
const versionOptions = computed(() => (detail.data.value?.versions ?? []).map((v) => ({ value: v.id, label: v.base_model_label ? `${v.name} · ${v.base_model_label}` : v.name })));
const images = computed(() => (version.value?.images.length ? version.value.images : (detail.data.value?.images ?? [])).slice(0, 8));

async function copy(text: string) {
  await navigator.clipboard?.writeText(text);
}
</script>

<template>
  <AppDialog v-model:open="open" :title="detail.data.value?.name ?? ''" :from-rect="fromRect" width="large" :close-label="t('common.close')">
    <div v-if="detail.isPending.value" class="loading">
      <Skeleton height="28px" width="60%" />
      <Skeleton height="200px" />
      <Skeleton height="16px" width="80%" />
    </div>
    <p v-else-if="detail.error.value" class="type-body-medium error">{{ (detail.error.value as Error).message }}</p>
    <div v-else-if="detail.data.value" class="detail">
      <div class="meta">
        <Badge tone="primary" :value="kindLabel(detail.data.value.kind)" />
        <Badge v-if="version?.base_model_label" tone="neutral" :value="version.base_model_label" />
        <span v-if="detail.data.value.creator" class="type-body-medium muted">{{ t('browse.by', { name: detail.data.value.creator }) }}</span>
        <span v-if="detail.data.value.stats.downloads" class="type-body-medium muted">· {{ t('detail.stats', { downloads: formatCount(detail.data.value.stats.downloads) }) }}</span>
        <a v-if="detail.data.value.page_url" :href="detail.data.value.page_url" target="_blank" rel="noopener noreferrer" class="link type-label-large">
          {{ t('detail.openPage') }} <AppIcon :icon="icons.ExternalLink" :size="18" />
        </a>
      </div>

      <div v-if="images.length" class="gallery">
        <div v-for="img in images" :key="img.url" class="shot">
          <PreviewImage :src="img.url" :alt="detail.data.value.name" :nsfw-level="img.nsfw_level" :is-video="img.is_video" />
        </div>
      </div>

      <SelectField v-if="versionOptions.length > 1" v-model="versionId" :label="t('detail.versions')" :options="versionOptions" class="version" />

      <section v-if="version?.trained_words.length">
        <h3 class="type-title-small">{{ t('detail.triggerWords') }}</h3>
        <div class="words">
          <button v-for="w in version.trained_words" :key="w" type="button" class="word type-label-large state-layer" :title="t('common.copy')" @click="copy(w)">
            {{ w }} <AppIcon :icon="icons.Copy" :size="18" />
          </button>
        </div>
      </section>

      <section>
        <h3 class="type-title-small">{{ t('detail.files') }}</h3>
        <p v-if="!version?.files.length" class="type-body-medium muted">{{ t('detail.noFiles') }}</p>
        <ul class="files">
          <li v-for="f in version?.files" :key="f.id" class="file">
            <AppIcon :icon="icons.FileBox" :size="24" class="file-icon" />
            <div class="file-text">
              <span class="type-body-large name">{{ f.name }}</span>
              <span class="type-body-small muted">
                {{ formatBytes(f.size) }}<template v-if="f.kind"> · {{ f.kind }}</template><template v-if="f.format"> · {{ f.format }}</template><template v-if="f.scan_result"> · scan: {{ f.scan_result }}</template>
              </span>
            </div>
            <div class="file-actions">
              <Badge v-if="f.primary" tone="neutral" :value="t('detail.primary')" />
              <AppButton :variant="f.primary ? 'filled' : 'tonal'" :icon="icons.Download" @click="emit('download', { file: f, versionId: version!.id, kind: detail.data.value!.kind ?? null, name: detail.data.value!.name })">
                {{ t('common.download') }}
              </AppButton>
            </div>
          </li>
        </ul>
      </section>

      <template v-if="detail.data.value.description">
        <Divider />
        <section>
          <h3 class="type-title-small">{{ t('detail.description') }}</h3>
          <!-- Civitai sends HTML, GitHub and OpenModelDB send Markdown: the renderer takes both and sanitises the result. -->
          <MarkdownContent :text="detail.data.value.description" class="description" />
        </section>
      </template>
      <p v-if="detail.data.value.license" class="type-body-small muted">{{ t('detail.license') }}: {{ detail.data.value.license }}</p>
    </div>
  </AppDialog>
</template>

<style scoped>
.loading, .detail { display: flex; flex-direction: column; gap: var(--app-space-4); }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2); }
.link { display: inline-flex; align-items: center; gap: var(--app-space-1); color: var(--md-sys-color-primary); text-decoration: none; margin-left: auto; }
.gallery { display: grid; grid-auto-flow: column; grid-auto-columns: clamp(160px, 12vw, 280px); gap: var(--app-space-2); overflow-x: auto; padding-bottom: var(--app-space-1); }
.shot { border-radius: var(--md-sys-shape-corner-medium); overflow: hidden; }
.version { width: min(100%, max(420px, 40%)); }
h3 { margin: 0 0 var(--app-space-2); }
.words { display: flex; flex-wrap: wrap; gap: var(--app-space-2); }
.word {
  display: inline-flex; align-items: center; gap: var(--app-space-1); min-height: 32px; max-width: 100%; padding: var(--app-space-1) var(--app-space-3); cursor: pointer; font: inherit; font-weight: 500;
  text-align: left; overflow-wrap: anywhere;
  border: 1px solid var(--md-sys-color-outline-variant); border-radius: var(--md-sys-shape-corner-small); background: transparent; color: var(--md-sys-color-on-surface-variant);
}
.files { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--app-space-2); }
/* Too narrow for one row — a phone — and the badge and the button drop to a line of their own. */
.file { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2) var(--app-space-3); padding: var(--app-space-2) var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); }
.file-icon { color: var(--md-sys-color-on-surface-variant); flex: none; }
.file-text { flex: 1 1 180px; min-width: 0; display: flex; flex-direction: column; }
.file-actions { display: flex; align-items: center; gap: var(--app-space-2); margin-left: auto; }
.name { overflow-wrap: anywhere; }
.description { max-height: 400px; overflow: auto; }
.error { color: var(--md-sys-color-error); }
@media (max-width: 599px) {
  .gallery { grid-auto-columns: 132px; }
  .link { margin-left: 0; }
  /* The sheet itself scrolls; a second scrolling box inside it fights the touch gesture. */
  .description { max-height: none; overflow: visible; }
}
</style>
