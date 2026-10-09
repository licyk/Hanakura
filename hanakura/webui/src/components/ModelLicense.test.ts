import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import ModelLicense from '@/components/ModelLicense.vue';
import en from '@/i18n/en';
import zhCN from '@/i18n/zh-CN';

vi.mock('@/i18n', async (importActual) => {
  const actual = await importActual<typeof import('@/i18n')>();
  return { useI18n: () => ({ t: (key: string) => actual.translate('en', key) }) };
});

describe('the model licence', () => {
  it('reads each permission as a sentence with its answer, never as raw flags', () => {
    const wrapper = mount(ModelLicense, {
      props: {
        permissions: [
          { id: 'credit', allowed: true },
          { id: 'rent', allowed: false },
        ],
      },
    });
    const rows = wrapper.findAll('.permission');
    expect(rows.map((r) => r.classes())).toEqual([expect.arrayContaining(['allowed']), expect.arrayContaining(['denied'])]);
    expect(rows[0].text()).toBe('Allowed: Use without crediting the creator');
    expect(rows[1].text()).toBe('Not allowed: Run on services that generate images for money');
    expect(wrapper.text()).not.toMatch(/allow[A-Z]|=/);
  });

  it('shows a named licence on its own, and nothing when there is neither', async () => {
    const wrapper = mount(ModelLicense, { props: { license: 'CC-BY-NC-SA-4.0', permissions: [] } });
    expect(wrapper.find('.name').text()).toBe('CC-BY-NC-SA-4.0');
    expect(wrapper.find('.permissions').exists()).toBe(false);
    await wrapper.setProps({ license: null });
    expect(wrapper.find('section').exists()).toBe(false);
  });

  it('has a translation for every permission the server can send', () => {
    const ids = ['credit', 'sell_images', 'rent', 'generate_on_civitai', 'derivatives', 'sell_model', 'different_license'];
    expect(Object.keys(en.detail.permissions)).toEqual(ids);
    expect(Object.keys(zhCN.detail.permissions)).toEqual(ids);
  });
});
