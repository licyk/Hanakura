import type { PathRef } from '@/api/types';

/**
 * Dragging library items onto a folder moves them. The payload is a JSON list of ``{root_id, path}``
 * under a type of its own, so the upload drop zone (which takes only ``Files``) ignores it.
 */
export const DRAG_TYPE = 'application/x-sd-model-hub-refs';

export const carriesRefs = (event: DragEvent) => !!event.dataTransfer && Array.from(event.dataTransfer.types).includes(DRAG_TYPE);

export function startDrag(event: DragEvent, refs: PathRef[]) {
  if (!event.dataTransfer || !refs.length) return event.preventDefault();
  event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(refs));
  event.dataTransfer.setData('text/plain', refs.map((r) => r.path).join('\n'));
  event.dataTransfer.effectAllowed = 'move';
}

/**
 * The dragged items that can go into ``dir`` of ``rootId``: a folder cannot go into itself or
 * below itself. Items already in that folder stay where they are, which the server skips.
 */
export function readDrop(event: DragEvent, rootId: string, dir: string): PathRef[] {
  let refs: PathRef[];
  try {
    refs = JSON.parse(event.dataTransfer?.getData(DRAG_TYPE) || '[]') as PathRef[];
  } catch {
    return [];
  }
  return refs.filter((r) => !(r.root_id === rootId && (r.path === dir || dir.startsWith(`${r.path}/`))));
}
