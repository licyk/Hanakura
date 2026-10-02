/**
 * Render a model card (README) written in Markdown.
 *
 * Model cards lean on HTML for what Markdown cannot express: centred banners, image rows,
 * `<details>` sections, tables with spans. That HTML is parsed, but the text comes from a third
 * party, so nothing reaches the page unchecked: markdown-it's output goes through DOMPurify with
 * the allowlist below, which keeps document markup and drops everything that can execute, load a
 * script, frame another page, or restyle the app. Links and images are hardened afterwards, so a
 * raw `<a>` in the card is treated exactly like a Markdown one. See `markdown.test.ts`, which
 * holds these promises.
 */
import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';

const md = new MarkdownIt({ html: true, linkify: true, breaks: false, typographer: false });

/** Document markup only: no script, style, iframe, object, form, or custom element survives. */
const ALLOWED_TAGS = [
  'p', 'br', 'hr', 'div', 'span', 'center', 'section', 'article',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'strong', 'b', 'em', 'i', 'u', 's', 'strike', 'del', 'ins', 'mark', 'small', 'sub', 'sup', 'abbr',
  'code', 'pre', 'kbd', 'samp', 'var', 'blockquote', 'q', 'cite',
  'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  'a', 'img', 'figure', 'figcaption',
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
  'details', 'summary',
];

/**
 * No `class` or `style`: a card must not be able to borrow the app's styling or cover the page.
 * `align`, `width` and `height` are the presentational attributes model cards actually use.
 */
const ALLOWED_ATTR = [
  'href', 'src', 'alt', 'title', 'align', 'valign', 'width', 'height',
  'colspan', 'rowspan', 'span', 'start', 'reversed', 'open', 'dir', 'lang',
];

// This module owns DOMPurify's hooks; it is the only caller.
// Links leave the app, so they open in a new tab and carry no referrer or window handle;
// images are often broken or huge in a README, so they load lazily and never block the text.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer nofollow');
  }
  if (node.tagName === 'IMG') {
    node.setAttribute('loading', 'lazy');
    node.setAttribute('referrerpolicy', 'no-referrer');
  }
});

export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(md.render(text), {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    ALLOW_UNKNOWN_PROTOCOLS: false,
  });
}
