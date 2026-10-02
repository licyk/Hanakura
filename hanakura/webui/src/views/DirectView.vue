<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMeta } from '@/api/queries/app';
import { useCreateDownload } from '@/api/queries/downloads';
import DestinationPicker, { type Destination } from '@/components/DestinationPicker.vue';
import { useI18n } from '@/i18n';
import { useDownloadsStore } from '@/stores/downloads';
import { AppButton, AppIcon, SelectField, Surface, TextField, icons, useSnackbar } from '@/ui';

/** Download any http(s) link by hand, into a folder chosen by hand. */
const { t, kindLabel } = useI18n();
const meta = useMeta();
const downloads = useDownloadsStore();
const snackbar = useSnackbar();
const create = useCreateDownload();

const url = ref('');
const fileName = ref('');
const sha256 = ref('');
const kind = ref<string | null>(null);
const pickerOpen = ref(false);

const kindOptions = computed(() => [{ value: '', label: t('direct.noKind') }, ...(meta.data.value?.kinds ?? []).map((k) => ({ value: k, label: kindLabel(k) }))]);

const urlError = computed(() => (!url.value.trim() || /^https?:\/\/\S+$/i.test(url.value.trim()) ? '' : t('direct.urlInvalid')));
const shaError = computed(() => (!sha256.value.trim() || /^[0-9a-fA-F]{64}$/.test(sha256.value.trim()) ? '' : t('direct.sha256Invalid')));
const ready = computed(() => !!url.value.trim() && !urlError.value && !shaError.value);

/** The name the server would take from the link when the user gives none. */
const urlName = computed(() => {
  try {
    return decodeURIComponent(new URL(url.value.trim()).pathname.split('/').filter(Boolean).pop() ?? '');
  } catch {
    return '';
  }
});
const label = computed(() => fileName.value.trim() || urlName.value || null);

function queue(dest: Destination) {
  create.mutate(
    {
      url: url.value.trim(),
      file_name: fileName.value.trim() || null,
      expected_sha256: sha256.value.trim() || null,
      title: label.value,
      ...dest,
    },
    {
      onSuccess: (job) => {
        pickerOpen.value = false;
        url.value = '';
        fileName.value = '';
        sha256.value = '';
        snackbar.show(t('browse.queued', { name: job.title }), { actionLabel: t('browse.openDownloads'), action: () => (downloads.drawerOpen = true) });
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}
</script>

<template>
  <div class="direct">
    <Surface :level="0" shape="large" class="section">
      <h2 class="type-title-large">{{ t('direct.title') }}</h2>
      <p class="type-body-medium muted intro">{{ t('direct.intro') }}</p>
      <div class="fields">
        <TextField
          v-model="url"
          type="url"
          :label="t('direct.url')"
          :placeholder="t('direct.urlPlaceholder')"
          :icon="icons.Link"
          :supporting-text="t('direct.urlHelp')"
          :error-text="urlError || undefined"
          autocomplete="off"
          @enter="ready && (pickerOpen = true)"
        />
        <TextField
          v-model="fileName"
          :label="t('direct.fileName')"
          :placeholder="urlName || undefined"
          :icon="icons.File"
          :supporting-text="t('direct.fileNameHelp')"
          autocomplete="off"
          @enter="ready && (pickerOpen = true)"
        />
        <TextField
          v-model="sha256"
          :label="t('direct.sha256')"
          :icon="icons.Fingerprint"
          :supporting-text="t('direct.sha256Help')"
          :error-text="shaError || undefined"
          autocomplete="off"
          @enter="ready && (pickerOpen = true)"
        />
        <SelectField v-model="kind" :label="t('direct.kind')" :options="kindOptions" :supporting-text="t('direct.kindHelp')" />
      </div>
      <p class="type-body-small muted note"><AppIcon :icon="icons.Info" :size="18" /> {{ t('direct.note') }}</p>
      <div class="actions">
        <AppButton :icon="icons.Download" :disabled="!ready" @click="pickerOpen = true">{{ t('direct.choose') }}</AppButton>
      </div>
    </Surface>

    <DestinationPicker v-model:open="pickerOpen" :kind="kind" :file-label="label" :loading="create.isPending.value" @confirm="queue" />
  </div>
</template>

<style scoped>
.direct { display: flex; flex-direction: column; gap: var(--app-space-4); padding: var(--app-space-4) var(--app-space-6) var(--app-space-8); }
.section { display: flex; flex-direction: column; gap: var(--app-space-3); padding: var(--app-space-4) var(--app-space-6) var(--app-space-6); }
h2 { margin: 0; }
p { margin: 0; }
.intro { margin-bottom: var(--app-space-2); }
/* The form fills the window: one column when narrow, more as the width allows. */
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: var(--app-space-3); align-items: start; }
.fields > :first-child { grid-column: 1 / -1; }
.note { display: flex; align-items: center; gap: var(--app-space-1); }
.actions { display: flex; justify-content: flex-end; }
@media (max-width: 599px) {
  .direct { padding: var(--app-space-3); }
  .section { padding: var(--app-space-4); }
}
</style>
