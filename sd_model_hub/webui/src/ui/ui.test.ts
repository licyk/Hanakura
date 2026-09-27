import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { nextTick } from 'vue';
import { formatBytes, parentPath, pathSegments } from '@/format';
import { translate } from '@/i18n';
import { windowClass } from '@/theme/breakpoints';
import { generateScheme } from '@/theme/scheme';
import Breadcrumbs from '@/ui/Breadcrumbs.vue';
import EmptyState from '@/ui/EmptyState.vue';
import ExpansionPanel from '@/ui/ExpansionPanel.vue';
import PathText from '@/ui/PathText.vue';
import SegmentedButton from '@/ui/SegmentedButton.vue';
import { Box } from '@/ui/icons';
import { containerFrom, staggerStyle } from '@/ui/motion/transitions';
import { useSnackbar } from '@/ui/useSnackbar';

describe('ui components', () => {
  it('SegmentedButton selects one option', async () => {
    const wrapper = mount(SegmentedButton, { props: { modelValue: 'a', options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }], 'onUpdate:modelValue': (v: string) => wrapper.setProps({ modelValue: v }) } });
    const buttons = wrapper.findAll('button');
    expect(buttons[0].attributes('aria-checked')).toBe('true');
    await buttons[1].trigger('click');
    await nextTick();
    expect(wrapper.findAll('button')[1].attributes('aria-checked')).toBe('true');
  });

  it('Breadcrumbs emits the crumb value and marks the last as current', async () => {
    const wrapper = mount(Breadcrumbs, { props: { crumbs: [{ label: 'root', value: '' }, { label: 'a', value: 'a' }, { label: 'b', value: 'a/b' }] } });
    await wrapper.findAll('button')[1].trigger('click');
    expect(wrapper.emitted('navigate')?.[0]).toEqual(['a']);
    expect(wrapper.find('[aria-current="location"]').text()).toBe('b');
  });

  it('EmptyState renders title and text', () => {
    const wrapper = mount(EmptyState, { props: { icon: Box, title: 'Nothing', text: 'here' } });
    expect(wrapper.text()).toContain('Nothing');
    expect(wrapper.text()).toContain('here');
  });

  it('ExpansionPanel shows its content only when open, and reports the change', async () => {
    const wrapper = mount(ExpansionPanel, { props: { label: 'Model card' }, slots: { default: '<p>body</p>' } });
    const header = wrapper.find('button');
    expect(header.attributes('aria-expanded')).toBe('false');
    expect(wrapper.text()).not.toContain('body');

    await header.trigger('click');
    await nextTick();
    expect(header.attributes('aria-expanded')).toBe('true');
    expect(wrapper.text()).toContain('body');
    expect(wrapper.emitted('update:open')?.[0]).toEqual([true]);
    // The header labels the region it opens, so a screen reader announces the pair.
    expect(wrapper.find('[role="region"]').attributes('aria-labelledby')).toBe(header.attributes('id'));
  });

  it('PathText keeps a path in its own order inside the right-to-left line that moves the ellipsis', () => {
    const wrapper = mount(PathText, { props: { path: '/root/model' } });
    expect(wrapper.attributes('title')).toBe('/root/model');
    // Without the isolate, a right-to-left line draws the leading "/" at the far end.
    const inner = wrapper.find('bdi');
    expect(inner.attributes('dir')).toBe('ltr');
    expect(inner.text()).toBe('/root/model');
    const css = readFileSync(join(process.cwd(), 'src/ui/PathText.vue'), 'utf8');
    expect(css).toMatch(/\.path-text \{[^}]*direction: rtl/);
  });

  it('no path is set right-to-left outside PathText', () => {
    const offenders = readdirSync(join(process.cwd(), 'src'), { recursive: true, encoding: 'utf8' })
      .filter((f) => f.endsWith('.vue') && !f.endsWith('PathText.vue'))
      .filter((f) => readFileSync(join(process.cwd(), 'src', f), 'utf8').includes('direction: rtl'));
    expect(offenders).toEqual([]);
  });

  it('snackbar queue shows one message at a time', () => {
    const s = useSnackbar();
    s.show('one');
    s.show('two', { actionLabel: 'Undo' });
    expect(s.state.queue.map((m) => m.text)).toEqual(['one', 'two']);
    s.dismiss(s.state.queue[0].id);
    expect(s.state.queue[0].text).toBe('two');
    expect(s.state.queue[0].timeout).toBe(6000);
    s.dismiss(s.state.queue[0].id);
  });
});

describe('motion helpers', () => {
  it('staggers by 20ms up to a cap', () => {
    expect(staggerStyle(2)['--stagger']).toBe('40ms');
    expect(staggerStyle(100)['--stagger']).toBe('240ms');
  });
  it('container transition starts from the card rectangle', () => {
    const style = containerFrom(new DOMRect(10, 20, 100, 200), new DOMRect(0, 0, 400, 400));
    expect(style['--from-transform']).toBe('translate(10px, 20px) scale(0.25, 0.5)');
    expect(containerFrom(null, new DOMRect(0, 0, 1, 1))).toEqual({});
  });
});

describe('theme', () => {
  it('generates every role as a hex colour, different in light and dark', () => {
    const light = generateScheme('#4a6fa5', false);
    const dark = generateScheme('#4a6fa5', true);
    expect(light.primary).toMatch(/^#[0-9a-f]{6}$/);
    expect(light.surface).not.toBe(dark.surface);
    expect(generateScheme('not a colour', false).primary).toBe(generateScheme('#4a6fa5', false).primary);
  });
  it('maps widths to window size classes', () => {
    expect([599, 600, 839, 840, 1199, 1200, 1600].map(windowClass)).toEqual(['compact', 'medium', 'medium', 'expanded', 'expanded', 'large', 'extra-large']);
  });
});

describe('i18n and formatting', () => {
  it('translates with parameters and falls back to English', () => {
    expect(translate('zh-CN', 'library.selected', { n: 3 })).toBe('已选择 3 项');
    expect(translate('en', 'library.selected', { n: 3 })).toBe('3 selected');
    expect(translate('en', 'no.such.key')).toBe('no.such.key');
  });
  it('formats sizes and paths', () => {
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(null)).toBe('—');
    expect(pathSegments('a/b/c').map((s) => s.path)).toEqual(['a', 'a/b', 'a/b/c']);
    expect(parentPath('a/b/c')).toBe('a/b');
  });
});
