import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Background, Panel, ReactFlow, useReactFlow } from '@xyflow/react'
import ThoughtNode from './ThoughtNode.jsx'
import { backend } from './backend.js'
import { isOpenShortcut, selectionFromNodeChanges, snapshotRevision, subtreeConfirmation } from './graphState.js'
import { layoutGraph } from './layout.js'

const nodeTypes = { thought: ThoughtNode }

function projectFromLocation() {
  const value = new URLSearchParams(window.location.search).get('project')
  return value && /^\d+$/.test(value) ? Number(value) : null
}

function displayDate(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value))
}

function errorMessage(value) {
  return value instanceof Error ? value.message : String(value)
}

function Picker() {
  const [projects, setProjects] = useState(null)
  const [error, setError] = useState(null)
  const request = useRef(0)

  const reload = useCallback(async () => {
    const current = ++request.current
    try {
      const value = await backend.projects()
      if (current === request.current) {
        setProjects(value)
        setError(null)
      }
    } catch (caught) {
      if (current === request.current) setError(caught)
    }
  }, [])

  useEffect(() => {
    reload()
    return backend.onChanged(reload)
  }, [reload])

  useEffect(() => {
    const blockOpenShortcut = (event) => {
      if (isOpenShortcut(event)) event.preventDefault()
    }
    window.addEventListener('keydown', blockOpenShortcut)
    return () => window.removeEventListener('keydown', blockOpenShortcut)
  }, [])

  const choose = (project) => {
    window.location.search = `?project=${project.id}`
  }

  return (
    <div className="picker-shell">
      <header className="picker-header">
        <div className="mark" aria-hidden="true">m</div>
        <div>
          <h1>Open a coding session</h1>
        </div>
      </header>
      <main className="project-list" aria-busy={!projects && !error}>
        {error && <p className="picker-error" role="alert">{errorMessage(error)}</p>}
        {!error && !projects && <p className="picker-note">Loading projects…</p>}
        {projects?.map((project) => (
          <button className="project-row" onClick={() => choose(project)} key={project.id}>
            <span className={`status-dot${project.active ? ' active' : ''}`} aria-hidden="true" />
            <span className="sr-only">{project.active ? 'Active project.' : 'Paused project.'}</span>
            <span className="project-label">
              <strong>{project.name}</strong>
              <small>{project.root_path}</small>
            </span>
            <span className="project-counts">
              {project.item_count} concepts<br />
              {project.open_count + project.planned_count} unresolved
            </span>
            <span className="row-arrow" aria-hidden="true">›</span>
          </button>
        ))}
        {projects?.length === 0 && (
          <div className="picker-empty">
            <strong>No coding sessions yet.</strong>
            <span>In a project directory, run <code>mindmap start</code>, then begin a new agent session.</span>
          </div>
        )}
      </main>
    </div>
  )
}

function DeleteDialog({ item, count, busy, error, onCancel, onDelete }) {
  const cancelButton = useRef(null)
  const previousFocus = useRef(null)

  useEffect(() => {
    previousFocus.current = document.activeElement
    cancelButton.current?.focus()
    return () => previousFocus.current?.focus?.()
  }, [])

  useEffect(() => {
    const handleKey = (event) => {
      if (event.key === 'Escape' && !busy) onCancel()
      if (event.key === 'Tab') {
        const controls = [...document.querySelectorAll('.modal button:not(:disabled)')]
        if (!controls.length) return
        const first = controls[0]
        const last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [busy, onCancel])

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={() => !busy && onCancel()}>
      <section className="modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-title" aria-describedby="delete-description delete-retention" onMouseDown={(event) => event.stopPropagation()}>
        <span className="danger-label">Delete branch</span>
        <h2 id="delete-title">Delete “{item.title}”?</h2>
        <p id="delete-description">This removes {count} {count === 1 ? 'concept' : 'concepts'} from the map, including every descendant.</p>
        <p id="delete-retention" className="retention-note">Event and transcript history are retained. This is not secure erasure.</p>
        {error && <p className="dialog-error" role="alert">{errorMessage(error)}</p>}
        <div className="dialog-actions">
          <button ref={cancelButton} className="button" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="button danger" onClick={onDelete} disabled={busy}>
            {busy ? 'Deleting…' : `Delete ${count}`}
          </button>
        </div>
      </section>
    </div>
  )
}

function ConceptMap({ projectID }) {
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState(null)
  const [windowError, setWindowError] = useState(null)
  const [direction, setDirection] = useState('LR')
  const [selectedId, setSelectedId] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const request = useRef(0)
  const currentRevision = useRef('')
  const fittedDirection = useRef(null)
  const { fitView } = useReactFlow()

  const reload = useCallback(async () => {
    const current = ++request.current
    try {
      const value = await backend.snapshot(projectID)
      if (current === request.current) {
        const revision = snapshotRevision(value)
        if (revision !== currentRevision.current) {
          currentRevision.current = revision
          setSnapshot(value)
        }
        setError(null)
      }
    } catch (caught) {
      if (current === request.current) setError(caught)
    }
  }, [projectID])

  useEffect(() => {
    reload()
    return backend.onChanged(reload)
  }, [reload])

  const items = snapshot?.items || []
  const graph = useMemo(() => {
    const hasChildren = new Set(items.filter((item) => item.parent_id).map((item) => item.parent_id))
    const nodes = items.map((item) => ({
      id: item.id,
      type: 'thought',
      position: { x: 0, y: 0 },
      data: {
        ...item,
        isRoot: !item.parent_id,
        isFrontier: item.state !== 'settled' && !hasChildren.has(item.id),
      },
      selected: item.id === selectedId,
      ariaLabel: `${item.title}, ${item.state} ${item.kind}`,
      focusable: true,
    }))
    const edges = items.filter((item) => item.parent_id).map((item) => ({
      id: `${item.parent_id}->${item.id}`,
      source: item.parent_id,
      target: item.id,
      type: 'smoothstep',
      style: { stroke: '#3f3f46', strokeWidth: 1.2 },
    }))
    return {
      ...layoutGraph(nodes, edges, direction),
      frontierCount: nodes.filter((node) => node.data.isFrontier).length,
    }
  }, [items, direction, selectedId])

  useEffect(() => {
    if (graph.nodes.length && fittedDirection.current !== direction) {
      fittedDirection.current = direction
      requestAnimationFrame(() => fitView({ padding: 0.14, duration: 180 }))
    }
  }, [direction, graph.nodes.length, fitView])

  useEffect(() => {
    if (selectedId && !items.some((item) => item.id === selectedId)) setSelectedId(null)
  }, [items, selectedId])

  const selected = items.find((item) => item.id === selectedId) || null
  const titles = useMemo(() => Object.fromEntries(items.map((item) => [item.id, item.title])), [items])
  const children = selected ? items.filter((item) => item.parent_id === selected.id) : []
  const openWindow = useCallback(async (action) => {
    try {
      await action()
      setWindowError(null)
    } catch (caught) {
      setWindowError(caught)
    }
  }, [])

  useEffect(() => {
    const handleOpenShortcut = (event) => {
      if (isOpenShortcut(event)) {
        event.preventDefault()
        void openWindow(backend.newPickerWindow)
      }
    }
    window.addEventListener('keydown', handleOpenShortcut)
    return () => window.removeEventListener('keydown', handleOpenShortcut)
  }, [openWindow])

  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError(null)
    try {
      await backend.deleteSubtree(projectID, deleteTarget.id, deleteTarget.confirmed)
      setDeleteTarget(null)
      setSelectedId(null)
      await reload()
    } catch (caught) {
      setDeleteError(caught)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="app">
      <header className="topbar" inert={deleteTarget ? true : undefined}>
        <span className="brand">mindmap</span>
        {snapshot && <span className="project-name">/ {snapshot.project.name}</span>}
        {snapshot && <span className="counts">{items.length} concepts · {graph.frontierCount} frontier</span>}
        <span className="spacer" />
        <button className="button" onClick={() => openWindow(backend.newPickerWindow)}>open…</button>
        <span className="divider" />
        <button className={`button${direction === 'LR' ? ' active' : ''}`} onClick={() => setDirection('LR')}>horizontal</button>
        <button className={`button${direction === 'TB' ? ' active' : ''}`} onClick={() => setDirection('TB')}>vertical</button>
      </header>
      {windowError && <div className="window-error" role="alert">{errorMessage(windowError)}</div>}
      <main className="flow-wrap" inert={deleteTarget ? true : undefined}>
        {error && <div className="center-note picker-error" role="alert">{errorMessage(error)}</div>}
        {!error && !snapshot && <div className="center-note picker-note">Loading…</div>}
        {snapshot && items.length === 0 && (
          <div className="center-note empty-map">
            <strong>No concepts recorded yet.</strong>
            <span>Continue your agent session; this view updates automatically.</span>
          </div>
        )}
        {snapshot && items.length > 0 && (
          <ReactFlow
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            colorMode="dark"
            minZoom={0.15}
            nodesConnectable={false}
            nodesDraggable={false}
            edgesFocusable={false}
            deleteKeyCode={null}
            proOptions={{ hideAttribution: true }}
            onNodesChange={(changes) => {
              setSelectedId((current) => selectionFromNodeChanges(changes, current))
            }}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(null)}
          >
            <Background color="#1c1c1f" gap={26} size={1.5} />
            <Panel position="bottom-left">
              <div className="legend">
                <span><i className="dot dot-open glow" /> open frontier</span>
                <span><i className="dot dot-planned glow" /> planned frontier</span>
                <span><i className="dot dot-settled" /> settled</span>
              </div>
            </Panel>
          </ReactFlow>
        )}
        {selected && (
          <aside className="detail">
            <div className="detail-top">
              <span className={`chip state-${selected.state}`}>{selected.state}</span>
              <button className="close" onClick={() => setSelectedId(null)} aria-label="Close details">×</button>
            </div>
            <h2>{selected.title}</h2>
            {selected.summary && <p>{selected.summary}</p>}
            {selected.resume && (
              <>
                <div className="group-label">resume</div>
                <div className={`resume ${selected.state === 'settled' ? 'quiet' : ''}`}>{selected.resume}</div>
              </>
            )}
            {(selected.parent_id || children.length > 0) && (
              <>
                <div className="group-label">branches</div>
                <ul className="connections">
                  {selected.parent_id && <li><span>grew out of</span><button onClick={() => setSelectedId(selected.parent_id)}>{titles[selected.parent_id]}</button></li>}
                  {children.map((child) => <li key={child.id}><span>branched into</span><button onClick={() => setSelectedId(child.id)}>{child.title}</button></li>)}
                </ul>
              </>
            )}
            <div className="meta">{selected.kind} · updated {displayDate(selected.updated_at)}</div>
            <button className="delete-link" onClick={() => {
              setDeleteError(null)
              try {
                setDeleteTarget({ ...selected, confirmed: subtreeConfirmation(items, selected.id) })
              } catch (caught) {
                setError(caught)
              }
            }}>Delete this branch…</button>
          </aside>
        )}
      </main>
      {deleteTarget && (
        <DeleteDialog
          item={deleteTarget}
          count={deleteTarget.confirmed.length}
          busy={deleting}
          error={deleteError}
          onCancel={() => { setDeleteTarget(null); setDeleteError(null) }}
          onDelete={confirmDelete}
        />
      )}
    </div>
  )
}

export default function App() {
  const projectID = projectFromLocation()
  return projectID ? <ConceptMap projectID={projectID} /> : <Picker />
}
