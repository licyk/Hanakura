import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Rows that pair a name with a control must let the name shrink.
 *
 * A model file name is one long unbreakable word, so the row's min-content width is the whole
 * name. A flex item keeps `min-width: auto` by default and refuses to go below that, which pushed
 * the overflow menu out of the card (clipped away, so the model could not be renamed or deleted)
 * and the snackbar's buttons off the screen. `min-width: 0` on the item that holds the text is
 * what makes the ellipsis work and keeps the control in place.
 */
const SRC = join(process.cwd(), 'src');
const ROWS: [file: string, selector: string][] = [
  ['components/ModelCard.vue', '.body'],
  ['components/DownloadItem.vue', '.main'],
  ['components/DownloadsDrawer.vue', '.main'],
  ['components/RepoFileTree.vue', '.name'],
  ['ui/Snackbar.vue', '.text'],
  ['views/LibraryView.vue', '.folder-text'],
];

function rule(file: string, selector: string): string {
  const css = readFileSync(join(SRC, file), 'utf8');
  const match = new RegExp(String.raw`(?:^|\n)\s*${selector.replace('.', '\\.')}\s*\{([^}]*)\}`).exec(css);
  expect(match, `${file} has no rule for ${selector}`).not.toBeNull();
  return match![1];
}

describe('rows that hold a file name', () => {
  it.each(ROWS)('%s %s can shrink below the name', (file, selector) => {
    expect(rule(file, selector)).toContain('min-width: 0');
  });
});

/**
 * A component capped at a fixed width stops growing with the window, leaving a wide screen mostly
 * margin. Caps scale with the viewport instead (`clamp()`, `max()`); a fixed pixel cap belongs only
 * inside a media query, where the window size is already known.
 */
describe('widths follow the window', () => {
  const files = (dir: string): string[] =>
    readdirSync(join(SRC, dir), { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? files(join(dir, e.name)) : e.name.endsWith('.vue') ? [join(dir, e.name)] : []));

  it.each(files('.'))('%s has no fixed max-width outside a media query', (file) => {
    const style = /<style[^>]*>([\s\S]*?)<\/style>/.exec(readFileSync(join(SRC, file), 'utf8'))?.[1] ?? '';
    const outside = style.replace(/@media[^{]*\{(?:[^{}]*\{[^}]*\})*[^{}]*\}/g, '');
    expect(outside).not.toMatch(/max-width:\s*\d+px/);
    expect(outside).not.toMatch(/width:\s*min\(\s*\d+px/);
  });
});
