import { describe, expect, it } from 'vitest';
import { columnsOf, moveFocus, rangeOf } from '@/components/gridKeyboard';

describe('grid keyboard model', () => {
  // A grid of 10 items in rows of 4:  0 1 2 3 / 4 5 6 7 / 8 9
  const move = (from: number, key: string) => moveFocus(from, key, 4, 10, 2);

  it('moves by cells and rows, clamped to the list', () => {
    expect(move(5, 'ArrowRight')).toBe(6);
    expect(move(5, 'ArrowLeft')).toBe(4);
    expect(move(5, 'ArrowDown')).toBe(9);
    expect(move(6, 'ArrowDown')).toBe(9);
    expect(move(1, 'ArrowUp')).toBe(0);
    expect(move(9, 'ArrowRight')).toBe(9);
    expect(move(0, 'ArrowLeft')).toBe(0);
  });

  it('starts at the first cell when nothing is focused', () => {
    expect(move(-1, 'ArrowDown')).toBe(0);
    expect(move(-1, 'ArrowRight')).toBe(0);
  });

  it('jumps to the ends and by pages', () => {
    expect(move(5, 'Home')).toBe(0);
    expect(move(5, 'End')).toBe(9);
    expect(move(0, 'PageDown')).toBe(8);
    expect(move(9, 'PageUp')).toBe(1);
  });

  it('ignores other keys and empty grids', () => {
    expect(move(3, 'a')).toBeNull();
    expect(moveFocus(0, 'ArrowRight', 4, 0)).toBeNull();
  });
});

describe('the grid as laid out', () => {
  const cell = (top: number) => ({ getBoundingClientRect: () => ({ top }) }) as HTMLElement;

  it('counts the cells of the first row', () => {
    expect(columnsOf([cell(0), cell(0), cell(0), cell(120), cell(120)])).toBe(3);
    // One row, or a list: every cell on it, or one per row.
    expect(columnsOf([cell(0), cell(0)])).toBe(2);
    expect(columnsOf([cell(0), cell(60), cell(120)])).toBe(1);
    expect(columnsOf([])).toBe(1);
  });

  it('takes a range in either direction', () => {
    const order = ['a', 'b', 'c', 'd'];
    expect(rangeOf(order, 'b', 'd')).toEqual(['b', 'c', 'd']);
    expect(rangeOf(order, 'd', 'b')).toEqual(['b', 'c', 'd']);
    expect(rangeOf(order, 'gone', 'c')).toEqual(['c']);
  });
});
