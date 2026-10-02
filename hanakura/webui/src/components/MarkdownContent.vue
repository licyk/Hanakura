<script setup lang="ts">
import { computed } from 'vue';
import { renderMarkdown } from '@/markdown';

/** Third-party Markdown or HTML — a hub model card, a source's model description — rendered safely. */
const props = defineProps<{ text: string }>();
const html = computed(() => (props.text ? renderMarkdown(props.text) : ''));
</script>

<template>
  <!-- Safe: markdown-it's output, sanitised with DOMPurify before it gets here. See src/markdown.ts. -->
  <div class="markdown type-body-medium" v-html="html"></div>
</template>

<style scoped>
.markdown { overflow-wrap: anywhere; padding: var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); }
/* The tags come from the text itself, so they can only be styled through :deep. */
.markdown > :deep(:first-child) { margin-top: 0; }
.markdown > :deep(:last-child) { margin-bottom: 0; }
.markdown :deep(h1), .markdown :deep(h2), .markdown :deep(h3), .markdown :deep(h4), .markdown :deep(h5), .markdown :deep(h6) {
  margin: var(--app-space-4) 0 var(--app-space-2);
  font-size: var(--md-sys-typescale-title-small-size); line-height: var(--md-sys-typescale-title-small-line-height); font-weight: var(--md-sys-typescale-title-small-weight);
}
.markdown :deep(h1), .markdown :deep(h2) { padding-bottom: var(--app-space-1); border-bottom: 1px solid var(--md-sys-color-outline-variant); }
.markdown :deep(p), .markdown :deep(ul), .markdown :deep(ol), .markdown :deep(blockquote), .markdown :deep(table) { margin: var(--app-space-2) 0; }
.markdown :deep(ul), .markdown :deep(ol) { padding-left: var(--app-space-5); }
.markdown :deep(a) { color: var(--md-sys-color-primary); }
.markdown :deep(code) { padding: 0 4px; border-radius: var(--md-sys-shape-corner-extra-small); background: var(--md-sys-color-surface-container-highest); font-family: ui-monospace, monospace; font-size: 0.9em; }
.markdown :deep(pre) { margin: var(--app-space-2) 0; padding: var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container-highest); overflow: auto; }
.markdown :deep(pre code) { padding: 0; background: none; }
.markdown :deep(blockquote) { padding-left: var(--app-space-3); border-left: 3px solid var(--md-sys-color-outline-variant); color: var(--md-sys-color-on-surface-variant); }
.markdown :deep(img) { max-width: 100%; height: auto; }
.markdown :deep(table) { border-collapse: collapse; display: block; overflow: auto; }
.markdown :deep(th), .markdown :deep(td) { padding: var(--app-space-1) var(--app-space-2); border: 1px solid var(--md-sys-color-outline-variant); }
.markdown :deep(th:not([align])), .markdown :deep(td:not([align])) { text-align: left; }
.markdown :deep(hr) { border: 0; border-top: 1px solid var(--md-sys-color-outline-variant); }
/* Tags a text brings itself rather than through Markdown. */
.markdown :deep(details) { margin: var(--app-space-2) 0; }
.markdown :deep(summary) { cursor: pointer; font-weight: var(--md-sys-typescale-title-small-weight); }
.markdown :deep(figure) { margin: var(--app-space-2) 0; }
.markdown :deep(figcaption) { color: var(--md-sys-color-on-surface-variant); font-size: 0.9em; }
</style>
