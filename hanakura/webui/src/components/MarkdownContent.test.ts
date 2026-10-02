/**
 * @vitest-environment jsdom
 *
 * DOMPurify is a no-op under happy-dom (see markdown.test.ts), so this renders under jsdom.
 */
import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import MarkdownContent from '@/components/MarkdownContent.vue';

describe('MarkdownContent', () => {
  it('renders a Markdown description', () => {
    const w = mount(MarkdownContent, { props: { text: '## Usage\n\nUse **0.8** weight.\n\n- one\n' } });
    expect(w.find('h2').text()).toBe('Usage');
    expect(w.find('strong').text()).toBe('0.8');
    expect(w.find('li').text()).toBe('one');
  });

  it("renders Civitai's HTML description and strips what could execute", () => {
    const w = mount(MarkdownContent, { props: { text: '<p>Hello <strong>world</strong></p><script>alert(1)</script><p><a href="https://example.com" onclick="x()">link</a></p>' } });
    expect(w.find('strong').text()).toBe('world');
    expect(w.find('script').exists()).toBe(false);
    const a = w.find('a');
    expect(a.attributes('onclick')).toBeUndefined();
    expect(a.attributes('rel')).toContain('noopener');
  });
});
