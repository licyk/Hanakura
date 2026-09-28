<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query';
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue';
import { previewUrl, saveFile } from '@/api/client';
import { COMBINED_VIEW_ID, keys } from '@/api/queries/keys';
import { useCombinedEntries, useEntries, useLibraryMutations, useRoots, useTree } from '@/api/queries/library';
import { useMeta } from '@/api/queries/app';
import type { FolderEntry, ModelEntry, PathRef } from '@/api/types';
import FileDropZone, { type DroppedFile } from '@/components/FileDropZone.vue';
import FolderTree from '@/components/FolderTree.vue';
import ModelCard from '@/components/ModelCard.vue';
import ModelGrid from '@/components/ModelGrid.vue';
import ModelInfoDialog from '@/components/ModelInfoDialog.vue';
import MoveDialog from '@/components/MoveDialog.vue';
import RenameDialog from '@/components/RenameDialog.vue';
import RootDialog from '@/components/RootDialog.vue';
import SelectionBar from '@/components/SelectionBar.vue';
import { columnsOf, moveFocus, rangeOf } from '@/components/gridKeyboard';
import { carriesRefs, readDrop, startDrag } from '@/components/libraryDrag';
import { fileExtensionLabel, formatBytes, parentPath, pathSegments } from '@/format';
import { useI18n } from '@/i18n';
import { useDownloadsStore } from '@/stores/downloads';
import { usePreferencesStore } from '@/stores/preferences';
import { useUploadsStore } from '@/stores/uploads';
import { useSettings } from '@/api/queries/app';
import {
  AppButton,
  AppDialog,
  AppIcon,
  AppMenu,
  Breadcrumbs,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  IconButton,
  PathField,
  PathText,
  SegmentedButton,
  SelectField,
  Skeleton,
  TextField,
  TRANSITIONS,
  icons,
  type MenuItem,
  useElementHeight,
  useMediaQuery,
  useSnackbar,
} from '@/ui';
import { useViewQuery } from '@/viewState';

const { t, kindLabel } = useI18n();
const route = useViewQuery();
const qc = useQueryClient();
const prefs = usePreferencesStore();
const uploads = useUploadsStore();
const downloadsStore = useDownloadsStore();
const snackbar = useSnackbar();
const settings = useSettings();
const meta = useMeta();
const roots = useRoots();
const m = useLibraryMutations();

const str = (v: unknown) => (typeof v === 'string' ? v : null);
const rootId = ref<string | null>(str(route.query.root) ?? prefs.prefs.lastRoot);
const path = ref(str(route.query.path) ?? '');
const kind = ref<string | null>(null);
const direction = ref(1);

/**
 * Too narrow for the folders beside the contents — a phone, a tablet held upright — the folder
 * panel is a drawer over them. It opens below the toolbar, which stays usable (its button closes
 * the drawer again, however many rows the toolbar wraps onto); a tap on the scrim, Escape or a
 * picked folder closes it too.
 */
const narrow = useMediaQuery('(max-width: 839px)');
const sideOpen = ref(false);
watch(narrow, (value) => {
  if (value) sideOpen.value = false;
});
const head = ref<HTMLElement | null>(null);
const headHeight = useElementHeight(head);
const drawerOpen = computed(() => narrow.value && sideOpen.value);
const belowHead = computed(() => ({ top: `${headHeight.value}px` }));
const onDrawerKey = (event: KeyboardEvent) => event.key === 'Escape' && !event.defaultPrevented && (sideOpen.value = false);
watch(drawerOpen, (open) => (open ? document.addEventListener('keydown', onDrawerKey) : document.removeEventListener('keydown', onDrawerKey)));
onActivated(() => drawerOpen.value && document.addEventListener('keydown', onDrawerKey));
onDeactivated(() => document.removeEventListener('keydown', onDrawerKey));
onBeforeUnmount(() => document.removeEventListener('keydown', onDrawerKey));

/**
 * A root with no kind hint holds a whole model directory; one with a hint is dedicated to a
 * single kind. An embedding host seeds both, so the complete directory leads the list and is
 * what this view opens on. Roots keep their configured order otherwise.
 */
const sortedRoots = computed(() => {
  const list = roots.data.value ?? [];
  return [...list.filter((r) => !r.kind), ...list.filter((r) => r.kind)];
});

/**
 * "All folders" lists the top level of every root side by side. When library.combined_view is on
 * it leads the root list, ahead of even the whole model directory, and is what the view opens on.
 */
const combinedEnabled = computed(() => settings.data.value?.library.combined_view === true);
const isCombined = computed(() => rootId.value === COMBINED_VIEW_ID);

watch(
  [sortedRoots, combinedEnabled],
  ([list, combined]) => {
    if (!roots.data.value) return;
    // Whether "All folders" exists is not known until the settings arrive; a remembered or
    // first choice waits for them rather than settling on a root and never moving.
    const settingsKnown = !!settings.data.value || settings.isError.value;
    if (!settingsKnown && (rootId.value === null || rootId.value === COMBINED_VIEW_ID)) return;
    const ids = [...(combined && list.length ? [COMBINED_VIEW_ID] : []), ...list.map((r) => r.id)];
    if (!ids.includes(rootId.value ?? '')) {
      rootId.value = ids[0] ?? null;
      path.value = '';
    }
  },
  { immediate: true },
);
watch([rootId, path], ([r, p]) => {
  if (r) prefs.prefs.lastRoot = r;
  route.replace({ root: r ?? undefined, path: p || undefined });
  if (!keepSelection.value) selection.value = new Map();
});
// A link pasted while this view is already open must move it, not only fill it on first load.
route.onChange((q) => {
  const nextRoot = str(q.root) ?? rootId.value;
  const nextPath = str(q.path) ?? '';
  if (nextRoot !== rootId.value) rootId.value = nextRoot;
  if (nextPath !== path.value) path.value = nextPath;
});

const entries = useEntries(() => (isCombined.value ? null : rootId.value), path, kind);
const combined = useCombinedEntries(isCombined);
const tree = useTree(() => (isCombined.value ? null : rootId.value));
const root = computed(() => roots.data.value?.find((r) => r.id === rootId.value) ?? null);
const current = computed(() => (isCombined.value ? combined : entries));
const loading = computed(() => current.value.isPending.value);
const failed = computed(() => current.value.isError.value);
const failure = computed(() => (current.value.error?.value as Error | null | undefined)?.message);
const rootOptions = computed(() => [
  ...(combinedEnabled.value && sortedRoots.value.length ? [{ value: COMBINED_VIEW_ID, label: t('library.allFolders') }] : []),
  ...sortedRoots.value.map((r) => ({ value: r.id, label: r.name })),
]);
const kindOptions = computed(() => [{ value: '', label: t('browse.allKinds') }, ...(meta.data.value?.kinds ?? []).map((k) => ({ value: k, label: kindLabel(k) }))]);

// No folder's path is "/", so this crumb cannot be mistaken for one.
const ALL_CRUMB = '/';
const crumbs = computed(() => {
  if (isCombined.value) return [{ label: t('library.allFolders'), value: '' }];
  const trail = [{ label: root.value?.name ?? '', value: '' }, ...pathSegments(path.value).map((s) => ({ label: s.name, value: s.path }))];
  return combinedEnabled.value ? [{ label: t('library.allFolders'), value: ALL_CRUMB }, ...trail] : trail;
});

function navigate(to: string) {
  direction.value = to.length >= path.value.length ? 1 : -1;
  path.value = to;
}

function onCrumb(value: string) {
  if (value !== ALL_CRUMB) return navigate(value);
  direction.value = -1;
  rootId.value = COMBINED_VIEW_ID;
  path.value = '';
}

// Up from a root's top leads to "All folders" when it is offered.
const canGoUp = computed(() => !!path.value || (combinedEnabled.value && !isCombined.value));
const goUp = () => (path.value ? navigate(parentPath(path.value)) : canGoUp.value && onCrumb(ALL_CRUMB));

/**
 * Every item carries its root: in "All folders" the folders on screen come from several roots, and
 * each action goes to the one the item belongs to. ``label`` tells equal names apart there, and an
 * ``isRoot`` entry is a whole root kept together because it has files at its top level.
 */
type FolderItem = { type: 'folder'; rootId: string; label: string; rootName: string | null; isRoot: boolean; folder: FolderEntry };
type ModelItem = { type: 'model'; rootId: string; model: ModelEntry };
type Item = FolderItem | ModelItem;
const items = computed<Item[]>(() => {
  // "All folders" holds folders only: a root with files is one entry, so no file is ever loose there.
  if (isCombined.value) {
    return (combined.data.value?.folders ?? []).map(
      (folder): FolderItem => ({ type: 'folder', rootId: folder.root_id, label: folder.label, rootName: folder.root_name, isRoot: folder.is_root, folder }),
    );
  }
  const id = rootId.value ?? '';
  const l = entries.data.value;
  return [
    ...(l?.folders ?? []).map((folder): FolderItem => ({ type: 'folder', rootId: id, label: folder.name, rootName: null, isRoot: false, folder })),
    ...(l?.models ?? []).map((model): ModelItem => ({ type: 'model', rootId: id, model })),
  ];
});
const itemRef = (i: Item): PathRef => ({ root_id: i.rootId, path: i.type === 'folder' ? i.folder.path : i.model.path });
const refKey = (r: PathRef) => JSON.stringify([r.root_id, r.path]);
const itemKey = (i: Item) => `${i.type}:${refKey(itemRef(i))}`;

function openFolder(item: FolderItem) {
  if (!isCombined.value) return navigate(item.folder.path);
  direction.value = 1;
  rootId.value = item.rootId;
  path.value = item.folder.path;
}

/**
 * In "All folders" each first-level folder is a tree of its own, marked with the root it comes
 * from, and opening one moves into that root.
 */
const combinedTrees = computed(() =>
  (combined.data.value?.folders ?? []).map((folder) => ({ key: refKey({ root_id: folder.root_id, path: folder.path }), folder, node: { name: folder.name, path: folder.path, folder_kind: folder.folder_kind ?? null, children: [] } })),
);
function onTreeSelect(to: string, inRoot?: string) {
  sideOpen.value = false;
  if (!inRoot || inRoot === rootId.value) return navigate(to);
  direction.value = 1;
  rootId.value = inRoot;
  path.value = to;
}
const missingRoots = computed(() => {
  const ids = isCombined.value ? (combined.data.value?.missing_roots ?? []) : [];
  return ids.map((id) => roots.data.value?.find((r) => r.id === id)?.name ?? id).join(', ');
});

/**
 * Selection. While anything is selected the view is in selection mode: a bar of its own slides in
 * below the toolbar, every card shows its checkbox, a click toggles an item instead of opening it,
 * and an item's menu acts on the whole selection when the item is part of it. The selection holds
 * each item with its root, so with ``keepSelection`` it can gather items from several folders.
 */
const selection = ref(new Map<string, PathRef>());
const keepSelection = ref(false);
const selecting = computed(() => selection.value.size > 0);
const isSelected = (i: Item) => selection.value.has(refKey(itemRef(i)));
// Where a Shift range starts: the item last toggled or clicked.
const anchor = ref<string | null>(null);
const toggle = (i: Item, on: boolean) => {
  const r = itemRef(i);
  const next = new Map(selection.value);
  if (on) next.set(refKey(r), r);
  else next.delete(refKey(r));
  selection.value = next;
  anchor.value = refKey(r);
};
/**
 * A click or a key with modifiers: Ctrl/Cmd toggles the item, Shift selects the range from the
 * anchor, replacing the selection unless Ctrl/Cmd is held too or the selection is kept. False
 * when the modifiers ask for nothing, so the item is opened as usual.
 */
function selectWith(item: Item, mods: { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean }): boolean {
  if (item.type === 'folder' && item.isRoot) return false;
  const adding = !!(mods.ctrlKey || mods.metaKey);
  if (mods.shiftKey && anchor.value) {
    const order = selectable.value.map((i) => refKey(itemRef(i)));
    const next = adding || keepSelection.value ? new Map(selection.value) : new Map<string, PathRef>();
    const byKey = new Map(selectable.value.map((i) => [refKey(itemRef(i)), itemRef(i)]));
    for (const key of rangeOf(order, anchor.value, refKey(itemRef(item)))) next.set(key, byKey.get(key)!);
    selection.value = next;
    return true;
  }
  if (adding) {
    toggle(item, !isSelected(item));
    return true;
  }
  return false;
}
const selected = computed(() => [...selection.value.values()]);
// A whole root cannot be moved or deleted, so it is never part of a selection.
const selectable = computed(() => items.value.filter((i) => !(i.type === 'folder' && i.isRoot)));
const selectableTotal = computed(() => new Set([...selection.value.keys(), ...selectable.value.map((i) => refKey(itemRef(i)))]).size);
function selectAll() {
  const next = new Map(selection.value);
  for (const i of selectable.value) next.set(refKey(itemRef(i)), itemRef(i));
  selection.value = next;
}
// Letting go of a kept selection leaves only what is on screen selected.
watch(keepSelection, (keep) => {
  if (keep) return;
  const here = new Set(items.value.map((i) => refKey(itemRef(i))));
  selection.value = new Map([...selection.value].filter(([key]) => here.has(key)));
});
const clearSelection = () => {
  selection.value = new Map();
  anchor.value = null;
};
/** The items an item's menu acts on: the whole selection when the item is part of it. */
const actedOn = (i: Item) => (isSelected(i) ? selected.value : [itemRef(i)]);
const actsOnSelection = (i: Item) => isSelected(i) && selection.value.size > 1;

// Dialogs
const infoOpen = ref(false);
const infoRoot = ref<string | null>(null);
const infoPath = ref<string | null>(null);
const infoRect = ref<DOMRect | null>(null);
function openInfo(item: ModelItem, rect: DOMRect | null) {
  infoRoot.value = item.rootId;
  infoPath.value = item.model.path;
  infoRect.value = rect;
  infoOpen.value = true;
}

const renameOpen = ref(false);
const renameTarget = ref<{ ref: PathRef; name: string; isFile: boolean } | null>(null);
const renameError = ref<string | null>(null);
function startRename(ref_: PathRef, name: string, isFile: boolean) {
  renameTarget.value = { ref: ref_, name, isFile };
  renameError.value = null;
  renameOpen.value = true;
}
function doRename(newName: string) {
  if (!renameTarget.value) return;
  m.rename.mutate(
    { ...renameTarget.value.ref, new_name: newName },
    { onSuccess: () => (renameOpen.value = false), onError: (e) => (renameError.value = (e as Error).message) },
  );
}

const moveOpen = ref(false);
const moveItems = ref<PathRef[]>([]);
function startMove(refs: PathRef[]) {
  moveItems.value = refs;
  moveOpen.value = true;
}
function doMove(dest: { rootId: string; dir: string }) {
  m.move.mutate(
    { items: moveItems.value, dest_root_id: dest.rootId, dest_dir: dest.dir, on_conflict: 'error' },
    {
      onSuccess: () => {
        moveOpen.value = false;
        selection.value = new Map();
        qc.invalidateQueries({ queryKey: ['library'] });
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

/**
 * Drag and drop: a card or folder dragged onto a folder, in the grid or the tree, moves there,
 * taking the whole selection along when it is part of it. A whole root cannot be moved.
 */
const dropKey = ref<string | null>(null);
function onDragStart(item: Item, event: DragEvent) {
  const own = itemRef(item);
  startDrag(event, selection.value.has(refKey(own)) ? selected.value : [own]);
}
function onFolderDragOver(item: FolderItem, event: DragEvent) {
  if (!carriesRefs(event)) return;
  event.preventDefault();
  event.dataTransfer!.dropEffect = 'move';
  dropKey.value = itemKey(item);
}
function dropInto(event: DragEvent, destRoot: string | null, dir: string) {
  dropKey.value = null;
  if (!destRoot || !carriesRefs(event)) return;
  event.preventDefault();
  const items = readDrop(event, destRoot, dir);
  if (!items.length) return;
  const folder = dir.split('/').pop() || (roots.data.value?.find((r) => r.id === destRoot)?.name ?? '/');
  m.move.mutate(
    { items, dest_root_id: destRoot, dest_dir: dir, on_conflict: 'error' },
    {
      onSuccess: () => {
        selection.value = new Map();
        qc.invalidateQueries({ queryKey: ['library'] });
        snackbar.show(t('library.movedTo', { n: items.length, folder }));
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

const deleteOpen = ref(false);
const deleteItems = ref<PathRef[]>([]);
const permanent = ref(false);
const toTrash = computed(() => settings.data.value?.library.delete_to_trash !== false);
function startDelete(refs: PathRef[]) {
  deleteItems.value = refs;
  permanent.value = !toTrash.value;
  deleteOpen.value = true;
}
function doDelete() {
  m.remove.mutate(
    { items: deleteItems.value, permanent: permanent.value },
    {
      onSuccess: () => {
        deleteOpen.value = false;
        selection.value = new Map();
        qc.invalidateQueries({ queryKey: ['library'] });
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

// Creating, importing and uploading need one folder to land in, which "All folders" is not.
const canAdd = computed(() => !!rootId.value && !isCombined.value);

const folderOpen = ref(false);
const folderName = ref('');
function doCreateFolder() {
  if (!canAdd.value || !rootId.value || !folderName.value.trim()) return;
  m.createFolder.mutate(
    { root_id: rootId.value, path: path.value, name: folderName.value.trim() },
    {
      onSuccess: () => {
        folderOpen.value = false;
        folderName.value = '';
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

const importOpen = ref(false);
const importPath = ref('');
const importMove = ref(false);
function doImport() {
  if (!canAdd.value || !rootId.value || !importPath.value.trim()) return;
  m.importPaths.mutate(
    { sources: [importPath.value.trim()], root_id: rootId.value, rel_dir: path.value, move: importMove.value, on_conflict: 'error' },
    {
      onSuccess: () => {
        importOpen.value = false;
        importPath.value = '';
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

const rootDialogOpen = ref(false);
const editingRoot = ref(false);
const rootError = ref<string | null>(null);
function openRootDialog(edit: boolean) {
  editingRoot.value = edit;
  rootError.value = null;
  rootDialogOpen.value = true;
}
function saveRoot(form: { name: string | null; path: string; layout: 'comfyui' | 'sd-webui' | 'custom'; kind: string | null }) {
  const onError = (e: unknown) => (rootError.value = (e as Error).message);
  if (editingRoot.value && rootId.value) {
    m.updateRoot.mutate({ id: rootId.value, body: form }, { onSuccess: () => (rootDialogOpen.value = false), onError });
  } else {
    m.addRoot.mutate(form, {
      onSuccess: (r) => {
        rootDialogOpen.value = false;
        rootId.value = r.id;
        path.value = '';
      },
      onError,
    });
  }
}
const removeRootOpen = ref(false);
function doRemoveRoot() {
  if (!rootId.value) return;
  m.removeRoot.mutate(rootId.value, { onSuccess: () => (removeRootOpen.value = false) });
}

// A host application can fix the model folders; the actions that would change them are then gone.
const rootsLocked = computed(() => meta.data.value?.roots_locked ?? false);
const rootMenu = computed<MenuItem[]>(() =>
  rootsLocked.value
    ? []
    : [
        { id: 'add', label: t('library.addRoot'), icon: icons.Plus },
        { id: 'edit', label: t('library.editRoot'), icon: icons.Pencil, disabled: !root.value },
        { id: 'remove', label: t('library.removeRoot'), icon: icons.Trash2, danger: true, disabled: !root.value },
      ],
);
function onRootMenu(id: string) {
  if (id === 'add') openRootDialog(false);
  if (id === 'edit') openRootDialog(true);
  if (id === 'remove') removeRootOpen.value = true;
}

/**
 * An item's menu. Part of a larger selection, it offers only what applies to the whole selection;
 * otherwise it acts on the item alone and can start or end a selection with it.
 */
function itemMenu(item: Item): MenuItem[] {
  if (actsOnSelection(item)) {
    const n = selection.value.size;
    return [
      { id: 'move', label: t('library.moveItems', { n }), icon: icons.FolderInput },
      { id: 'delete', label: t('library.deleteItems', { n }), icon: icons.Trash2, danger: true },
      { id: 'deselect', label: t('library.deselect'), icon: icons.X },
    ];
  }
  const own: MenuItem[] =
    item.type === 'model'
      ? [
          { id: 'info', label: t('common.info'), icon: icons.Info },
          // A diffusers model is a folder, which a browser cannot save as one download.
          ...(item.model.is_dir ? [] : [{ id: 'download', label: t('library.download'), icon: icons.Download }]),
        ]
      : [];
  return [
    isSelected(item) ? { id: 'deselect', label: t('library.deselect'), icon: icons.X } : { id: 'select', label: t('library.select'), icon: icons.SquareCheck },
    ...own,
    { id: 'rename', label: t('common.rename'), icon: icons.Pencil },
    { id: 'move', label: t('common.move'), icon: icons.Move },
    { id: 'delete', label: t('common.delete'), icon: icons.Trash2, danger: true },
  ];
}
function onItemMenu(id: string, item: Item) {
  if (id === 'select' || id === 'deselect') return toggle(item, id === 'select');
  if (id === 'move') return startMove(actedOn(item));
  if (id === 'delete') return startDelete(actedOn(item));
  if (id === 'rename') return item.type === 'model' ? startRename(itemRef(item), item.model.name, !item.model.is_dir) : startRename(itemRef(item), item.folder.name, false);
  if (item.type !== 'model') return;
  if (id === 'info') openInfo(item, null);
  if (id === 'download') saveFile(item.rootId, item.model.path);
}

/** While selecting, a click on an item toggles it rather than opening it; with modifiers it selects. */
function onFolderClick(item: FolderItem, event?: MouseEvent) {
  if (event && selectWith(item, event)) return;
  if (selecting.value && !item.isRoot) return toggle(item, !isSelected(item));
  openFolder(item);
}
function onModelActivate(item: ModelItem, rect: DOMRect | null, event?: MouseEvent | KeyboardEvent) {
  if (event && selectWith(item, event)) return;
  if (selecting.value) return toggle(item, !isSelected(item));
  openInfo(item, rect);
}

/**
 * The grid's keyboard, on the item that has the focus (its menu button and checkbox keep their
 * own keys). Arrows, Home/End and PageUp/PageDown move between items, with Shift selecting the
 * way; Enter opens even while selecting, Space toggles, Ctrl/Cmd+A selects all, Escape clears,
 * Delete deletes the selection or the item, Backspace goes up. It listens in the capture phase so
 * Enter reaches it before the card turns it into a click.
 */
function onGridKey(event: KeyboardEvent) {
  const grid = event.currentTarget as HTMLElement;
  const cell = (event.target as HTMLElement).closest<HTMLElement>('.model-grid > .cell');
  if (!cell || event.target !== cell.firstElementChild) return;
  const cells = Array.from(grid.querySelectorAll<HTMLElement>('.model-grid > .cell'));
  const index = cells.indexOf(cell);
  const item = items.value[index];
  if (!item) return;
  const handled = () => {
    event.preventDefault();
    event.stopPropagation();
  };

  const next = moveFocus(index, event.key, columnsOf(cells), cells.length);
  if (next !== null && !event.altKey && !event.ctrlKey && !event.metaKey) {
    handled();
    (cells[next].firstElementChild as HTMLElement | null)?.focus();
    const target = items.value[next];
    if (event.shiftKey && target) {
      if (!anchor.value) anchor.value = refKey(itemRef(item));
      selectWith(target, { shiftKey: true });
    }
    return;
  }
  const whole = item.type === 'folder' && item.isRoot;
  if (event.key === 'Enter') {
    handled();
    if (item.type === 'folder') openFolder(item);
    else openInfo(item, cell.getBoundingClientRect());
  } else if (event.key === ' ') {
    handled();
    if (!whole) toggle(item, !isSelected(item));
  } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
    handled();
    selectAll();
  } else if (event.key === 'Escape' && selecting.value) {
    handled();
    clearSelection();
  } else if (event.key === 'Delete') {
    handled();
    if (selecting.value) startDelete(selected.value);
    else if (!whole) startDelete([itemRef(item)]);
  } else if (event.key === 'Backspace') {
    handled();
    goUp();
  }
}

function rescan() {
  if (!rootId.value) return;
  const targets = isCombined.value ? sortedRoots.value.map((r) => ({ rootId: r.id, path: '' })) : [{ rootId: rootId.value, path: path.value }];
  Promise.all(targets.map((v) => m.scan.mutateAsync(v))).then(
    () => snackbar.show(t('library.scanStarted')),
    (e) => snackbar.error((e as Error).message),
  );
}

// Files land in the folder on screen, whether they were dropped or chosen in the file picker.
function startUpload(files: DroppedFile[]) {
  if (!canAdd.value || !rootId.value || !files.length) return;
  uploads.enqueue(rootId.value, path.value, files);
  snackbar.show(t('library.uploadStarted', { n: files.length }), { actionLabel: t('browse.openDownloads'), action: () => (downloadsStore.drawerOpen = true) });
}

/**
 * Open the system file picker. The input is created here rather than kept in the template: a
 * folder needs the non-standard ``webkitdirectory``, and a fresh input also fires ``change``
 * when the same file is chosen twice.
 */
function pickFiles(directory: boolean) {
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  if (directory) input.webkitdirectory = true;
  input.addEventListener('change', () => {
    // The picker gives a folder's structure in webkitRelativePath, which the upload keeps.
    startUpload(Array.from(input.files ?? []).map((file) => ({ file, relativePath: file.webkitRelativePath || file.name })));
  });
  input.click();
}

const uploadMenu = computed<MenuItem[]>(() => [
  { id: 'files', label: t('library.uploadFiles'), icon: icons.File },
  { id: 'folder', label: t('library.uploadFolder'), icon: icons.FolderInput },
]);

const stopListening = uploads.onFinished((item) => {
  if (item.state === 'failed') snackbar.error(t('library.uploadFailed', { name: item.name, error: item.error ?? '' }));
  qc.invalidateQueries({ queryKey: keys.entries(item.rootId) });
  qc.invalidateQueries({ queryKey: keys.entries(COMBINED_VIEW_ID) });
  qc.invalidateQueries({ queryKey: keys.tree(item.rootId) });
});
onBeforeUnmount(stopListening);

/** A file listed only because library.show_all_files is on: shown by its extension, never detected. */
const fileLabel = (model: ModelEntry) => fileExtensionLabel(model.name) ?? t('library.file');

const warningFor = (model: ModelEntry) => (model.mismatch ? t('library.mismatchText') : null);
const baseFor = (model: ModelEntry) => {
  if (!model.is_model) return null;
  const b = model.detection?.base_model ?? model.sidecar?.base_model;
  return b ? (meta.data.value?.base_models.find((x) => x.value === b)?.label ?? b) : null;
};
const kindFor = (model: ModelEntry) => {
  if (!model.is_model) return fileLabel(model);
  const k = model.detection?.kind && model.detection.kind !== 'unknown' ? model.detection.kind : (model.sidecar?.kind ?? model.folder_kind ?? 'unknown');
  return kindLabel(k);
};
</script>

<template>
  <div class="library" :class="{ narrow }">
    <EmptyState
      v-if="roots.isSuccess.value && !roots.data.value?.length"
      :icon="icons.HardDrive"
      :title="t('library.noRootsTitle')"
      :text="rootsLocked ? t('library.rootsLocked') : t('library.noRootsText')"
      class="no-roots"
    >
      <AppButton v-if="!rootsLocked" :icon="icons.FolderPlus" @click="openRootDialog(false)">{{ t('library.addRoot') }}</AppButton>
    </EmptyState>

    <template v-else>
      <Transition :name="TRANSITIONS.scrim">
        <div v-if="drawerOpen" class="scrim" :style="belowHead" @click="sideOpen = false" />
      </Transition>
      <!-- As a drawer it slides in from the edge; beside the contents on a wide screen it is simply there. -->
      <Transition :name="TRANSITIONS.drawer" :css="narrow">
      <aside v-if="!narrow || sideOpen" class="side" :class="{ overlay: narrow }" :style="narrow ? belowHead : undefined">
        <div class="root-row">
          <SelectField v-model="rootId" :label="t('library.root')" :options="rootOptions" class="root-select" @update:model-value="path = ''" />
          <AppMenu v-if="rootMenu.length" :items="rootMenu" @select="onRootMenu">
            <template #default="{ toggle }"><IconButton :icon="icons.MoreVertical" :label="t('common.more')" @click="toggle" /></template>
          </AppMenu>
        </div>
        <PathText v-if="root" :path="root.path" class="type-body-small muted" />
        <p v-else-if="isCombined" class="type-body-small muted hint">{{ t('library.allFoldersHint') }}</p>
        <p v-if="root && !root.exists" class="type-body-small error">{{ t('library.missing') }}</p>
        <p v-if="missingRoots" class="type-body-small error">{{ t('library.missingRoots', { names: missingRoots }) }}</p>
        <div v-if="isCombined" class="tree" role="tree" :aria-label="t('library.allFolders')">
          <template v-if="combined.data.value">
            <FolderTree
              v-for="entry in combinedTrees"
              :key="entry.key"
              :node="entry.node"
              :root-id="entry.folder.root_id"
              :label="entry.folder.root_name"
              :selected="null"
              :open="false"
              @select="onTreeSelect($event, entry.folder.root_id)"
              @drop="(event, dir) => dropInto(event, entry.folder.root_id, dir)"
            />
          </template>
          <div v-else class="tree-skeleton"><Skeleton v-for="i in 6" :key="i" height="28px" shape="full" /></div>
        </div>
        <div v-else class="tree" role="tree" :aria-label="root?.name">
          <FolderTree v-if="tree.data.value" :key="rootId ?? ''" :node="tree.data.value" :selected="path" @select="onTreeSelect" @drop="(event, dir) => dropInto(event, rootId, dir)" />
          <div v-else class="tree-skeleton"><Skeleton v-for="i in 6" :key="i" height="28px" shape="full" /></div>
        </div>
      </aside>
      </Transition>

      <section class="main">
        <FileDropZone :label="t('library.dropHere', { folder: path || root?.name || '/' })" :disabled="!canAdd" @files="startUpload">
          <div ref="head" class="head">
            <div class="crumb-row">
              <IconButton
                v-if="narrow"
                :icon="sideOpen ? icons.FolderOpen : icons.Folder"
                :label="sideOpen ? t('library.hideFolders') : t('library.showFolders')"
                :tonal="sideOpen"
                :expanded="sideOpen"
                class="side-toggle"
                @click="sideOpen = !sideOpen"
              />
              <IconButton :icon="icons.ArrowUp" :label="t('library.up')" :disabled="!canGoUp" class="up" @click="goUp" />
              <Breadcrumbs :crumbs="crumbs" @navigate="onCrumb" />
            </div>
            <div class="toolbar">
              <template v-if="canAdd">
                <AppMenu :items="uploadMenu" @select="pickFiles($event === 'folder')">
                  <template #default="{ toggle }">
                    <AppButton variant="tonal" :icon="icons.Upload" @click="toggle">{{ t('library.upload') }}</AppButton>
                  </template>
                </AppMenu>
                <AppButton variant="text" :icon="icons.FolderInput" @click="importOpen = true">{{ t('library.import') }}</AppButton>
                <IconButton :icon="icons.FolderPlus" :label="t('library.newFolder')" @click="folderOpen = true" />
              </template>
              <IconButton :icon="icons.RefreshCw" :label="t('library.rescan')" :spin="m.scan.isPending.value" @click="rescan" />
              <SelectField v-if="!isCombined" :model-value="kind ?? ''" :label="t('library.filterKind')" :options="kindOptions" class="kind" @update:model-value="kind = $event || null" />
              <SegmentedButton
                v-model="prefs.prefs.libraryView"
                :options="[
                  { value: 'grid', icon: icons.LayoutGrid, ariaLabel: t('library.grid') },
                  { value: 'list', icon: icons.LayoutList, ariaLabel: t('library.list') },
                ]"
              />
            </div>
            <SelectionBar
              v-model:keep="keepSelection"
              :count="selection.size"
              :total="selectableTotal"
              @clear="clearSelection"
              @select-all="selectAll"
              @move="startMove(selected)"
              @delete="startDelete(selected)"
            />
          </div>

          <Transition name="shared-axis-x" mode="out-in">
            <div :key="`${rootId}:${path}:${kind}`" class="content" :class="{ selecting }" :style="{ '--axis-dir': direction }" @keydown.capture="onGridKey">
              <div v-if="loading" class="skeletons">
                <div v-for="i in 10" :key="i" class="skeleton-card"><Skeleton height="200px" shape="medium" /><Skeleton width="70%" /></div>
              </div>
              <EmptyState v-else-if="failed" :icon="icons.AlertTriangle" :title="t('common.error')" :text="failure" />
              <EmptyState v-else-if="!items.length && isCombined" :icon="icons.FolderOpen" :title="t('library.emptyTitle')" :text="t('library.allFoldersEmptyText')" />
              <EmptyState v-else-if="!items.length" :icon="icons.FolderOpen" :title="t('library.emptyTitle')" :text="t('library.emptyText')">
                <AppButton variant="tonal" :icon="icons.Upload" :disabled="!canAdd" @click="pickFiles(false)">{{ t('library.upload') }}</AppButton>
                <AppButton variant="text" :icon="icons.FolderInput" @click="importOpen = true">{{ t('library.import') }}</AppButton>
              </EmptyState>
              <ModelGrid v-else :items="items" :item-key="itemKey" :layout="prefs.prefs.libraryView">
                <template #default="{ item }">
                  <button
                    v-if="item.type === 'folder'"
                    type="button"
                    class="folder state-layer"
                    :class="[`folder-${prefs.prefs.libraryView}`, { dropping: dropKey === itemKey(item), checked: isSelected(item) }]"
                    :draggable="!item.isRoot"
                    @click="onFolderClick(item, $event)"
                    @dragstart="onDragStart(item, $event)"
                    @dragover="onFolderDragOver(item, $event)"
                    @dragleave="dropKey = null"
                    @drop="dropInto($event, item.rootId, item.folder.path)"
                  >
                    <!-- The folder's icon gives way to its checkbox on hover and while selecting. -->
                    <span class="folder-icon" :class="{ checkable: !item.isRoot }">
                      <AppIcon :icon="icons.Folder" :size="24" class="folder-glyph" />
                      <span v-if="!item.isRoot" class="folder-check" @click.stop>
                        <Checkbox :model-value="isSelected(item)" dense :label="t('library.select')" @update:model-value="toggle(item, $event)" />
                      </span>
                    </span>
                    <span class="folder-text">
                      <span class="type-title-small folder-name">{{ item.label }}</span>
                      <span v-if="item.folder.folder_kind || item.rootName" class="type-body-small muted folder-meta">
                        {{ [item.folder.folder_kind ? kindLabel(item.folder.folder_kind) : null, item.rootName].filter(Boolean).join(' · ') }}
                      </span>
                    </span>
                    <!-- A root cannot be renamed, moved or deleted from here. -->
                    <AppMenu v-if="!item.isRoot" :items="itemMenu(item)" @select="onItemMenu($event, item)">
                      <template #default="{ toggle }"><IconButton :icon="icons.MoreVertical" :label="t('common.more')" @click.stop="toggle" /></template>
                    </AppMenu>
                  </button>
                  <ModelCard
                    v-else
                    :layout="prefs.prefs.libraryView"
                    :title="item.model.name"
                    :subtitle="formatBytes(item.model.size)"
                    :preview="item.model.preview ? previewUrl(item.rootId, item.model.preview, prefs.prefs.libraryView === 'list' ? 128 : 384) : null"
                    :fallback-icon="item.model.is_model ? undefined : icons.FileText"
                    :kind="kindFor(item.model)"
                    :base="baseFor(item.model)"
                    :warning="warningFor(item.model)"
                    :pending="item.model.is_model && !item.model.detection && (entries.data.value?.pending_detection ?? 0) > 0"
                    :selected="isSelected(item)"
                    :selecting="selecting"
                    draggable="true"
                    @activate="(rect: DOMRect | null, event?: MouseEvent | KeyboardEvent) => onModelActivate(item, rect, event)"
                    @dragstart="onDragStart(item, $event)"
                  >
                    <template #select>
                      <Checkbox
                        :model-value="isSelected(item)"
                        :dense="prefs.prefs.libraryView === 'list'"
                        :class="prefs.prefs.libraryView === 'list' ? '' : 'select-box'"
                        @update:model-value="toggle(item, $event)"
                      />
                    </template>
                    <template #actions>
                      <AppMenu :items="itemMenu(item)" @select="onItemMenu($event, item)">
                        <template #default="{ toggle: open }"><IconButton :icon="icons.MoreVertical" :label="t('common.more')" @click="open" /></template>
                      </AppMenu>
                    </template>
                  </ModelCard>
                </template>
              </ModelGrid>
            </div>
          </Transition>
        </FileDropZone>
      </section>
    </template>

    <ModelInfoDialog v-model:open="infoOpen" :root-id="infoRoot" :path="infoPath" :from-rect="infoRect" />
    <RenameDialog v-model:open="renameOpen" :name="renameTarget?.name ?? ''" :is-file="renameTarget?.isFile" :loading="m.rename.isPending.value" :error="renameError" @confirm="doRename" />
    <MoveDialog v-model:open="moveOpen" :count="moveItems.length" :root-id="moveItems[0]?.root_id ?? null" :loading="m.move.isPending.value" @confirm="doMove" />
    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('library.deleteTitle', { n: deleteItems.length })"
      :message="permanent ? t('library.deletePermanent') : t('library.deleteTrash')"
      :confirm-label="t('common.delete')"
      :cancel-label="t('common.cancel')"
      :loading="m.remove.isPending.value"
      danger
      @confirm="doDelete"
    >
      <Checkbox v-if="toTrash" v-model="permanent" :label="t('library.permanent')" />
    </ConfirmDialog>
    <AppDialog v-model:open="folderOpen" :title="t('library.newFolder')" width="small">
      <TextField v-model="folderName" :label="t('library.folderName')" @enter="doCreateFolder" />
      <template #actions>
        <AppButton variant="text" @click="folderOpen = false">{{ t('common.cancel') }}</AppButton>
        <AppButton :disabled="!folderName.trim()" :loading="m.createFolder.isPending.value" @click="doCreateFolder">{{ t('common.save') }}</AppButton>
      </template>
    </AppDialog>
    <AppDialog v-model:open="importOpen" :title="t('library.import')" width="small">
      <div class="form">
        <PathField v-model="importPath" :label="t('library.importPath')" :supporting-text="t('library.importHelp')" placeholder="/path/to/model.safetensors" @enter="doImport" />
        <Checkbox v-model="importMove" :label="t('library.importMove')" />
      </div>
      <template #actions>
        <AppButton variant="text" @click="importOpen = false">{{ t('common.cancel') }}</AppButton>
        <AppButton :disabled="!importPath.trim()" :loading="m.importPaths.isPending.value" @click="doImport">{{ t('library.import') }}</AppButton>
      </template>
    </AppDialog>
    <RootDialog v-model:open="rootDialogOpen" :root="editingRoot ? root : null" :loading="m.addRoot.isPending.value || m.updateRoot.isPending.value" :error="rootError" @confirm="saveRoot" />
    <ConfirmDialog
      v-model:open="removeRootOpen"
      :title="t('library.removeRoot')"
      :message="t('library.removeRootText')"
      :confirm-label="t('library.removeRoot')"
      :cancel-label="t('common.cancel')"
      @confirm="doRemoveRoot"
    />
  </div>
</template>

<style scoped>
/* The folder side widens with the window, so long folder names fit on a wide screen. */
.library { --side-width: clamp(280px, 20vw, 480px); position: relative; display: grid; grid-template-columns: var(--side-width) minmax(0, 1fr); height: 100%; }
.no-roots { grid-column: 1 / -1; align-self: center; }
.side { display: flex; flex-direction: column; gap: var(--app-space-2); padding: var(--app-space-4); min-height: 0; border-right: 1px solid var(--md-sys-color-outline-variant); }
/* The drawer and its scrim start below the toolbar (``top`` is its measured height). */
.side.overlay {
  position: absolute; left: 0; bottom: 0; z-index: 7; width: min(var(--side-width), 90%); border-right: 0;
  background: var(--md-sys-color-surface-container-low); box-shadow: var(--app-elevation-2); border-top-right-radius: var(--md-sys-shape-corner-large);
}
.scrim { position: absolute; left: 0; right: 0; bottom: 0; z-index: 6; background: color-mix(in srgb, var(--md-sys-color-scrim) 32%, transparent); }
.root-row { display: flex; align-items: center; gap: var(--app-space-1); }
.root-select { flex: 1; min-width: 0; }
.hint { margin: 0; }
.error { color: var(--md-sys-color-error); margin: 0; }
.tree { flex: 1; min-height: 0; overflow: auto; margin: 0 calc(-1 * var(--app-space-2)); }
.tree-skeleton { display: flex; flex-direction: column; gap: var(--app-space-2); padding: var(--app-space-2); }
.main { min-width: 0; overflow: auto; }
.crumb-row { display: flex; align-items: center; gap: var(--app-space-1); min-width: 0; }
.side-toggle, .up { flex: none; }
.head { position: sticky; top: 0; z-index: 5; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--app-space-2); padding: var(--app-space-3) var(--app-space-4); background: var(--md-sys-color-surface-container-low); }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2); }
.kind { min-width: 150px; }
.content { position: relative; padding: 0 var(--app-space-4) var(--app-space-6); }
.skeletons { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--app-space-3); }
.skeleton-card { display: flex; flex-direction: column; gap: var(--app-space-2); }
.folder {
  display: flex; align-items: center; gap: var(--app-space-3); width: 100%; padding: var(--app-space-2) var(--app-space-1) var(--app-space-2) var(--app-space-3);
  border: 0; border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); color: var(--md-sys-color-on-surface); cursor: pointer; text-align: left; font: inherit;
}
.folder.dropping { outline: 2px solid var(--md-sys-color-primary); outline-offset: -2px; }
.folder-grid { min-height: 64px; }
.folder-list { min-height: 56px; }
.folder.checked { outline: 3px solid var(--md-sys-color-primary); outline-offset: -3px; }
.folder-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: var(--md-sys-shape-corner-small); background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); flex: none; }
/* The icon and the checkbox share one place; the checkbox takes it on hover, while selecting, or once checked. */
.folder-glyph, .folder-check { grid-area: 1 / 1; transition: opacity var(--md-sys-motion-duration-short3) var(--md-sys-motion-easing-standard); }
.folder-check { display: grid; place-items: center; opacity: 0; pointer-events: none; }
.selecting .folder-check, .folder.checked .folder-check { opacity: 1; pointer-events: auto; }
.selecting .checkable .folder-glyph, .folder.checked .folder-glyph { opacity: 0; }
@media (hover: hover) {
  .folder:hover .folder-check, .folder:focus-visible .folder-check { opacity: 1; pointer-events: auto; }
  .folder:hover .checkable .folder-glyph, .folder:focus-visible .checkable .folder-glyph { opacity: 0; }
}
.folder-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.folder-name, .folder-meta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.select-box { padding: 2px; border-radius: var(--md-sys-shape-corner-small); background: color-mix(in srgb, var(--md-sys-color-surface) 70%, transparent); }
.form { display: flex; flex-direction: column; gap: var(--app-space-3); }
/* The contents take the whole width; the folders come over them as a drawer. */
.narrow { grid-template-columns: minmax(0, 1fr); }
</style>
