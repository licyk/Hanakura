<script setup lang="ts">
import { computed } from 'vue';
import type { SourceInfo } from '@/api/types';
import { useI18n } from '@/i18n';
import { SearchField, SelectField } from '@/ui';

/** Search box, source switch, and the kind, base-model and sort filters the source declares. */
const props = defineProps<{ sources: SourceInfo[] }>();
const source = defineModel<string>('source', { required: true });
const query = defineModel<string>('query', { default: '' });
const kind = defineModel<string | null>('kind', { default: null });
const baseModel = defineModel<string | null>('baseModel', { default: null });
const sort = defineModel<string | null>('sort', { default: null });
const emit = defineEmits<{ search: [string] }>();
const { t } = useI18n();

const caps = computed(() => props.sources.find((s) => s.id === source.value)?.capabilities);
const sourceOptions = computed(() => props.sources.filter((s) => s.enabled).map((s) => ({ value: s.id, label: s.name })));
const kindOptions = computed(() => [{ value: '', label: t('browse.allKinds') }, ...(caps.value?.kinds ?? [])]);
const baseOptions = computed(() => [{ value: '', label: t('browse.allBaseModels') }, ...(caps.value?.base_models ?? [])]);
const sortOptions = computed(() => [{ value: '', label: t('browse.defaultSort') }, ...(caps.value?.sorts ?? [])]);

const optional = (v: string | null) => v || null;
</script>

<template>
  <div class="filter-bar">
    <SearchField v-model="query" class="search" :placeholder="t('browse.searchPlaceholder')" @search="emit('search', $event)" />
    <div class="filters">
      <SelectField v-model="source" :label="t('browse.source')" :options="sourceOptions" />
      <SelectField v-if="(caps?.kinds.length ?? 0) > 1" :model-value="kind ?? ''" :label="t('browse.kind')" :options="kindOptions" @update:model-value="kind = optional($event)" />
      <SelectField v-if="caps?.base_models.length" :model-value="baseModel ?? ''" :label="t('browse.baseModel')" :options="baseOptions" @update:model-value="baseModel = optional($event)" />
      <SelectField v-if="caps?.sorts.length" :model-value="sort ?? ''" :label="t('browse.sort')" :options="sortOptions" @update:model-value="sort = optional($event)" />
    </div>
  </div>
</template>

<style scoped>
.filter-bar { display: flex; flex-direction: column; gap: var(--app-space-3); }
.search { width: 100%; }
.filters { display: flex; flex-wrap: wrap; gap: var(--app-space-2); }
</style>
