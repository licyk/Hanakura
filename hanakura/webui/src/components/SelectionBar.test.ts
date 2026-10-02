import { shallowMount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import SelectionBar from '@/components/SelectionBar.vue';
import { IconButton, Switch } from '@/ui';

vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string, params?: Record<string, unknown>) => (params ? `${key}:${JSON.stringify(params)}` : key) }) }));

describe('the selection bar', () => {
  it('is there only while something is selected', async () => {
    const wrapper = shallowMount(SelectionBar, { props: { count: 0, total: 4 } });
    expect(wrapper.find('.selection-bar').exists()).toBe(false);
    await wrapper.setProps({ count: 2 });
    expect(wrapper.find('.selection-bar').attributes('role')).toBe('toolbar');
    expect(wrapper.find('.count').text()).toBe('library.selected:{"n":2}');
  });

  it('leads with clearing and selecting all, then the actions and whether the selection is kept', async () => {
    const wrapper = shallowMount(SelectionBar, { props: { count: 2, total: 4, keep: false } });
    const buttons = wrapper.findAllComponents(IconButton);
    expect(buttons.map((b) => b.props('label'))).toEqual(['library.clearSelection', 'library.selectAll', 'library.moveTo', 'common.delete']);
    for (const b of buttons) b.vm.$emit('click', new MouseEvent('click'));
    expect(Object.keys(wrapper.emitted())).toEqual(expect.arrayContaining(['clear', 'selectAll', 'move', 'delete']));

    wrapper.findComponent(Switch).vm.$emit('update:modelValue', true);
    expect(wrapper.emitted('update:keep')).toEqual([[true]]);

    // Everything is already selected: nothing more to add.
    await wrapper.setProps({ count: 4 });
    expect(wrapper.findAllComponents(IconButton)[1].props('disabled')).toBe(true);
  });
});
