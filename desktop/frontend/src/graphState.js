export function snapshotRevision(snapshot) {
  if (!snapshot) return ''
  return JSON.stringify([
    snapshot.project.id,
    snapshot.project.updated_at,
    snapshot.items.map((item) => [item.id, item.parent_id, item.revision]),
  ])
}

export function selectionFromNodeChanges(changes, currentID) {
  const selected = changes.find((change) => change.type === 'select' && change.selected)
  if (selected) return selected.id
  return changes.some((change) => change.type === 'select') ? null : currentID
}

export function isOpenShortcut(event) {
  return Boolean(
    event.metaKey &&
    !event.altKey &&
    !event.ctrlKey &&
    !event.repeat &&
    ['n', 'o'].includes(event.key.toLowerCase()),
  )
}

export function subtreeConfirmation(items, itemID) {
  const byParent = new Map()
  const byID = new Map(items.map((item) => [item.id, item]))
  items.forEach((item) => byParent.set(item.parent_id || '', [...(byParent.get(item.parent_id || '') || []), item.id]))
  const confirmed = []
  const seen = new Set()
  const visit = (id) => {
    if (seen.has(id)) throw new Error(`Concept graph contains a cycle at "${id}".`)
    const item = byID.get(id)
    if (!item) return
    seen.add(id)
    confirmed.push({ id: item.id, revision: item.revision })
    ;(byParent.get(id) || []).forEach(visit)
  }
  visit(itemID)
  return confirmed.sort((left, right) => left.id.localeCompare(right.id))
}
