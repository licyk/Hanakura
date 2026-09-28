import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { computed, ref, toValue } from 'vue';
import FolderTree from '@/components/FolderTree.vue';
import ModelCard from '@/components/ModelCard.vue';
import MoveDialog from '@/components/MoveDialog.vue';
import SelectionBar from '@/components/SelectionBar.vue';
import { AppMenu, Breadcrumbs, IconButton, PathText, SelectField, icons } from '@/ui';
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

  it('gives each folder a tree of its own, marked with its root, that opens in that root', async () => {
    library.settings = { delete_to_trash: true, combined_view: true };
    const wrapper = mountWithItems();
    await flushPromises();
    const trees = wrapper.findAllComponents(FolderTree);
    expect(trees.map((tree) => [tree.props('node').name, tree.props('label'), tree.props('rootId')])).toEqual([
      ['loras', 'ComfyUI', 'comfy'],
      ['loras', 'Forge', 'forge'],
      ['Lora', 'loras (2)', 'webui-lora'],
    ]);
    // Nothing in "All folders" is the current folder, and every tree starts closed.
    expect(trees.every((tree) => tree.props('selected') === null && tree.props('open') === false)).toBe(true);

    trees[1].vm.$emit('select', 'models/Lora/sdxl');
    await flushPromises();
    expect(queries.replace).toHaveBeenLastCalledWith({ query: { root: 'forge', path: 'models/Lora/sdxl' } });
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
  function mountNarrow() {
    const narrow = vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true, addEventListener: () => {}, removeEventListener: () => {} } as unknown as MediaQueryList);
    onTestFinished(() => narrow.mockRestore());
    roots.tree = { name: 'All models', path: '', folder_kind: null, children: [{ name: 'loras', path: 'loras', folder_kind: 'lora', children: [] }] };
    queries.entries.mockReturnValue({ data: computed(() => ({ folders: [], models: [], pending_detection: 0 })), isPending: ref(false), isError: ref(false) });
    return shallowMount(LibraryView, {
      attachTo: document.body,
      global: { stubs: { FileDropZone: { template: '<div><slot /></div>' }, ModelGrid: true } },
    });
  }
  const toggleOf = (wrapper: ReturnType<typeof mountNarrow>) => wrapper.findAllComponents(IconButton).find((b) => b.classes('side-toggle'))!;
  async function open(wrapper: ReturnType<typeof mountNarrow>) {
    toggleOf(wrapper).vm.$emit('click', new MouseEvent('click'));
    await flushPromises();
  }

  it('is a drawer over the contents: closed at first, opened by its button, closed by a picked folder', async () => {
    const wrapper = mountNarrow();
    await flushPromises();

    expect(wrapper.classes()).toContain('narrow');
    expect(wrapper.find('aside.side').exists()).toBe(false);
    expect(toggleOf(wrapper).props('expanded')).toBe(false);

    await open(wrapper);
    expect(wrapper.find('aside.side').classes()).toContain('overlay');
    expect(wrapper.find('.scrim').exists()).toBe(true);
    expect(toggleOf(wrapper).props('label')).toBe('library.hideFolders');
    expect(toggleOf(wrapper).props('icon')).toBe(icons.FolderOpen);

    wrapper.findComponent(FolderTree).vm.$emit('select', 'loras');
    await flushPromises();
    expect(wrapper.find('aside.side').exists()).toBe(false);
    expect(toValue(queries.entries.mock.lastCall![1])).toBe('loras');
    wrapper.unmount();
  });

  it('closes on its scrim and on Escape', async () => {
    const wrapper = mountNarrow();
    await flushPromises();
    await open(wrapper);
    await wrapper.find('.scrim').trigger('click');
    expect(wrapper.find('aside.side').exists()).toBe(false);

    await open(wrapper);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await flushPromises();
    expect(wrapper.find('aside.side').exists()).toBe(false);
    wrapper.unmount();
  });

  it('stays beside the contents, with no button or scrim, on a wide screen', async () => {
    queries.entries.mockReturnValue({ data: computed(() => null), isPending: ref(false), isError: ref(false) });
    const wrapper = shallowMount(LibraryView, {
      global: { stubs: { FileDropZone: { template: '<div><slot /></div>' }, ModelGrid: true } },
    });
    await flushPromises();
    expect(wrapper.classes()).not.toContain('narrow');
    expect(wrapper.find('aside.side').classes()).not.toContain('overlay');
    expect(wrapper.find('.scrim').exists()).toBe(false);
    expect(wrapper.findAllComponents(IconButton).some((b) => b.classes('side-toggle'))).toBe(false);
    wrapper.unmount();
  });
});

describe('going up', () => {
  const upButton = (wrapper: ReturnType<typeof mountWithItems>) => wrapper.findAllComponents(IconButton).find((b) => b.classes('up'))!;

  it('leads to the parent folder, and is off at the top of a root', async () => {
    queries.entries.mockReturnValue({ data: computed(() => ({ folders: [{ name: 'sdxl', path: 'loras/sdxl', folder_kind: null }], models: [], pending_detection: 0 })), isPending: ref(false), isError: ref(false) });
    const wrapper = mountWithItems();
    await flushPromises();
    expect(upButton(wrapper).props('disabled')).toBe(true);

    await wrapper.find('button.folder').trigger('click');
    await flushPromises();
    expect(upButton(wrapper).props('disabled')).toBe(false);
    upButton(wrapper).vm.$emit('click', new MouseEvent('click'));
    await flushPromises();
    expect(queries.replace).toHaveBeenLastCalledWith({ query: { root: 'models', path: 'loras' } });
    wrapper.unmount();
  });

  it('leads from the top of a root to "All folders" when it is offered', async () => {
    library.settings = { delete_to_trash: true, combined_view: true };
    queries.entries.mockReturnValue({ data: computed(() => ({ folders: [], models: [], pending_detection: 0 })), isPending: ref(false), isError: ref(false) });
    const wrapper = mountWithItems();
    await flushPromises();
    // "All folders" is the top: nothing above it.
    expect(upButton(wrapper).props('disabled')).toBe(true);
    wrapper.findAllComponents(SelectField).find((field) => field.props('label') === 'library.root')!.vm.$emit('update:modelValue', 'models');
    await flushPromises();
    upButton(wrapper).vm.$emit('click', new MouseEvent('click'));
    await flushPromises();
    expect(queries.replace).toHaveBeenLastCalledWith({ query: { root: '*', path: undefined } });
    wrapper.unmount();
  });
});

describe('dragging to move', () => {
  /** A stand-in for the browser's DataTransfer, which the test DOM does not provide. */
  class Transfer {
    data = new Map<string, string>();
    dropEffect = 'none';
    effectAllowed = 'all';
    get types() {
      return [...this.data.keys()];
    }
    setData(type: string, value: string) {
      this.data.set(type, value);
    }
    getData(type: string) {
      return this.data.get(type) ?? '';
    }
  }

  beforeEach(() => {
    queries.entries.mockReturnValue({
      data: computed(() => ({
        folders: [{ name: 'loras', path: 'loras', folder_kind: 'lora' }, { name: 'vae', path: 'vae', folder_kind: 'vae' }],
        models: [model('a.safetensors'), model('b.safetensors')],
        pending_detection: 0,
      })),
      isPending: ref(false),
      isError: ref(false),
    });
  });

  it('moves a card dropped on a folder, with the rest of the selection when it is part of it', async () => {
    roots.tree = { name: 'All models', path: '', folder_kind: null, children: [{ name: 'vae', path: 'vae', folder_kind: 'vae', children: [] }] };
    const wrapper = mountWithItems();
    await flushPromises();
    const cards = wrapper.findAllComponents(ModelCard);
    const folders = wrapper.findAll('button.folder');

    const alone = new Transfer();
    await cards[0].trigger('dragstart', { dataTransfer: alone });
    await folders[0].trigger('dragover', { dataTransfer: alone });
    expect(folders[0].classes()).toContain('dropping');
    await folders[0].trigger('drop', { dataTransfer: alone });
    expect(folders[0].classes()).not.toContain('dropping');
    expect(queries.mutations.move.mutate.mock.calls[0][0]).toEqual({ items: [{ root_id: 'models', path: 'a.safetensors' }], dest_root_id: 'models', dest_dir: 'loras', on_conflict: 'error' });

    cards[0].findComponent({ name: 'Checkbox' }).vm.$emit('update:modelValue', true);
    cards[1].findComponent({ name: 'Checkbox' }).vm.$emit('update:modelValue', true);
    await flushPromises();
    const both = new Transfer();
    await cards[1].trigger('dragstart', { dataTransfer: both });
    await wrapper.findComponent(FolderTree).vm.$emit('drop', { dataTransfer: both, preventDefault: () => {} }, 'vae');
    expect(queries.mutations.move.mutate.mock.calls[1][0].items).toEqual([
      { root_id: 'models', path: 'a.safetensors' },
      { root_id: 'models', path: 'b.safetensors' },
    ]);
    expect(queries.mutations.move.mutate.mock.calls[1][0].dest_dir).toBe('vae');
    wrapper.unmount();
  });

  it('never moves a folder into itself', async () => {
    const wrapper = mountWithItems();
    await flushPromises();
    const folder = wrapper.findAll('button.folder')[0];
    const transfer = new Transfer();
    await folder.trigger('dragstart', { dataTransfer: transfer });
    await folder.trigger('drop', { dataTransfer: transfer });
    expect(queries.mutations.move.mutate).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('cannot drag a whole root out of "All folders", but drops into one', async () => {
    library.settings = { delete_to_trash: true, combined_view: true };
    roots.list = [{ id: 'models', name: 'All models', path: '/models', exists: true, kind: null }];
    queries.combined.mockReturnValue({
      data: computed(() => ({ folders: [{ name: 'Lora', path: '', folder_kind: 'lora', root_id: 'lora-root', root_name: 'Lora', label: 'Lora', is_root: true }], missing_roots: [] })),
      isPending: ref(false),
      isError: ref(false),
    });
    const wrapper = mountWithItems();
    await flushPromises();
    const whole = wrapper.find('button.folder');
    expect(whole.attributes('draggable')).toBe('false');
    const transfer = new Transfer();
    transfer.setData('application/x-sd-model-hub-refs', JSON.stringify([{ root_id: 'models', path: 'a.safetensors' }]));
    await whole.trigger('drop', { dataTransfer: transfer });
    expect(queries.mutations.move.mutate.mock.calls[0][0]).toMatchObject({ items: [{ root_id: 'models', path: 'a.safetensors' }], dest_root_id: 'lora-root', dest_dir: '' });
    wrapper.unmount();
  });
});

describe('selection mode', () => {
  beforeEach(() => {
    queries.entries.mockReturnValue({
      data: computed(() => ({
        folders: [{ name: 'loras', path: 'loras', folder_kind: 'lora' }],
        models: [model('a.safetensors'), model('b.safetensors')],
        pending_detection: 0,
      })),
      isPending: ref(false),
      isError: ref(false),
    });
  });
  const bar = (wrapper: ReturnType<typeof mountWithItems>) => wrapper.findComponent(SelectionBar);
  const check = async (card: ReturnType<ReturnType<typeof mountWithItems>['findComponent']>) => {
    card.findComponent({ name: 'Checkbox' }).vm.$emit('update:modelValue', true);
    await flushPromises();
  };
  const menuOf = (wrapper: ReturnType<typeof mountWithItems>, index: number) => wrapper.findAllComponents(ModelCard)[index].findComponent(AppMenu);
  const ids = (menu: ReturnType<typeof menuOf>) => (menu.props('items') as { id: string }[]).map((i) => i.id);

  it('adds a bar of its own below the toolbar, which stays as it was', async () => {
    const wrapper = mountWithItems();
    await flushPromises();
    expect(bar(wrapper).props('count')).toBe(0);
    await check(wrapper.findAllComponents(ModelCard)[0]);

    expect(bar(wrapper).props()).toMatchObject({ count: 1, total: 3 });
    expect(wrapper.findAllComponents(ModelCard).every((card) => card.attributes('selecting') === 'true')).toBe(true);
    // The toolbar's own actions do not give way to the selection's.
    expect(wrapper.findAllComponents(AppMenu).some((c) => (c.props('items') as { id: string }[]).some((i) => i.id === 'files'))).toBe(true);

    bar(wrapper).vm.$emit('selectAll');
    await flushPromises();
    expect(bar(wrapper).props('count')).toBe(3);
    bar(wrapper).vm.$emit('delete');
    await flushPromises();
    wrapper.findAllComponents({ name: 'ConfirmDialog' }).find((c) => c.props('title') === 'library.deleteTitle')!.vm.$emit('confirm');
    expect(queries.mutations.remove.mutate.mock.calls[0][0].items).toHaveLength(3);

    bar(wrapper).vm.$emit('clear');
    await flushPromises();
    expect(bar(wrapper).props('count')).toBe(0);
    wrapper.unmount();
  });

  it('toggles an item on a click instead of opening it', async () => {
    const wrapper = mountWithItems();
    await flushPromises();
    await check(wrapper.findAllComponents(ModelCard)[0]);

    wrapper.findAllComponents(ModelCard)[1].vm.$emit('activate', null);
    await wrapper.find('button.folder').trigger('click');
    await flushPromises();
    expect(bar(wrapper).props('count')).toBe(3);
    expect(wrapper.findComponent({ name: 'ModelInfoDialog' }).props('open')).toBe(false);
    expect(toValue(queries.entries.mock.lastCall![1])).toBe('');
    expect(wrapper.find('button.folder').classes()).toContain('checked');
    wrapper.unmount();
  });

  it('turns the menu of a selected item into one for the whole selection', async () => {
    const wrapper = mountWithItems();
    await flushPromises();
    expect(ids(menuOf(wrapper, 0))[0]).toBe('select');

    menuOf(wrapper, 0).vm.$emit('select', 'select');
    await check(wrapper.findAllComponents(ModelCard)[1]);
    expect(ids(menuOf(wrapper, 0))).toEqual(['move', 'delete', 'deselect']);
    expect((menuOf(wrapper, 0).props('items') as { label: string }[])[0].label).toBe('library.moveItems');

    menuOf(wrapper, 1).vm.$emit('select', 'move');
    await flushPromises();
    expect(wrapper.findComponent(MoveDialog).props('count')).toBe(2);

    menuOf(wrapper, 0).vm.$emit('select', 'deselect');
    await flushPromises();
    // One left: its menu is its own again.
    expect(ids(menuOf(wrapper, 1))).toContain('info');
    wrapper.unmount();
  });

  it('is cleared by opening another folder, unless it is kept', async () => {
    const wrapper = mountWithItems();
    await flushPromises();
    await check(wrapper.findAllComponents(ModelCard)[0]);
    bar(wrapper).vm.$emit('update:keep', true);
    wrapper.findComponent(Breadcrumbs).vm.$emit('navigate', 'loras');
    await flushPromises();
    expect(bar(wrapper).props('count')).toBe(1);

    bar(wrapper).vm.$emit('update:keep', false);
    wrapper.findComponent(Breadcrumbs).vm.$emit('navigate', '');
    await flushPromises();
    expect(bar(wrapper).props('count')).toBe(0);
    wrapper.unmount();
  });
});

describe('the keyboard and modifier clicks', () => {
  beforeEach(() => {
    queries.entries.mockReturnValue({
      data: computed(() => ({
        folders: [{ name: 'loras', path: 'loras', folder_kind: 'lora' }],
        models: [model('a.safetensors'), model('b.safetensors'), model('c.safetensors')],
        pending_detection: 0,
      })),
      isPending: ref(false),
      isError: ref(false),
    });
  });

  /** The grid laid out as the real one is: cells holding each item's own focusable element. */
  function mountGrid() {
    return shallowMount(LibraryView, {
      attachTo: document.body,
      global: {
        stubs: {
          FileDropZone: { template: '<div><slot /></div>' },
          ModelGrid: { props: ['items'], template: '<div class="model-grid"><div v-for="item in items" class="cell"><slot :item="item" /></div></div>' },
          ModelCard: {
            props: ['layout', 'title', 'subtitle', 'preview', 'fallbackIcon', 'kind', 'base', 'warning', 'pending', 'selected', 'selecting'],
            template: '<article tabindex="0" class="card"><slot name="select" /><slot name="actions" /></article>',
          },
        },
      },
    });
  }
  const own = (wrapper: ReturnType<typeof mountGrid>) => wrapper.findAll('.model-grid > .cell').map((cell) => cell.element.firstElementChild as HTMLElement);
  const press = async (target: HTMLElement, key: string, mods: KeyboardEventInit = {}) => {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...mods }));
    await flushPromises();
  };
  const count = (wrapper: ReturnType<typeof mountGrid>) => wrapper.findComponent(SelectionBar).props('count');

  it('moves the focus with the arrows and selects the way with Shift', async () => {
    const wrapper = mountGrid();
    await flushPromises();
    const cells = own(wrapper);
    cells[1].focus();
    await press(cells[1], 'ArrowRight');
    expect(document.activeElement).toBe(cells[2]);
    await press(cells[2], 'Home');
    expect(document.activeElement).toBe(cells[0]);

    cells[1].focus();
    await press(cells[1], 'ArrowRight', { shiftKey: true });
    await press(cells[2], 'ArrowRight', { shiftKey: true });
    expect(count(wrapper)).toBe(3);
    wrapper.unmount();
  });

  it('toggles with Space, selects all, clears with Escape, and deletes the selection', async () => {
    const wrapper = mountGrid();
    await flushPromises();
    const cells = own(wrapper);
    await press(cells[1], ' ');
    expect(count(wrapper)).toBe(1);
    await press(cells[1], 'a', { ctrlKey: true });
    expect(count(wrapper)).toBe(4);
    await press(cells[1], 'Delete');
    expect(wrapper.findAllComponents({ name: 'ConfirmDialog' }).find((c) => c.props('title') === 'library.deleteTitle')!.props('open')).toBe(true);
    await press(cells[1], 'Escape');
    expect(count(wrapper)).toBe(0);
    wrapper.unmount();
  });

  it('opens with Enter even while selecting, and goes up with Backspace', async () => {
    const wrapper = mountGrid();
    await flushPromises();
    await press(own(wrapper)[2], ' ');
    await press(own(wrapper)[1], 'Enter');
    expect(wrapper.findComponent({ name: 'ModelInfoDialog' }).props()).toMatchObject({ open: true, path: 'a.safetensors' });

    await press(own(wrapper)[0], 'Enter');
    expect(toValue(queries.entries.mock.lastCall![1])).toBe('loras');
    await press(own(wrapper)[0], 'Backspace');
    expect(toValue(queries.entries.mock.lastCall![1])).toBe('');
    wrapper.unmount();
  });

  it('leaves the keys of an item’s own controls alone', async () => {
    const wrapper = mountGrid();
    await flushPromises();
    const menu = wrapper.findAllComponents(ModelCard)[0].findComponent(AppMenu).element as HTMLElement;
    expect(own(wrapper)[1].contains(menu)).toBe(true);
    await press(menu, ' ');
    await press(menu, 'Delete');
    expect(count(wrapper)).toBe(0);
    expect(wrapper.findAllComponents({ name: 'ConfirmDialog' }).find((c) => c.props('title') === 'library.deleteTitle')!.props('open')).toBe(false);
    wrapper.unmount();
  });

  it('toggles on a Ctrl-click and takes a range on a Shift-click, opening nothing', async () => {
    const wrapper = mountGrid();
    await flushPromises();
    const cards = wrapper.findAllComponents(ModelCard);
    cards[0].vm.$emit('activate', null, new MouseEvent('click', { ctrlKey: true }));
    cards[2].vm.$emit('activate', null, new MouseEvent('click', { shiftKey: true }));
    await flushPromises();
    expect(count(wrapper)).toBe(3);
    await wrapper.find('button.folder').trigger('click', { metaKey: true });
    expect(count(wrapper)).toBe(4);
    expect(wrapper.findComponent({ name: 'ModelInfoDialog' }).props('open')).toBe(false);
    expect(toValue(queries.entries.mock.lastCall![1])).toBe('');
    wrapper.unmount();
  });
});
