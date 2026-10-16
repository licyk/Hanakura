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
 * A field and its buttons (Open, Refresh, a token's Save): the buttons centre on the field's box,
 * not on the box and the supporting text under it, so a hint never pulls them out of line.
 */
describe('field rows', () => {
  it('FieldRow centres its end on the field box alone', () => {
    expect(rule('ui/FieldRow.vue', '.field-row')).toContain('align-items: flex-start');
    const end = rule('ui/FieldRow.vue', '.end');
    expect(end).toContain('align-items: center');
    expect(end).toContain('min-height: var(--app-field-height)');
  });
  it.each(['views/HubsView.vue', 'ui/TokenField.vue'])('%s puts fields and their buttons in a FieldRow', (file) => {
    expect(readFileSync(join(SRC, file), 'utf8')).toContain('<FieldRow');
  });
  // Fields side by side in a stretching grid keep their own boxes (Settings › Network).
  it.each([['ui/TextField.vue', '.text-field'], ['ui/SelectField.vue', '.select']] as const)('%s keeps its own height', (file, selector) => {
    expect(rule(file, selector)).toContain('height: fit-content');
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
