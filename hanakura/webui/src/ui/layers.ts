import { onScopeDispose, watch } from 'vue';

/**
 * Overlays stacked on one another — a menu inside a dialog, an image viewer above a dialog, a
 * dialog above a drawer — share one keyboard. Each listening on the document for itself closed
 * every layer on a single Escape and let a dialog's focus trap pull focus out of the viewer
 * above it, so they register here instead and only the topmost receives keys.
 */
type KeyHandler = (event: KeyboardEvent) => void;
interface Layer {
  onKey: KeyHandler;
}

const stack: Layer[] = [];

function dispatch(event: KeyboardEvent) {
  // A control inside the layer that handled the key itself (closing its own popup) has claimed it.
  if (event.defaultPrevented) return;
  stack[stack.length - 1]?.onKey(event);
}

function add(layer: Layer) {
  if (stack.includes(layer)) return;
  stack.push(layer);
  if (stack.length === 1) document.addEventListener('keydown', dispatch);
}

function remove(layer: Layer) {
  const i = stack.indexOf(layer);
  if (i < 0) return;
  stack.splice(i, 1);
  if (!stack.length) document.removeEventListener('keydown', dispatch);
}

/**
 * Registers a layer while ``active`` is true, topmost from the moment it becomes active. The
 * handler sees every key pressed while the layer is on top; one it acts on should be
 * ``preventDefault``-ed so listeners outside the stack can tell.
 */
export function useLayer(active: () => boolean, onKey: KeyHandler): { isTop: () => boolean } {
  const layer: Layer = { onKey };
  watch(active, (value) => (value ? add(layer) : remove(layer)), { immediate: true });
  onScopeDispose(() => remove(layer));
  return { isTop: () => stack[stack.length - 1] === layer };
}

const FOCUSABLE = 'button:not([disabled]), [href], input, select, textarea, video[controls], [tabindex]:not([tabindex="-1"]), md-filled-button, md-outlined-button, md-text-button, md-filled-tonal-button, md-icon-button, md-filled-tonal-icon-button';

/** Keeps Tab and Shift+Tab cycling inside ``container``. */
export function trapFocus(event: KeyboardEvent, container: HTMLElement | null) {
  if (event.key !== 'Tab' || !container) return;
  const focusable = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute('disabled'));
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const inside = container.contains(document.activeElement);
  if (event.shiftKey && (document.activeElement === first || !inside)) {
    last.focus();
    event.preventDefault();
  } else if (!event.shiftKey && (document.activeElement === last || !inside)) {
    first.focus();
    event.preventDefault();
  }
}
