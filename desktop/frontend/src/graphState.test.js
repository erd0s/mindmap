import { describe, expect, it } from 'vitest'
import { isOpenShortcut, selectionFromNodeChanges, snapshotRevision, subtreeConfirmation } from './graphState.js'

describe('isOpenShortcut', () => {
  it('accepts command O and command N without modifier aliases', () => {
    expect(isOpenShortcut({ key: 'o', metaKey: true })).toBe(true)
    expect(isOpenShortcut({ key: 'N', metaKey: true })).toBe(true)
    expect(isOpenShortcut({ key: 'o', metaKey: true, repeat: true })).toBe(false)
    expect(isOpenShortcut({ key: 'o', metaKey: true, altKey: true })).toBe(false)
    expect(isOpenShortcut({ key: 'o', ctrlKey: true })).toBe(false)
  })
})

describe('selectionFromNodeChanges', () => {
  it('opens the node selected through React Flow keyboard handling', () => {
    expect(selectionFromNodeChanges([{ type: 'select', id: 'root', selected: true }], null)).toBe('root')
  })

  it('switches selection when React Flow unselects one node and selects another', () => {
    const changes = [
      { type: 'select', id: 'root', selected: false },
      { type: 'select', id: 'child', selected: true },
    ]
    expect(selectionFromNodeChanges(changes, 'root')).toBe('child')
  })

  it('clears an explicit unselection and ignores unrelated changes', () => {
    expect(selectionFromNodeChanges([{ type: 'select', id: 'root', selected: false }], 'root')).toBeNull()
    expect(selectionFromNodeChanges([{ type: 'dimensions', id: 'root' }], 'root')).toBe('root')
  })
})

describe('subtreeConfirmation', () => {
  it('captures every confirmed identifier and revision', () => {
    const items = [
      { id: 'root', parent_id: '', revision: 3 },
      { id: 'child', parent_id: 'root', revision: 2 },
      { id: 'sibling', parent_id: '', revision: 1 },
    ]
    expect(subtreeConfirmation(items, 'root')).toEqual([
      { id: 'child', revision: 2 },
      { id: 'root', revision: 3 },
    ])
  })

  it('does not silently expand after the user confirms', () => {
    const before = [
      { id: 'root', parent_id: '', revision: 1 },
      { id: 'child', parent_id: 'root', revision: 1 },
    ]
    const confirmed = subtreeConfirmation(before, 'root')
    const after = [...before, { id: 'late', parent_id: 'child', revision: 1 }]
    expect(confirmed).toHaveLength(2)
    expect(subtreeConfirmation(after, 'root')).toHaveLength(3)
  })

  it('rejects a corrupted cycle instead of recursing forever', () => {
    const items = [
      { id: 'cycle-a', parent_id: 'cycle-b', revision: 1 },
      { id: 'cycle-b', parent_id: 'cycle-a', revision: 1 },
    ]
    expect(() => subtreeConfirmation(items, 'cycle-a')).toThrow(/cycle at "cycle-a"/i)
  })
})

describe('snapshotRevision', () => {
  it('ignores an identical reload and changes with a node revision', () => {
    const snapshot = { project: { id: 1, updated_at: 'now' }, items: [{ id: 'root', parent_id: '', revision: 1 }] }
    expect(snapshotRevision(structuredClone(snapshot))).toBe(snapshotRevision(snapshot))
    const changed = structuredClone(snapshot)
    changed.items[0].revision = 2
    expect(snapshotRevision(changed)).not.toBe(snapshotRevision(snapshot))
  })
})
