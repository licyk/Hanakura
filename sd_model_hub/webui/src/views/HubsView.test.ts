import { flushPromises, shallowMount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { computed, ref } from 'vue';
import { ExpansionPanel, TRANSITIONS } from '@/ui';
import HubsView from '@/views/HubsView.vue';

// A plain holder, not a ref: vi.hoisted runs before the imports this file makes.
const repo = vi.hoisted(() => ({ id: null as { value: string | null } | null, detail: null as Record<string, unknown> | null }));
vi.mock('@/api/queries/hubs', () => ({
  useHubs: () => ({ data: ref([{ id: 'huggingface', name: 'Hugging Face', sorts: [] }]) }),
  useRepoSearch: () => ({
    data: ref({ pages: [{ items: [{ id: 'owner/one' }, { id: 'owner/two' }] }] }),
    isPending: ref(false),
    isError: ref(false),
    error: ref(null),
    hasNextPage: ref(false),
    isFetchingNextPage: ref(false),
    fetchNextPage: vi.fn(),
  }),
  useRepo: (_hub: unknown, id: { value: string | null }) => {
    repo.id = id;
    return { data: computed(() => (id.value ? repo.detail : null)), isPending: ref(false), isError: ref(false), error: ref(null) };
  },
}));
vi.mock('@/api/queries/downloads', () => ({ useCreateDownload: () => ({ mutate: vi.fn(), isPending: ref(false) }) }));
vi.mock('@/stores/downloads', () => ({ useDownloadsStore: () => ({ drawerOpen: false }) }));
vi.mock('@/stores/preferences', () => ({ usePreferencesStore: () => ({ prefs: { lastHub: 'huggingface' } }) }));
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: ref('en') }) }));

// shallowMount keeps @material/web out of happy-dom; the rows and the pane are plain markup.
// The transition stub writes its name into the DOM so the motion can be asserted.
function view() {
  return shallowMount(HubsView, {
    global: {
      stubs: {
        ModelGrid: { props: ['items'], template: '<div><slot v-for="item in items" :item="item" /></div>' },
        transition: { props: ['name'], template: '<div :data-transition="name"><slot /></div>' },
      },
    },
  });
}

const transitions = (wrapper: ReturnType<typeof view>) => wrapper.findAll('[data-transition]').map((el) => el.attributes('data-transition'));

describe('opening a repository', () => {
  it('moves the pane in and out with the motion system rather than swapping it in', async () => {
    const wrapper = view();
    await flushPromises();
    expect(wrapper.find('.repo-pane').exists()).toBe(false);

    await wrapper.find('.repo-row').trigger('click');
    await flushPromises();
    const pane = wrapper.find('.repo-pane');
    expect(pane.exists()).toBe(true);
    // The pane arrives from the right, and its content is keyed so another repository fades through.
    expect(transitions(wrapper)).toContain(TRANSITIONS.sharedAxisX);
    expect(transitions(wrapper)).toContain(TRANSITIONS.fadeThrough);
    expect(pane.attributes('style')).toContain('--axis-dir: 1');
    expect(wrapper.find('.panes').classes()).toContain('has-repo');
  });

  it('closes from the pane header at any width, leaving in the other direction', async () => {
    const wrapper = view();
    await flushPromises();
    await wrapper.find('.repo-row').trigger('click');
    await flushPromises();

    // The close control used to be hidden above 899px, which left no way back to the full list.
    const close = wrapper.find('.repo-head .back');
    expect(close.exists()).toBe(true);
    await close.trigger('click');
    await flushPromises();
    expect(repo.id!.value).toBeNull();
    expect(wrapper.find('.repo-pane').exists()).toBe(false);
  });
});

describe('the model card', () => {
  it('opens expanded for every repository, even after it was collapsed for the last one', async () => {
    repo.detail = { id: 'owner/one', revision: 'main', files: [], description: '# Card', page_url: 'https://example.com', total_size: 0, last_modified: null, license: null };
    const wrapper = view();
    await flushPromises();
    await wrapper.find('.repo-row').trigger('click');
    await flushPromises();
    const panel = () => wrapper.findComponent(ExpansionPanel);
    expect(panel().props('open')).toBe(true);

    panel().vm.$emit('update:open', false);
    await flushPromises();
    expect(panel().props('open')).toBe(false);

    await wrapper.findAll('.repo-row')[1].trigger('click');
    await flushPromises();
    expect(panel().props('open')).toBe(true);
    repo.detail = null;
  });
});
