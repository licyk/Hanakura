/** Named transitions and helpers for the motion system. See motion.css. */

export const TRANSITIONS = {
  fadeThrough: 'fade-through',
  sharedAxisX: 'shared-axis-x',
  container: 'container',
  sheet: 'sheet',
  drawer: 'drawer',
  scrim: 'scrim',
  list: 'list',
  collapse: 'collapse',
  snackbar: 'snackbar',
} as const;

const STAGGER_MS = 20;
const STAGGER_CAP = 12;

/** Style for the n-th item of a list transition: a 20 ms stagger, capped. */
export function staggerStyle(index: number): Record<string, string> {
  return { '--stagger': `${Math.min(index, STAGGER_CAP) * STAGGER_MS}ms` };
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * CSS variables that make a dialog grow from ``from`` (a card's rectangle) into ``to``.
 * Returns an empty object when the source rectangle is unknown, which falls back to fade and scale.
 */
export function containerFrom(from: DOMRect | null | undefined, to: DOMRect | null | undefined): Record<string, string> {
  if (!from || !to || to.width === 0 || to.height === 0) return {};
  const scaleX = from.width / to.width;
  const scaleY = from.height / to.height;
  const dx = from.left - to.left;
  const dy = from.top - to.top;
  return {
    '--from-origin': 'top left',
    '--from-transform': `translate(${dx}px, ${dy}px) scale(${scaleX}, ${scaleY})`,
  };
}

/** Hooks for <Transition name="collapse"> that animate height from and to the content's size. */
export const collapseHooks = {
  onBeforeEnter(el: Element) {
    (el as HTMLElement).style.height = '0';
  },
  onEnter(el: Element) {
    const e = el as HTMLElement;
    e.style.height = `${e.scrollHeight}px`;
  },
  onAfterEnter(el: Element) {
    (el as HTMLElement).style.height = '';
  },
  onBeforeLeave(el: Element) {
    const e = el as HTMLElement;
    e.style.height = `${e.scrollHeight}px`;
  },
  onLeave(el: Element) {
    const e = el as HTMLElement;
    void e.offsetHeight;
    e.style.height = '0';
  },
};
