<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoots, useTree } from '@/api/queries/library';
import FolderTree from '@/components/FolderTree.vue';
import { useI18n } from '@/i18n';
import { AppButton, AppDialog, SelectField } from '@/ui';

/** Pick a destination folder in any root. */
const props = defineProps<{ count: number; rootId: string | null; loading?: boolean }>();
const open = defineModel<boolean>('open', { default: false });
const emit = defineEmits<{ confirm: [{ rootId: string; dir: string }] }>();
const { t } = useI18n();
const roots = useRoots();
const target = ref<string | null>(null);
const dir = ref('');
const tree = useTree(target);
watch(open, (v) => {
  if (v) {
    target.value = props.rootId;
    dir.value = '';
  }
});
const rootOptions = computed(() => (roots.data.value ?? []).map((r) => ({ value: r.id, label: r.name })));
</script>

<template>
  <AppDialog v-model:open="open" :title="`${t('library.moveTo')} (${count})`" width="small">
    <div class="form">
      <SelectField v-model="target" :label="t('library.root')" :options="rootOptions" @update:model-value="dir = ''" />
      <div class="tree" role="tree">
        <FolderTree v-if="tree.data.value" :node="tree.data.value" :selected="dir" @select="dir = $event" />
      </div>
      <p class="type-body-small muted">{{ dir || '/' }}</p>
    </div>
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.cancel') }}</AppButton>
      <AppButton :loading="loading" :disabled="!target" @click="emit('confirm', { rootId: target!, dir })">{{ t('common.move') }}</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--app-space-3); }
.tree { max-height: 320px; overflow: auto; padding: var(--app-space-1); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); }
p { margin: 0; }
</style>
