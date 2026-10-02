<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { useMeta } from '@/api/queries/app';
import type { RootInfo } from '@/api/types';
import { useI18n } from '@/i18n';
import { AppButton, AppDialog, PathField, SegmentedButton, SelectField, TextField } from '@/ui';

type Layout = 'comfyui' | 'sd-webui' | 'custom';

/** Add or edit a model root: a folder plus a layout preset. */
const props = defineProps<{ root?: RootInfo | null; loading?: boolean; error?: string | null }>();
const open = defineModel<boolean>('open', { default: false });
const emit = defineEmits<{ confirm: [{ name: string | null; path: string; layout: Layout; kind: string | null }] }>();
const { t } = useI18n();
const meta = useMeta();
const kindOptions = computed(() => [
  { value: '', label: t('library.noKindHint') },
  ...[...new Set([...(meta.data.value?.kinds ?? []), ...(props.root?.kind ? [props.root.kind] : [])])].map((kind) => ({ value: kind, label: t(`kinds.${kind}`) })),
]);
const form = reactive({ name: '', path: '', layout: 'comfyui' as Layout, kind: null as string | null });
watch(open, (v) => {
  if (!v) return;
  form.name = props.root?.name ?? '';
  form.path = props.root?.path ?? '';
  form.layout = (props.root?.layout as Layout) ?? 'comfyui';
  form.kind = props.root?.kind ?? null;
});
const layouts: { value: Layout; label: string }[] = [
  { value: 'comfyui', label: t('library.layouts.comfyui') },
  { value: 'sd-webui', label: 'WebUI' },
  { value: 'custom', label: t('library.layouts.custom') },
];
const submit = () => form.path.trim() && emit('confirm', { name: form.name.trim() || null, path: form.path.trim(), layout: form.layout, kind: form.kind });
</script>

<template>
  <AppDialog v-model:open="open" :title="root ? t('library.editRoot') : t('library.addRoot')" width="small">
    <div class="form">
      <PathField v-model="form.path" :label="t('library.rootPath')" :supporting-text="t('library.rootPathHelp')" :error-text="error ?? undefined" @enter="submit" />
      <TextField v-model="form.name" :label="t('library.rootName')" />
      <SelectField v-model="form.kind" :label="t('library.rootKind')" :supporting-text="t('library.rootKindHelp')" :options="kindOptions" />
      <div class="layout">
        <span class="type-label-large muted">{{ t('library.layout') }}</span>
        <SegmentedButton v-model="form.layout" :options="layouts" />
      </div>
    </div>
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.cancel') }}</AppButton>
      <AppButton :loading="loading" :disabled="!form.path.trim()" @click="submit">{{ t('common.save') }}</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--app-space-3); }
.layout { display: flex; flex-direction: column; gap: var(--app-space-2); }
</style>
