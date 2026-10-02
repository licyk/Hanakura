<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { api, unwrap } from '@/api/client';
import { useRoots } from '@/api/queries/library';
import { useI18n } from '@/i18n';
import { AppButton, AppDialog, Checkbox, PathField, SelectField, TextField } from '@/ui';

export interface Destination {
  root_id?: string | null;
  rel_dir?: string | null;
  dest_dir?: string | null;
  overwrite: boolean;
}

/** Root and folder chooser, defaulting to the layout's folder for the model's kind. */
const props = defineProps<{ kind?: string | null; fileLabel?: string | null; loading?: boolean; defaultSubfolder?: string | null }>();
const open = defineModel<boolean>('open', { default: false });
const emit = defineEmits<{ confirm: [Destination] }>();
const { t } = useI18n();
const roots = useRoots();

const rootId = ref<string | null>(null);
const relDir = ref('');
const absolute = ref('');
const overwrite = ref(false);
const suggesting = ref(false);
const error = ref('');
let requestId = 0;
const edited = ref(false);
onBeforeUnmount(() => requestId++);

const rootOptions = computed(() => [...(roots.data.value ?? []).map((r) => ({ value: r.id, label: r.name })), { value: '__abs__', label: t('dest.absolute') }]);
watch([open, () => props.kind], () => {
  requestId++;
  rootId.value = null;
  relDir.value = '';
  edited.value = false;
  error.value = '';
  overwrite.value = false;
}, { immediate: true });

watch([open, rootId, () => props.kind, () => roots.data.value], async () => {
  const id = ++requestId;
  suggesting.value = false;
  error.value = '';
  if (!open.value || !roots.data.value || rootId.value === '__abs__') return;
  if (!roots.data.value.length) {
    rootId.value = '__abs__';
    return;
  }
  suggesting.value = true;
  try {
    const destination = await unwrap(api.GET('/api/v1/library/destination', {
      params: { query: { kind: props.kind ?? undefined, root_id: rootId.value ?? undefined } },
    }));
    if (id !== requestId) return;
    rootId.value = destination.root_id;
    if (!edited.value) relDir.value = [destination.rel_dir, props.defaultSubfolder].filter(Boolean).join('/');
  } catch (e) {
    if (id === requestId) error.value = e instanceof Error ? e.message : String(e);
  } finally {
    if (id === requestId) suggesting.value = false;
  }
}, { immediate: true });

function chooseRoot(value: string | null) {
  edited.value = false;
  rootId.value = value;
}

function confirm() {
  if (!canConfirm.value) return;
  if (rootId.value === '__abs__') emit('confirm', { dest_dir: absolute.value.trim(), overwrite: overwrite.value });
  else emit('confirm', { root_id: rootId.value, rel_dir: relDir.value.trim(), overwrite: overwrite.value });
}

const canConfirm = computed(() => !!rootId.value && !error.value && !suggesting.value && !props.loading && (rootId.value !== '__abs__' || !!absolute.value.trim()));
</script>

<template>
  <AppDialog v-model:open="open" :title="t('dest.title')" width="small">
    <div class="form">
      <p v-if="fileLabel" class="type-body-medium muted file">{{ t('dest.fileName') }}: {{ fileLabel }}</p>
      <p v-if="!roots.data.value?.length" class="type-body-medium muted">{{ t('dest.noRoots') }}</p>
      <SelectField :model-value="rootId" :label="t('dest.root')" :options="rootOptions" @update:model-value="chooseRoot" />
      <PathField v-if="rootId === '__abs__'" v-model="absolute" :label="t('dest.absolute')" />
      <TextField v-else v-model="relDir" :label="t('dest.folder')" :supporting-text="t('dest.folderHelp')" :error-text="error || undefined" @update:model-value="edited = true" @enter="confirm" />
      <Checkbox v-model="overwrite" :label="t('dest.overwrite')" />
      <slot />
    </div>
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.cancel') }}</AppButton>
      <AppButton :loading="loading || suggesting" :disabled="!canConfirm" @click="confirm">{{ t('dest.queue') }}</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--app-space-3); }
.file { margin: 0; word-break: break-all; }
</style>
