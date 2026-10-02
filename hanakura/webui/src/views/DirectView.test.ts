import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import DestinationPicker from '@/components/DestinationPicker.vue';
import { AppButton, TextField } from '@/ui';
import DirectView from '@/views/DirectView.vue';

const mutate = vi.hoisted(() => vi.fn());
vi.mock('@/api/queries/downloads', () => ({ useCreateDownload: () => ({ mutate, isPending: ref(false) }) }));
vi.mock('@/api/queries/app', () => ({ useMeta: () => ({ data: ref({ kinds: ['lora'] }) }) }));
vi.mock('@/stores/downloads', () => ({ useDownloadsStore: () => ({ drawerOpen: false }) }));
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, kindLabel: (kind: string) => kind }) }));

function view() {
  return mount(DirectView, {
    global: { stubs: { DestinationPicker: true, SelectField: true, TextField: true, AppButton: true, AppIcon: true } },
  });
}

const field = (wrapper: ReturnType<typeof view>, label: string) => wrapper.findAllComponents(TextField).find((f) => f.props('label') === label)!;

describe('direct link download', () => {
  it('queues the typed address with the chosen destination', async () => {
    mutate.mockReset();
    const wrapper = view();
    field(wrapper, 'direct.url').vm.$emit('update:modelValue', ' https://example.com/a/model.safetensors ');
    field(wrapper, 'direct.fileName').vm.$emit('update:modelValue', ' renamed.safetensors ');
    await flushPromises();

    expect(wrapper.findComponent(AppButton).props('disabled')).toBe(false);
    wrapper.findComponent(DestinationPicker).vm.$emit('confirm', { root_id: 'models', rel_dir: 'loras', overwrite: false });
    expect(mutate.mock.calls[0][0]).toEqual({
      url: 'https://example.com/a/model.safetensors',
      file_name: 'renamed.safetensors',
      expected_sha256: null,
      title: 'renamed.safetensors',
      root_id: 'models',
      rel_dir: 'loras',
      overwrite: false,
    });
    wrapper.unmount();
  });

  it('names the file after the link and refuses an address that is not http', async () => {
    mutate.mockReset();
    const wrapper = view();
    field(wrapper, 'direct.url').vm.$emit('update:modelValue', 'file:///models/model.safetensors');
    await flushPromises();
    expect(field(wrapper, 'direct.url').props('errorText')).toBe('direct.urlInvalid');
    expect(wrapper.findComponent(AppButton).props('disabled')).toBe(true);

    field(wrapper, 'direct.url').vm.$emit('update:modelValue', 'https://example.com/a/my%20model.safetensors');
    await flushPromises();
    expect(wrapper.findComponent(DestinationPicker).props('fileLabel')).toBe('my model.safetensors');
    wrapper.unmount();
  });

  it('refuses a hash that is not a SHA256', async () => {
    const wrapper = view();
    field(wrapper, 'direct.url').vm.$emit('update:modelValue', 'https://example.com/model.safetensors');
    field(wrapper, 'direct.sha256').vm.$emit('update:modelValue', 'abc123');
    await flushPromises();
    expect(field(wrapper, 'direct.sha256').props('errorText')).toBe('direct.sha256Invalid');
    expect(wrapper.findComponent(AppButton).props('disabled')).toBe(true);
    wrapper.unmount();
  });
});
