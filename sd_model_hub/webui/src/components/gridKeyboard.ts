/**
 * The Library grid's keyboard model, kept apart from the view so it can be tested on its own.
 *
 * Arrows move by one cell or one row, Home/End to the ends, PageUp/PageDown by a screen of rows.
 * The result is clamped to the list; ``null`` means the key does not move the focus.
 */
export function moveFocus(index: number, key: string, columns: number, total: number, pageRows = 3): number | null {
  if (total <= 0) return null;
  const current = index < 0 ? -1 : Math.min(index, total - 1);
  const clamp = (i: number) => Math.max(0, Math.min(total - 1, i));
  switch (key) {
    case 'ArrowRight':
      return clamp(current + 1);
    case 'ArrowLeft':
      return current < 0 ? 0 : clamp(current - 1);
    case 'ArrowDown':
      return current < 0 ? 0 : clamp(current + columns);
    case 'ArrowUp':
      return current < 0 ? 0 : clamp(current - columns);
    case 'Home':
      return 0;
    case 'End':
      return total - 1;
    case 'PageDown':
      return clamp(Math.max(current, 0) + columns * pageRows);
    case 'PageUp':
      return clamp(current - columns * pageRows);
    default:
      return null;
  }
}

/** How many cells share the first row: the grid's column count, whatever the window gives it. */
export function columnsOf(cells: HTMLElement[]): number {
  if (!cells.length) return 1;
  const top = cells[0].getBoundingClientRect().top;
  const n = cells.findIndex((cell) => cell.getBoundingClientRect().top > top + 1);
  return n < 0 ? cells.length : Math.max(n, 1);
}

/** The keys from ``from`` to ``to`` in ``order``, both included, whichever comes first. */
export function rangeOf(order: string[], from: string, to: string): string[] {
  const a = order.indexOf(from);
  const b = order.indexOf(to);
  if (a < 0 || b < 0) return [to];
  return order.slice(Math.min(a, b), Math.max(a, b) + 1);
}
