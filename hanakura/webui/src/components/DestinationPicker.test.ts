import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import DestinationPicker from '@/components/DestinationPicker.vue';
import { AppButton, SelectField, TextField } from '@/ui';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({
  api: { GET: get },
  unwrap: async (value: Promise<unknown>) => {
    const result = await value;
    if (result instanceof Error) throw result;
    return result;
  },
}));
vi.mock('@/api/queries/library', () => ({ useRoots: () => ({ data: ref([{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }]) }) }));
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

function picker() {
  return mount(DestinationPicker, {
    props: { open: true, kind: 'lora' },
    global: { stubs: { AppDialog: { template: '<div><slot /><slot name="actions" /></div>' }, SelectField: true, TextField: true, Checkbox: true, AppButton: true } },
  });
}

describe('download destination', () => {
  beforeEach(() => get.mockReset());

  it('uses the backend root and relative directory, including an empty directory', async () => {
    get.mockResolvedValue({ root_id: 'b', rel_dir: '' });
    const wrapper = picker();
    await flushPromises();
    expect(wrapper.findComponent(SelectField).props('modelValue')).toBe('b');
    expect(wrapper.findComponent(TextField).props('modelValue')).toBe('');
    wrapper.findAllComponents(AppButton)[1].vm.$emit('click');
    expect(wrapper.emitted('confirm')?.[0]).toEqual([{ root_id: 'b', rel_dir: '', overwrite: false }]);
    wrapper.unmount();
  });

  it('ignores an old suggestion after the user selects another root', async () => {
    let finish!: (value: { root_id: string; rel_dir: string }) => void;
    get.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    get.mockResolvedValue({ root_id: 'b', rel_dir: 'chosen' });
    const wrapper = picker();
    wrapper.findComponent(SelectField).vm.$emit('update:modelValue', 'b');
    await flushPromises();
    finish({ root_id: 'a', rel_dir: 'stale' });
    await flushPromises();
    expect(wrapper.findComponent(SelectField).props('modelValue')).toBe('b');
    expect(wrapper.findComponent(TextField).props('modelValue')).toBe('chosen');
    wrapper.unmount();
  });

  it('does not overwrite a directory typed while a suggestion was loading', async () => {
    let finish!: (value: { root_id: string; rel_dir: string }) => void;
    get.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    get.mockResolvedValue({ root_id: 'a', rel_dir: 'suggested' });
    const wrapper = picker();
    wrapper.findComponent(TextField).vm.$emit('update:modelValue', 'manual');
    finish({ root_id: 'a', rel_dir: 'suggested' });
    await flushPromises();
    expect(wrapper.findComponent(TextField).props('modelValue')).toBe('manual');
    wrapper.unmount();
  });

  it('requests the new model kind even before the first suggestion has arrived', async () => {
    let finish!: (value: { root_id: string; rel_dir: string }) => void;
    get.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    get.mockResolvedValue({ root_id: 'b', rel_dir: 'vae' });
    const wrapper = picker();
    await wrapper.setProps({ kind: 'vae' });
    await flushPromises();
    finish({ root_id: 'a', rel_dir: 'lora' });
    await flushPromises();
    expect(wrapper.findComponent(SelectField).props('modelValue')).toBe('b');
    expect(wrapper.findComponent(TextField).props('modelValue')).toBe('vae');
    wrapper.unmount();
  });

  it('blocks both button and Enter submission when resolution fails', async () => {
    get.mockResolvedValue(new Error('No model root with id missing'));
    const wrapper = picker();
    await flushPromises();
    expect(wrapper.findComponent(TextField).props('errorText')).toContain('missing');
    expect(wrapper.findAllComponents(AppButton)[1].props('disabled')).toBe(true);
    wrapper.findComponent(TextField).vm.$emit('enter');
    expect(wrapper.emitted('confirm')).toBeUndefined();
    wrapper.unmount();
  });
});
