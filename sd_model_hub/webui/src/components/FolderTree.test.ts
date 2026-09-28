import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { toValue } from 'vue';
import FolderTree from '@/components/FolderTree.vue';
import { DRAG_TYPE } from '@/components/libraryDrag';

const tree = vi.hoisted(() => ({ calls: [] as unknown[][], data: null as Record<string, unknown> | null }));
vi.mock('@/api/queries/library', async () => {
  const { computed, ref: r, toValue: value } = await import('vue');
  return {
    useTree: (...args: unknown[]) => {
      tree.calls.push(args);
      // The root's tree arrives once the query is enabled, as vue-query would fetch it.
      return { data: computed(() => (value(args[1] as boolean) ? tree.data : undefined)), isError: r(false) };
    },
  };
});

const node = (name: string, path: string, children: unknown[] = []) => ({ name, path, folder_kind: null, children });

beforeEach(() => {
  tree.calls = [];
  tree.data = node('ComfyUI', '', [node('loras', 'loras', [node('sdxl', 'loras/sdxl'), node('flux', 'loras/flux')]), node('vae', 'vae')]);
});

describe('a folder tree', () => {
  it('holds its children itself when it is part of a whole tree', async () => {
    const wrapper = mount(FolderTree, { props: { node: tree.data as never, selected: 'loras/sdxl' } });
    await flushPromises();
    expect(tree.calls).toEqual([]);
    expect(wrapper.findAll('.name').map((n) => n.text())).toEqual(['ComfyUI', 'loras', 'sdxl', 'flux', 'vae']);
    expect(wrapper.find('.row.active .name').text()).toBe('sdxl');
  });

  it('loads a standalone folder’s subfolders from its root only once opened, with its label beside it', async () => {
    const wrapper = mount(FolderTree, { props: { node: node('loras', 'loras') as never, rootId: 'comfy', label: 'ComfyUI', selected: null, open: false } });
    await flushPromises();
    expect(toValue(tree.calls[0][0] as () => string)).toBe('comfy');
    expect(toValue(tree.calls[0][1] as boolean)).toBe(false);
    expect(wrapper.find('.label').text()).toBe('ComfyUI');
    // Whether it has subfolders is not known yet, so it offers to open.
    expect(wrapper.find('button.toggle').exists()).toBe(true);
    expect(wrapper.findAll('.name').map((n) => n.text())).toEqual(['loras']);

    await wrapper.find('button.toggle').trigger('click');
    await flushPromises();
    expect(wrapper.findAll('.name').map((n) => n.text())).toEqual(['loras', 'sdxl', 'flux']);
    expect(wrapper.find('.row.active').exists()).toBe(false);

    await wrapper.findAll('.row')[2].trigger('click');
    expect(wrapper.emitted('select')).toEqual([['loras/flux']]);
  });

  it('takes dragged library items on any row, and nothing else', async () => {
    const wrapper = mount(FolderTree, { props: { node: tree.data as never, selected: '' } });
    await flushPromises();
    const row = wrapper.findAll('.row')[2];
    const items = { types: [DRAG_TYPE], dropEffect: 'none', getData: () => '[]' };
    await row.trigger('dragover', { dataTransfer: items });
    expect(row.classes()).toContain('dropping');
    await row.trigger('drop', { dataTransfer: items });
    expect(row.classes()).not.toContain('dropping');
    expect(wrapper.emitted('drop')!.map(([, path]) => path)).toEqual(['vae']);

    // Files from outside are an upload, which the view's drop zone takes.
    await row.trigger('drop', { dataTransfer: { types: ['Files'], getData: () => '' } });
    expect(wrapper.emitted('drop')).toHaveLength(1);
  });

  it('offers nothing to open once its root shows it has no subfolders', async () => {
    const wrapper = mount(FolderTree, { props: { node: node('vae', 'vae') as never, rootId: 'comfy', selected: null, open: true } });
    await flushPromises();
    expect(wrapper.find('button.toggle').exists()).toBe(false);
  });
});
