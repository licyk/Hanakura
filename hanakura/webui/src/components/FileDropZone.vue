<script setup lang="ts">
import { ref } from 'vue';
import { AppIcon, icons } from '@/ui';

export interface DroppedFile {
  file: File;
  relativePath: string;
}

/** The whole area accepts files dragged in from outside, including folders, with relative paths kept. */
const props = defineProps<{ label: string; disabled?: boolean }>();
const emit = defineEmits<{ files: [DroppedFile[]] }>();
const over = ref(false);
let depth = 0;

const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files');

function onEnter(e: DragEvent) {
  if (props.disabled || !hasFiles(e)) return;
  depth++;
  over.value = true;
}
function onLeave() {
  depth = Math.max(0, depth - 1);
  if (depth === 0) over.value = false;
}
function onOver(e: DragEvent) {
  if (props.disabled || !hasFiles(e)) return;
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
}

function readEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
}

async function walk(entry: FileSystemEntry, prefix: string, out: DroppedFile[]) {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
    out.push({ file, relativePath: prefix + file.name });
  } else if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries returns batches; call until empty.
    for (let batch = await readEntries(reader); batch.length; batch = await readEntries(reader)) {
      for (const child of batch) await walk(child, `${prefix}${entry.name}/`, out);
    }
  }
}

async function onDrop(e: DragEvent) {
  if (props.disabled || !hasFiles(e)) return;
  e.preventDefault();
  depth = 0;
  over.value = false;
  const out: DroppedFile[] = [];
  const items = Array.from(e.dataTransfer?.items ?? []);
  const entries = items.map((i) => i.webkitGetAsEntry?.()).filter((x): x is FileSystemEntry => !!x);
  if (entries.length) {
    for (const entry of entries) await walk(entry, '', out);
  } else {
    for (const file of Array.from(e.dataTransfer?.files ?? [])) out.push({ file, relativePath: file.name });
  }
  if (out.length) emit('files', out);
}
</script>

<template>
  <div class="drop-zone" :class="{ over }" @dragenter="onEnter" @dragleave="onLeave" @dragover="onOver" @drop="onDrop">
    <slot />
    <Transition name="scrim">
      <div v-if="over" class="overlay">
        <div class="message">
          <AppIcon :icon="icons.Upload" :size="24" />
          <span class="type-title-medium">{{ label }}</span>
        </div>
      </div>
    </Transition>
    <span class="visually-hidden" aria-live="assertive">{{ over ? label : '' }}</span>
  </div>
</template>

<style scoped>
.drop-zone { position: relative; min-height: 100%; }
.overlay {
  position: absolute; inset: var(--app-space-2); z-index: 10; pointer-events: none; display: grid; place-items: center;
  border: 2px dashed var(--md-sys-color-primary); border-radius: var(--md-sys-shape-corner-large);
  background: color-mix(in srgb, var(--md-sys-color-primary) calc(var(--md-sys-state-dragged-state-layer-opacity) * 100%), transparent);
}
.message {
  display: flex; align-items: center; gap: var(--app-space-3); padding: var(--app-space-3) var(--app-space-6);
  border-radius: var(--md-sys-shape-corner-full); background: var(--md-sys-color-primary); color: var(--md-sys-color-on-primary); box-shadow: var(--app-elevation-2);
}
</style>
