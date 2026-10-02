/**
 * @vitest-environment jsdom
 *
 * DOMPurify walks the parsed document with a NodeIterator, and happy-dom's iterator stops as soon
 * as the walk root is removed — which is the first thing DOMPurify does on the string path — so
 * under happy-dom it returns its input almost untouched. jsdom implements the walk the way
 * browsers do, so this file, the one that checks the sanitising, runs there.
 */
import { describe, expect, it } from 'vitest';
import { renderMarkdown } from '@/markdown';

describe('renderMarkdown', () => {
  it('renders Markdown structure', () => {
    const html = renderMarkdown('# Title\n\nSome **bold** text.\n\n- one\n- two\n');
    expect(html).toContain('<h1>Title</h1>');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<li>one</li>');
  });

  it('renders fenced code as a block, not as Markdown', () => {
    const html = renderMarkdown('```python\nprint("# hi")\n```\n');
    expect(html).toContain('<pre><code');
    expect(html).not.toContain('<h1>');
  });

  /** Model cards use HTML for what Markdown cannot express; those tags are rendered. */
  it('renders the HTML a model card embeds', () => {
    const html = renderMarkdown(
      '<p align="center">\n<img src="https://example.com/a.png" width="100%"/>\n</p>\n\n' +
        '<details><summary>More</summary>\n\nHidden **text**.\n\n</details>\n',
    );
    expect(html).toContain('<p align="center">');
    expect(html).toContain('<img src="https://example.com/a.png" width="100%"');
    expect(html).toContain('<details><summary>More</summary>');
    expect(html).toContain('<strong>text</strong>');
  });

  it('renders inline HTML inside a paragraph', () => {
    const html = renderMarkdown('A line with <em>emphasis</em> and a <br> break.\n');
    expect(html).toContain('<em>emphasis</em>');
    expect(html).toContain('<br>');
  });

  /** A model card comes from a third party: its HTML is rendered, but only the safe part of it. */
  it('drops anything executable', () => {
    const html = renderMarkdown(
      '<script>alert(1)</script>\n\n<img src="x" onerror="alert(2)">\n\n' +
        '<iframe src="https://evil.example/"></iframe>\n\n<style>body{display:none}</style>\n',
    );
    expect(html).not.toContain('<script');
    expect(html).not.toContain('<iframe');
    expect(html).not.toContain('<style');
    expect(html).not.toContain('onerror');
    expect(html).not.toContain('alert(1)');
    expect(html).toContain('<img src="x"'); // The image itself stays; only the handler went.
  });

  it('drops a script link written as raw HTML', () => {
    const html = renderMarkdown('<a href="javascript:alert(1)">click</a>\n');
    expect(html).not.toContain('javascript:');
    expect(html).toContain('click');
  });

  it('keeps a card from borrowing the app styling', () => {
    const html = renderMarkdown('<div class="app-bar" style="position:fixed;inset:0">x</div>\n');
    expect(html).not.toContain('class=');
    expect(html).not.toContain('style=');
  });

  it('leaves a script link unlinked', () => {
    const html = renderMarkdown('[click](javascript:alert(1))\n');
    expect(html).not.toContain('<a ');
    expect(html).not.toContain('href');
  });

  it('opens links in a new tab without a window handle', () => {
    const md = renderMarkdown('[hf](https://huggingface.co/)\n');
    const raw = renderMarkdown('<a href="https://huggingface.co/">hf</a>\n');
    for (const html of [md, raw]) {
      expect(html).toContain('target="_blank"');
      expect(html).toContain('rel="noopener noreferrer nofollow"');
    }
  });

  it('loads images lazily and without a referrer', () => {
    const md = renderMarkdown('![preview](https://example.com/a.png)\n');
    const raw = renderMarkdown('<img src="https://example.com/a.png">\n');
    for (const html of [md, raw]) {
      expect(html).toContain('loading="lazy"');
      expect(html).toContain('referrerpolicy="no-referrer"');
    }
  });
});
