<script setup lang="ts">
import { computed, ref } from 'vue';
import type { RepoFile } from '@/api/types';
import { formatBytes } from '@/format';
import { useI18n } from '@/i18n';
import { AppButton, AppIcon, Checkbox, collapseHooks, icons } from '@/ui';

/** The file tree of a hub repository, with checkboxes and pattern presets. v-model is the set of selected paths. */
const props = defineProps<{ files: RepoFile[] }>();
const selected = defineModel<string[]>({ default: () => [] });
const { t } = useI18n();

interface Dir {
  name: string;
  path: string;
  dirs: Dir[];
  files: RepoFile[];
}

const root = computed<Dir>(() => {
  const top: Dir = { name: '', path: '', dirs: [], files: [] };
  for (const f of props.files) {
    const parts = f.path.split('/');
    let node = top;
    for (let i = 0; i < parts.length - 1; i++) {
      const path = parts.slice(0, i + 1).join('/');
      let child = node.dirs.find((d) => d.path === path);
      if (!child) {
        child = { name: parts[i], path, dirs: [], files: [] };
        node.dirs.push(child);
      }
      node = child;
    }
    node.files.push(f);
  }
  return top;
});

const collapsed = ref(new Set<string>());
const flat = computed(() => {
  const rows: { type: 'dir' | 'file'; depth: number; dir?: Dir; file?: RepoFile }[] = [];
  const walk = (d: Dir, depth: number) => {
    for (const sub of d.dirs) {
      rows.push({ type: 'dir', depth, dir: sub });
      if (!collapsed.value.has(sub.path)) walk(sub, depth + 1);
    }
    for (const f of d.files) rows.push({ type: 'file', depth, file: f });
  };
  walk(root.value, 0);
  return rows;
});

const set = computed(() => new Set(selected.value));
const filesUnder = (d: Dir): string[] => [...d.files.map((f) => f.path), ...d.dirs.flatMap(filesUnder)];
const dirState = (d: Dir) => {
  const all = filesUnder(d);
  const n = all.filter((p) => set.value.has(p)).length;
  return { checked: n > 0 && n === all.length, indeterminate: n > 0 && n < all.length };
};

function toggleFile(path: string, on: boolean) {
  const next = new Set(selected.value);
  if (on) next.add(path);
  else next.delete(path);
  selected.value = [...next];
}
function toggleDir(d: Dir, on: boolean) {
  const next = new Set(selected.value);
  for (const p of filesUnder(d)) {
    if (on) next.add(p);
    else next.delete(p);
  }
  selected.value = [...next];
}
function toggleCollapse(path: string) {
  const next = new Set(collapsed.value);
  if (next.has(path)) next.delete(path);
  else next.add(path);
  collapsed.value = next;
}

const presets = {
  all: () => (selected.value = props.files.map((f) => f.path)),
  safetensors: () => (selected.value = props.files.filter((f) => f.path.endsWith('.safetensors')).map((f) => f.path)),
  none: () => (selected.value = []),
};
const totalSize = computed(() => props.files.filter((f) => set.value.has(f.path)).reduce((a, f) => a + (f.size ?? 0), 0));
defineExpose({ totalSize });
</script>

<template>
  <div class="repo-tree">
    <div class="presets">
      <AppButton variant="outlined" @click="presets.all">{{ t('hubs.presetAll') }}</AppButton>
      <AppButton variant="outlined" @click="presets.safetensors">{{ t('hubs.presetSafetensors') }}</AppButton>
      <AppButton variant="text" @click="presets.none">{{ t('hubs.presetNone') }}</AppButton>
      <span class="type-label-large summary">{{ t('hubs.selectedSummary', { count: selected.length, size: formatBytes(totalSize) }) }}</span>
    </div>
    <div class="rows" role="tree">
      <TransitionGroup name="collapse" v-bind="collapseHooks">
        <div v-for="row in flat" :key="row.type + (row.dir?.path ?? row.file!.path)" class="row" :style="{ paddingInlineStart: `${row.depth * 20}px` }">
          <template v-if="row.type === 'dir'">
            <button type="button" class="chev" @click="toggleCollapse(row.dir!.path)">
              <AppIcon :icon="icons.ChevronRight" :size="18" :class="{ open: !collapsed.has(row.dir!.path) }" class="chevron" />
            </button>
            <Checkbox :model-value="dirState(row.dir!).checked" :indeterminate="dirState(row.dir!).indeterminate" @update:model-value="toggleDir(row.dir!, $event)" />
            <AppIcon :icon="icons.Folder" :size="18" />
            <span class="type-body-medium name">{{ row.dir!.name }}</span>
          </template>
          <template v-else>
            <span class="chev" />
            <Checkbox :model-value="set.has(row.file!.path)" @update:model-value="toggleFile(row.file!.path, $event)" />
            <AppIcon :icon="icons.File" :size="18" />
            <span class="type-body-medium name" :title="row.file!.path">{{ row.file!.path.split('/').pop() }}</span>
            <span class="type-body-small muted size">{{ formatBytes(row.file!.size) }}</span>
          </template>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.repo-tree { display: flex; flex-direction: column; gap: var(--app-space-2); }
.presets { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2); }
.summary { margin-left: auto; color: var(--md-sys-color-on-surface-variant); }
.rows { max-height: 420px; overflow: auto; border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); padding: var(--app-space-1) var(--app-space-2); }
.row { display: flex; align-items: center; gap: var(--app-space-1); min-height: 40px; }
.chev { display: grid; place-items: center; width: 24px; height: 24px; border: 0; background: transparent; color: inherit; cursor: pointer; padding: 0; flex: none; }
.chevron { transition: transform var(--md-sys-motion-duration-short4) var(--md-sys-motion-easing-standard); }
.chevron.open { transform: rotate(90deg); }
.name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.size { flex: none; }
</style>
