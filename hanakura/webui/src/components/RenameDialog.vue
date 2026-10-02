<script setup lang="ts">
import { ref, watch } from 'vue';
import { useI18n } from '@/i18n';
import { AppButton, AppDialog, TextField } from '@/ui';

/** Rename a model; every companion file follows the new stem. */
const props = defineProps<{ name: string; isFile?: boolean; loading?: boolean; error?: string | null }>();
const open = defineModel<boolean>('open', { default: false });
const emit = defineEmits<{ confirm: [string] }>();
const { t } = useI18n();
const value = ref('');
watch(open, (v) => {
  // A model file keeps its extension; only the stem is edited.
  if (v) value.value = props.isFile ? props.name.replace(/\.[^./]+$/, '') : props.name;
});
const submit = () => value.value.trim() && emit('confirm', value.value.trim());
</script>

<template>
  <AppDialog v-model:open="open" :title="t('common.rename')" width="small">
    <TextField v-model="value" :label="t('library.newName')" :supporting-text="name" :error-text="error ?? undefined" @enter="submit" />
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.cancel') }}</AppButton>
      <AppButton :loading="loading" :disabled="!value.trim()" @click="submit">{{ t('common.rename') }}</AppButton>
    </template>
  </AppDialog>
</template>
