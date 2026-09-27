import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { computed, ref, toValue } from 'vue';
import FolderTree from '@/components/FolderTree.vue';
import ModelCard from '@/components/ModelCard.vue';
import { AppMenu, IconButton, PathText, SelectField, icons } from '@/ui';
import LibraryView from '@/views/LibraryView.vue';

const queries = vi.hoisted(() => ({ entries: vi.fn(), combined: vi.fn(), replace: vi.fn(), saveFile: vi.fn(), mutations: {} as Record<string, { mutate: ReturnType<typeof vi.fn> }> }));
const library = vi.hoisted(() => ({ settings: { delete_to_trash: true } as Record<string, unknown> }));
vi.mock('@/api/client', () => ({ previewUrl: (root: string, path: string) => `preview:${root}:${path}`, saveFile: queries.saveFile }));
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: queries.replace }),
}));
vi.mock('@tanstack/vue-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
// A plain holder, not a ref: vi.hoisted runs before the imports this file makes.
const roots = vi.hoisted(() => ({ list: [] as Record<string, unknown>[], tree: null as Record<string, unknown> | null }));
vi.mock('@/api/queries/library', async () => {
  const { computed: c, ref: r } = await import('vue');
  return {
    useRoots: () => ({ data: c(() => roots.list), isSuccess: r(true) }),
    useEntries: queries.entries,
    useCombinedEntries: queries.combined,
    useTree: () => ({ data: r(roots.tree) }),
    useLibraryMutations: () => {
      queries.mutations = Object.fromEntries(
        ['rename', 'move', 'remove', 'createFolder', 'importPaths', 'addRoot', 'updateRoot', 'removeRoot', 'scan']
          .map((name) => [name, { isPending: r(false), mutate: vi.fn() }]),
      );
      return queries.mutations;
    },
  };
});
vi.mock('@/api/queries/app', () => ({
  useMeta: () => ({ data: ref({ roots_locked: true, kinds: ['lora'], base_models: [] }) }),
  useSettings: () => ({ data: ref({ library: library.settings }), isError: ref(false) }),
}));
vi.mock('@/stores/preferences', () => ({ usePreferencesStore: () => ({ prefs: { lastRoot: null, libraryView: 'grid' } }) }));
const uploads = vi.hoisted(() => ({ enqueue: vi.fn() }));
vi.mock('@/stores/uploads', () => ({ useUploadsStore: () => ({ onFinished: () => () => {}, enqueue: uploads.enqueue }) }));
vi.mock('@/stores/downloads', () => ({ useDownloadsStore: () => ({ drawerOpen: false }) }));
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, kindLabel: (kind: string) => kind }) }));

beforeEach(() => {
  roots.list = [{ id: 'models', name: 'All models', path: '/models', exists: true }];
  roots.tree = null;
  library.settings = { delete_to_trash: true };
  queries.combined.mockReturnValue({ data: computed(() => undefined), isPending: ref(false), isError: ref(false) });
  queries.saveFile.mockReset();
});

describe('library folder navigation', () => {
  it('keeps folders visible and navigable while a model kind filter is active', async () => {
    queries.entries.mockImplementation((_root, path) => ({
      data: computed(() => ({
        folders: toValue(path) ? [] : [{ name: 'custom-folder', path: 'custom-folder', folder_kind: null }],
        models: [],
        pending_detection: 0,
      })),
      isPending: ref(false),
      isError: ref(false),
    }));
    const wrapper = shallowMount(LibraryView, {
      global: {
        stubs: {
          FileDropZone: { template: '<div><slot /></div>' },
          ModelGrid: { props: ['items'], template: '<div><slot v-for="item in items" :item="item" /></div>' },
        },
      },
    });
    await flushPromises();
    expect(wrapper.find('button.folder').text()).toContain('custom-folder');

    const filter = wrapper.findAllComponents(SelectField).find((field) => field.props('label') === 'library.filterKind')!;
    filter.vm.$emit('update:modelValue', 'lora');
    await flushPromises();
    expect(toValue(queries.entries.mock.calls[0][2])).toBe('lora');
    expect(wrapper.find('button.folder').exists()).toBe(true);

    await wrapper.find('button.folder').trigger('click');
    await flushPromises();
    expect(toValue(queries.entries.mock.calls[0][1])).toBe('custom-folder');
    expect(toValue(queries.entries.mock.calls[0][2])).toBe('lora');
    expect(queries.replace).toHaveBeenLastCalledWith({ query: { root: 'models', path: 'custom-folder' } });
    wrapper.unmount();
  });
});

describe('library roots', () => {
  it('leads with the whole model directory and opens on it, keeping the rest in order', async () => {
    // What an embedding host seeds: one directory per kind, plus the complete directory.
    roots.list = [
      { id: 'loras', name: 'LoRA', path: '/m/loras', exists: true, kind: 'lora' },
      { id: 'vae', name: 'VAE', path: '/m/vae', exists: true, kind: 'vae' },
      { id: 'models', name: 'All models', path: '/m', exists: true, kind: null },
    ];
    queries.entries.mockReturnValue({ data: computed(() => null), isPending: ref(false), isError: ref(false) });
    const wrapper = shallowMount(LibraryView, {
      global: { stubs: { FileDropZone: { template: '<div><slot /></div>' }, ModelGrid: true } },
    });
    await flushPromises();

    const root = wrapper.findAllComponents(SelectField).find((field) => field.props('label') === 'library.root')!;
    expect(root.props('options').map((o: { value: string }) => o.value)).toEqual(['models', 'loras', 'vae']);
    expect(root.props('modelValue')).toBe('models');
    wrapper.unmount();
  });
});

describe('files that are not models', () => {
  it('shows a plain file by its extension with a file icon and no detection badge', async () => {
    queries.entries.mockReturnValue({
      data: computed(() => ({
        folders: [],
        models: [{ name: 'notes.txt', stem: 'notes.txt', path: 'notes.txt', is_dir: false, is_model: false, size: 12, companions: [], mismatch: false, detection: null, sidecar: null }],
        pending_detection: 1,
      })),
      isPending: ref(false),
      isError: ref(false),
    });
    const wrapper = shallowMount(LibraryView, {
      global: {
        stubs: {
          FileDropZone: { template: '<div><slot /></div>' },
          ModelGrid: { props: ['items'], template: '<div><slot v-for="item in items" :item="item" /></div>' },
        },
      },
    });
    await flushPromises();

    const card = wrapper.findComponent(ModelCard);
    expect(card.props('kind')).toBe('TXT');
    expect(card.props('base')).toBe(null);
    expect(card.props('fallbackIcon')).toBe(icons.FileText);
    // A plain file is never detected, so the folder's pending scan must not mark it as pending.
    expect(card.props('pending')).toBe(false);
    wrapper.unmount();
  });
});

describe('uploading from the file picker', () => {
  it('opens the system file dialog and uploads what was chosen into the folder on screen', async () => {
    queries.entries.mockReturnValue({ data: computed(() => ({ folders: [], models: [], pending_detection: 0 })), isPending: ref(false), isError: ref(false) });
    const wrapper = shallowMount(LibraryView, {
      global: { stubs: { FileDropZone: { template: '<div><slot /></div>' }, ModelGrid: true } },
    });
    await flushPromises();
    const menu = wrapper.findAllComponents(AppMenu).find((c) => (c.props('items') as { id: string }[]).some((i) => i.id === 'files'))!;

    // Spied on only now: while the view renders, Vue creates elements of its own.
    const input = document.createElement('input');
    const click = vi.spyOn(input, 'click').mockImplementation(() => {});
    const create = vi.spyOn(document, 'createElement').mockReturnValue(input);
    menu.vm.$emit('select', 'files');
    create.mockRestore();
    expect(click).toHaveBeenCalled();
    expect(input.multiple).toBe(true);
    expect(input.webkitdirectory).toBeFalsy();

    const file = new File(['x'], 'model.safetensors');
    Object.defineProperty(input, 'files', { value: [file] });
    input.dispatchEvent(new Event('change'));
    expect(uploads.enqueue).toHaveBeenCalledWith('models', '', [{ file, relativePath: 'model.safetensors' }]);
    wrapper.unmount();
  });

  it('asks for a whole folder when that is what was chosen', async () => {
    queries.entries.mockReturnValue({ data: computed(() => ({ folders: [], models: [], pending_detection: 0 })), isPending: ref(false), isError: ref(false) });
    const wrapper = shallowMount(LibraryView, {
      global: { stubs: { FileDropZone: { template: '<div><slot /></div>' }, ModelGrid: true } },
    });
    await flushPromises();
    const menu = wrapper.findAllComponents(AppMenu).find((c) => (c.props('items') as { id: string }[]).some((i) => i.id === 'folder'))!;

    const input = document.createElement('input');
    vi.spyOn(input, 'click').mockImplementation(() => {});
    const create = vi.spyOn(document, 'createElement').mockReturnValue(input);
    menu.vm.$emit('select', 'folder');
    create.mockRestore();
    expect(input.webkitdirectory).toBe(true);
    wrapper.unmount();
  });
});

const model = (name: string, extra: Record<string, unknown> = {}) => ({
  name,
  stem: name.replace(/\.[^.]+$/, ''),
  path: name,
  is_dir: false,
  is_model: true,
  size: 1,
  companions: [],
  mismatch: false,
  detection: null,
  sidecar: null,
  preview: null,
  ...extra,
});

function mountWithItems() {
  return shallowMount(LibraryView, {
    global: {
      stubs: {
        FileDropZone: { props: ['disabled'], template: '<div :data-disabled="disabled"><slot /></div>' },
        ModelGrid: { props: ['items'], template: '<div><slot v-for="item in items" :item="item" /></div>' },
        // Renders its slots, where the per-model menu lives.
        ModelCard: {
          props: ['layout', 'title', 'subtitle', 'preview', 'fallbackIcon', 'kind', 'base', 'warning', 'pending', 'selected'],
          template: '<div><slot name="select" /><slot name="actions" /></div>',
        },
      },
    },
  });
}

describe('all folders', () => {
  beforeEach(() => {
    roots.list = [
      { id: 'comfy', name: 'ComfyUI', path: '/srv/comfy/models', exists: true, kind: null },
      { id: 'forge', name: 'Forge', path: '/srv/forge', exists: true, kind: null },
    ];
    queries.entries.mockReturnValue({ data: computed(() => ({ root_id: 'forge', folders: [], models: [], pending_detection: 0 })), isPending: ref(false), isError: ref(false) });
    queries.combined.mockReturnValue({
      data: computed(() => ({
        folders: [
          { name: 'loras', path: 'loras', folder_kind: 'lora', root_id: 'comfy', root_name: 'ComfyUI', label: 'loras (ComfyUI)', is_root: false },
          { name: 'loras', path: 'models/Lora', folder_kind: 'lora', root_id: 'forge', root_name: 'Forge', label: 'loras (Forge)', is_root: false },
          // A root with files at its top level, kept whole under its directory's name.
          { name: 'Lora', path: '', folder_kind: 'lora', root_id: 'webui-lora', root_name: 'loras (2)', label: 'Lora', is_root: true },
        ],
        missing_roots: [],
      })),
      isPending: ref(false),
      isError: ref(false),
    });
  });

  it('is not offered while the setting is off', async () => {
    const wrapper = mountWithItems();
    await flushPromises();
    const root = wrapper.findAllComponents(SelectField).find((field) => field.props('label') === 'library.root')!;
    expect(root.props('options').map((o: { value: string }) => o.value)).toEqual(['comfy', 'forge']);
    expect(root.props('modelValue')).toBe('comfy');
    expect(toValue(queries.combined.mock.calls.at(-1)![0])).toBe(false);
    wrapper.unmount();
  });

  it('leads the root list when on, opens first, and lists every root side by side', async () => {
    library.settings = { delete_to_trash: true, combined_view: true };
    const wrapper = mountWithItems();
    await flushPromises();
    const root = wrapper.findAllComponents(SelectField).find((field) => field.props('label') === 'library.root')!;
    expect(root.props('options').map((o: { value: string }) => o.value)).toEqual(['*', 'comfy', 'forge']);
    expect(root.props('modelValue')).toBe('*');
    expect(toValue(queries.combined.mock.calls.at(-1)![0])).toBe(true);
    // The per-root listing is not asked for a root called "*".
    expect(toValue(queries.entries.mock.calls.at(-1)![0])).toBe(null);

    const folders = wrapper.findAll('button.folder');
    expect(folders.map((b) => b.find('.folder-name').text())).toEqual(['loras (ComfyUI)', 'loras (Forge)', 'Lora']);
    expect(folders[2].find('.folder-meta').text()).toContain('loras (2)');
    // Folders only: no file is ever loose in "All folders", and the kind filter has nothing to filter.
    expect(wrapper.findComponent(ModelCard).exists()).toBe(false);
    expect(wrapper.findAllComponents(SelectField).some((field) => field.props('label') === 'library.filterKind')).toBe(false);
    // Nothing can be created or dropped where there is no single folder to put it in.
    expect(wrapper.find('[data-disabled="true"]').exists()).toBe(true);
    expect(wrapper.findAllComponents(AppMenu).some((c) => (c.props('items') as { id: string }[]).some((i) => i.id === 'files'))).toBe(false);
    wrapper.unmount();
  });

  it('opens a folder in its own root and acts on items with their own root', async () => {
    library.settings = { delete_to_trash: true, combined_view: true };
    const wrapper = mountWithItems();
    await flushPromises();

    const folders = wrapper.findAll('button.folder');
    // A whole root has no rename, move or delete; a folder inside one does, against its own root.
    expect(folders[2].findComponent(AppMenu).exists()).toBe(false);
    folders[1].findComponent(AppMenu).vm.$emit('select', 'delete');
    await flushPromises();
    const confirm = wrapper.findAllComponents({ name: 'ConfirmDialog' }).find((c) => c.props('title') === 'library.deleteTitle')!;
    confirm.vm.$emit('confirm');
    expect(queries.mutations.remove.mutate.mock.calls[0][0]).toEqual({ items: [{ root_id: 'forge', path: 'models/Lora' }], permanent: false });

    await folders[1].trigger('click');
    await flushPromises();
    expect(queries.replace).toHaveBeenLastCalledWith({ query: { root: 'forge', path: 'models/Lora' } });
    wrapper.unmount();
  });

  it('opens a whole root at its top', async () => {
    library.settings = { delete_to_trash: true, combined_view: true };
    roots.list = [...roots.list, { id: 'webui-lora', name: 'loras (2)', path: '/srv/webui/models/Lora', exists: true, kind: 'lora' }];
    const wrapper = mountWithItems();
    await flushPromises();
    await wrapper.findAll('button.folder')[2].trigger('click');
    await flushPromises();
    expect(queries.replace).toHaveBeenLastCalledWith({ query: { root: 'webui-lora', path: undefined } });
    wrapper.unmount();
  });

  it('keeps a way back from inside a root', async () => {
    library.settings = { delete_to_trash: true, combined_view: true };
    queries.replace.mockReset();
    const wrapper = mountWithItems();
    await flushPromises();
    await wrapper.findAll('button.folder')[0].trigger('click');
    await flushPromises();
    const crumbs = wrapper.findComponent({ name: 'Breadcrumbs' });
    expect(crumbs.props('crumbs').map((c: { label: string }) => c.label)).toEqual(['library.allFolders', 'ComfyUI', 'loras']);
    crumbs.vm.$emit('navigate', crumbs.props('crumbs')[0].value);
    await flushPromises();
    expect(queries.replace).toHaveBeenLastCalledWith({ query: { root: '*', path: undefined } });
    wrapper.unmount();
  });
});

describe('downloading a file', () => {
  it('offers a file for download through the browser, and not a diffusers folder', async () => {
    queries.entries.mockReturnValue({
      data: computed(() => ({ folders: [], models: [model('a.safetensors'), model('pipe', { is_dir: true })], pending_detection: 0 })),
      isPending: ref(false),
      isError: ref(false),
    });
    const wrapper = mountWithItems();
    await flushPromises();
    const menus = wrapper.findAllComponents(AppMenu).filter((c) => (c.props('items') as { id: string }[]).some((i) => i.id === 'info'));
    expect(menus.map((c) => (c.props('items') as { id: string }[]).some((i) => i.id === 'download'))).toEqual([true, false]);
    menus[0].vm.$emit('select', 'download');
    expect(queries.saveFile).toHaveBeenCalledWith('models', 'a.safetensors');
    wrapper.unmount();
  });
});

describe('the root path', () => {
  it('keeps its leading slash on screen', async () => {
    roots.list = [{ id: 'models', name: 'All models', path: '/root/model', exists: true }];
    queries.entries.mockReturnValue({ data: computed(() => ({ folders: [], models: [], pending_detection: 0 })), isPending: ref(false), isError: ref(false) });
    const wrapper = mountWithItems();
    await flushPromises();
    expect(wrapper.findComponent(PathText).props('path')).toBe('/root/model');
    wrapper.unmount();
  });
});

describe('the folder panel on a narrow screen', () => {
  it('starts closed, opens from its button and closes again once a folder is picked', async () => {
    const narrow = vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true, addEventListener: () => {}, removeEventListener: () => {} } as unknown as MediaQueryList);
    roots.tree = { name: 'All models', path: '', folder_kind: null, children: [{ name: 'loras', path: 'loras', folder_kind: 'lora', children: [] }] };
    queries.entries.mockReturnValue({ data: computed(() => ({ folders: [], models: [], pending_detection: 0 })), isPending: ref(false), isError: ref(false) });
    onTestFinished(() => narrow.mockRestore());
    const wrapper = shallowMount(LibraryView, {
      global: { stubs: { FileDropZone: { template: '<div><slot /></div>' }, ModelGrid: true } },
    });
    await flushPromises();
    const shown = () => wrapper.find('.side-wrap').attributes('style') !== 'display: none;';
    const toggle = () => wrapper.findAllComponents(IconButton).find((b) => b.classes('side-toggle'))!;

    expect(wrapper.classes()).toContain('stacked');
    expect(shown()).toBe(false);
    expect(toggle().props('expanded')).toBe(false);

    toggle().vm.$emit('click', new MouseEvent('click'));
    await flushPromises();
    expect(shown()).toBe(true);
    expect(toggle().props('label')).toBe('library.hideFolders');

    wrapper.findComponent(FolderTree).vm.$emit('select', 'loras');
    await flushPromises();
    expect(shown()).toBe(false);
    expect(toValue(queries.entries.mock.lastCall![1])).toBe('loras');
    wrapper.unmount();
  });

  it('stays beside the contents, with no button, on a wide screen', async () => {
    queries.entries.mockReturnValue({ data: computed(() => null), isPending: ref(false), isError: ref(false) });
    const wrapper = shallowMount(LibraryView, {
      global: { stubs: { FileDropZone: { template: '<div><slot /></div>' }, ModelGrid: true } },
    });
    await flushPromises();
    expect(wrapper.classes()).not.toContain('stacked');
    expect(wrapper.find('.side-wrap').attributes('style')).toBeUndefined();
    expect(wrapper.findAllComponents(IconButton).some((b) => b.classes('side-toggle'))).toBe(false);
    wrapper.unmount();
  });
});
