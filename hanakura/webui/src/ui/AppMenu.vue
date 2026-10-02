<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch, type Component } from 'vue';
import AppIcon from '@/ui/AppIcon.vue';

export interface MenuItem {
  id: string;
  label: string;
  icon?: Component;
  danger?: boolean;
  disabled?: boolean;
}

/**
 * An anchored menu. Place the trigger in the default slot; it receives ``toggle``.
 *
 * The list is rendered at the end of the document and positioned against the trigger, so a card
 * or a list row with its own overflow cannot clip it to one line. It flips above or to the other
 * side when there is no room, and follows the trigger while the page scrolls.
 */
const props = withDefaults(defineProps<{ items: MenuItem[]; align?: 'start' | 'end' }>(), { align: 'end' });
const emit = defineEmits<{ select: [string] }>();
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const list = ref<HTMLElement | null>(null);
const position = ref<Record<string, string>>({});

const MIN_WIDTH = 200;
const MARGIN = 8;

function place() {
  const trigger = root.value?.firstElementChild ?? root.value;
  if (!trigger) return;
  const anchor = trigger.getBoundingClientRect();
  const menu = list.value?.getBoundingClientRect();
  const width = Math.max(menu?.width ?? MIN_WIDTH, MIN_WIDTH);
  const height = menu?.height ?? 0;
  const below = window.innerHeight - anchor.bottom;
  // Open downwards unless the list would not fit and there is more room above.
  const openUp = height > below - MARGIN && anchor.top > below;
  const left = props.align === 'end' ? anchor.right - width : anchor.left;
  position.value = {
    left: `${Math.min(Math.max(MARGIN, left), Math.max(MARGIN, window.innerWidth - width - MARGIN))}px`,
    top: openUp ? '' : `${anchor.bottom + 4}px`,
    bottom: openUp ? `${window.innerHeight - anchor.top + 4}px` : '',
    minWidth: `${MIN_WIDTH}px`,
    maxHeight: `${Math.max(120, (openUp ? anchor.top : below) - MARGIN * 2)}px`,
  };
}

const onDoc = (e: Event) => {
  const target = e.target as Node;
  if (!root.value?.contains(target) && !list.value?.contains(target)) open.value = false;
};
const onKey = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    open.value = false;
    return;
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const items = [...(list.value?.querySelectorAll<HTMLButtonElement>('button:not([disabled])') ?? [])];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    e.preventDefault();
  }
};
const onReflow = () => (open.value ? place() : undefined);

watch(open, async (v) => {
  if (v) {
    document.addEventListener('pointerdown', onDoc);
    document.addEventListener('keydown', onKey);
    // Capture, so scrolling in any container keeps the menu on its trigger.
    window.addEventListener('scroll', onReflow, true);
    window.addEventListener('resize', onReflow);
    await nextTick();
    place();
    list.value?.querySelector<HTMLButtonElement>('button:not([disabled])')?.focus();
  } else {
    document.removeEventListener('pointerdown', onDoc);
    document.removeEventListener('keydown', onKey);
    window.removeEventListener('scroll', onReflow, true);
    window.removeEventListener('resize', onReflow);
  }
});
onBeforeUnmount(() => {
  open.value = false;
  document.removeEventListener('pointerdown', onDoc);
  document.removeEventListener('keydown', onKey);
  window.removeEventListener('scroll', onReflow, true);
  window.removeEventListener('resize', onReflow);
});

function choose(id: string) {
  open.value = false;
  emit('select', id);
}
const toggle = () => (open.value = !open.value);
</script>

<template>
  <div ref="root" class="menu-root" @click.stop>
    <slot :toggle="toggle" :open="open" />
    <Teleport to="body">
      <Transition name="snackbar">
        <div v-if="open" ref="list" class="menu" role="menu" :style="position" @click.stop>
          <button
            v-for="item in items"
            :key="item.id"
            type="button"
            role="menuitem"
            class="item state-layer type-label-large"
            :class="{ danger: item.danger }"
            :disabled="item.disabled"
            @click="choose(item.id)"
          >
            <AppIcon v-if="item.icon" :icon="item.icon" :size="20" />
            <span>{{ item.label }}</span>
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.menu-root { display: inline-flex; }
.menu {
  position: fixed; z-index: 35; padding: var(--app-space-2) 0; overflow-y: auto;
  background: var(--md-sys-color-surface-container); border-radius: var(--md-sys-shape-corner-extra-small); box-shadow: var(--app-elevation-2);
}
.item {
  display: flex; align-items: center; gap: var(--app-space-3); width: 100%; height: 48px; padding: 0 var(--app-space-3);
  border: 0; background: transparent; color: var(--md-sys-color-on-surface); cursor: pointer; text-align: left; font: inherit; white-space: nowrap;
}
.item:disabled { opacity: var(--app-disabled-content-opacity); cursor: default; }
.item.danger { color: var(--md-sys-color-error); }
</style>
