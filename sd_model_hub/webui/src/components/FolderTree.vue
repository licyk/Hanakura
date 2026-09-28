<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useTree } from '@/api/queries/library';
import type { TreeNode } from '@/api/types';
import { carriesRefs } from '@/components/libraryDrag';
import { AppIcon, collapseHooks, icons } from '@/ui';

defineOptions({ name: 'FolderTree' });

/**
 * Library navigation. Nodes on the path to the selected folder open automatically.
 *
 * ``selected`` is null where nothing in this tree is the current folder ("All folders"), and
 * ``open`` sets how the node starts. With ``rootId`` the node stands alone for a folder of that
 * root, and its subfolders come from the root's tree once it is first opened.
 */
const props = withDefaults(defineProps<{ node: TreeNode; selected: string | null; depth?: number; label?: string | null; open?: boolean; rootId?: string | null }>(), {
  depth: 0,
  label: null,
  open: undefined,
  rootId: null,
});
const emit = defineEmits<{ select: [string]; drop: [DragEvent, string] }>();
const isAncestor = (path: string) => props.selected !== null && (path === '' || props.selected === path || props.selected.startsWith(`${path}/`));
const expanded = ref(props.open ?? (props.depth === 0 || isAncestor(props.node.path)));
watch(
  () => props.selected,
  () => {
    if (isAncestor(props.node.path)) expanded.value = true;
  },
);

// Only a standalone node asks for its root's tree: every other node already holds its children.
const rootTree = props.rootId ? useTree(() => props.rootId, expanded) : null;
function find(tree: TreeNode, path: string): TreeNode | null {
  if (!path) return tree;
  let node: TreeNode | undefined = tree;
  for (const name of path.split('/')) node = node?.children.find((c) => c.name === name);
  return node ?? null;
}
const children = computed(() => {
  const tree = rootTree?.data.value;
  return tree ? (find(tree, props.node.path)?.children ?? []) : props.node.children;
});
// Until a standalone node's tree arrives, whether it has subfolders is unknown, so it offers to open.
const dropping = ref(false);
function onDragOver(event: DragEvent) {
  if (!carriesRefs(event)) return;
  event.preventDefault();
  event.dataTransfer!.dropEffect = 'move';
  dropping.value = true;
}
function onDrop(event: DragEvent) {
  dropping.value = false;
  if (!carriesRefs(event)) return;
  event.preventDefault();
  emit('drop', event, props.node.path);
}

const openable = computed(() => children.value.length > 0 || (!!rootTree && !rootTree.data.value && !rootTree.isError.value));
</script>

<template>
  <div class="tree-node" role="treeitem" :aria-expanded="openable ? expanded : undefined" :aria-selected="selected === node.path">
    <div
      class="row state-layer"
      :class="{ active: selected === node.path, dropping }"
      :style="{ paddingInlineStart: `${depth * 12 + 4}px` }"
      @click="emit('select', node.path)"
      @dragover="onDragOver"
      @dragleave="dropping = false"
      @drop="onDrop"
    >
      <button v-if="openable" type="button" class="toggle" :aria-label="expanded ? 'Collapse' : 'Expand'" @click.stop="expanded = !expanded">
        <AppIcon :icon="icons.ChevronRight" :size="18" class="chevron" :class="{ open: expanded }" />
      </button>
      <span v-else class="toggle" />
      <AppIcon :icon="selected === node.path ? icons.FolderOpen : icons.Folder" :size="18" />
      <span class="type-label-large name" :title="node.name">{{ node.name }}</span>
      <span v-if="label" class="label type-label-small" :title="label">{{ label }}</span>
    </div>
    <Transition name="collapse" v-bind="collapseHooks">
      <div v-if="expanded && children.length" role="group">
        <FolderTree v-for="child in children" :key="child.path" :node="child" :selected="selected" :depth="depth + 1" @select="emit('select', $event)" @drop="(e, p) => emit('drop', e, p)" />
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.row {
  display: flex; align-items: center; gap: var(--app-space-1); height: 36px; padding-right: var(--app-space-2);
  border-radius: var(--md-sys-shape-corner-full); cursor: pointer; color: var(--md-sys-color-on-surface-variant);
}
.row.active { background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); }
.row.dropping { outline: 2px solid var(--md-sys-color-primary); outline-offset: -2px; }
.toggle { display: grid; place-items: center; width: 24px; height: 24px; flex: none; border: 0; padding: 0; background: transparent; color: inherit; cursor: pointer; border-radius: 50%; }
.chevron { transition: transform var(--md-sys-motion-duration-short4) var(--md-sys-motion-easing-standard); }
.chevron.open { transform: rotate(90deg); }
.name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.label {
  flex: none; max-width: 50%; margin-left: auto; padding: 0 var(--app-space-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  border-radius: var(--md-sys-shape-corner-full); background: var(--md-sys-color-tertiary-container); color: var(--md-sys-color-on-tertiary-container);
}
</style>
