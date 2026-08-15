import { describe, expect, it } from 'vitest'
import { layoutGraph } from './layout.js'

describe('layoutGraph', () => {
  it('places a child after its parent in either direction', () => {
    const nodes = [
      { id: 'root', data: {} },
      { id: 'child', data: {} },
    ]
    const edges = [{ id: 'edge', source: 'root', target: 'child' }]
    const horizontal = layoutGraph(nodes, edges, 'LR')
    expect(horizontal.nodes[1].position.x).toBeGreaterThan(horizontal.nodes[0].position.x)
    const vertical = layoutGraph(nodes, edges, 'TB')
    expect(vertical.nodes[1].position.y).toBeGreaterThan(vertical.nodes[0].position.y)
  })

  it('keeps an empty project renderable', () => {
    expect(layoutGraph([], [], 'LR')).toEqual({ nodes: [], edges: [] })
  })

  it.each(['LR', 'TB'])('keeps long, multiline, and Unicode titles inside fixed layout boxes in %s', (direction) => {
    const nodes = [
      { id: 'root', data: { title: 'Root\n' + 'very long '.repeat(40) + '世界' } },
      { id: 'child', data: { title: 'Child 🚀\nline two' } },
    ]
    const edges = [{ id: 'edge', source: 'root', target: 'child' }]
    const result = layoutGraph(nodes, edges, direction)
    expect(result.nodes).toHaveLength(2)
    for (const node of result.nodes) {
      expect(Number.isFinite(node.position.x)).toBe(true)
      expect(Number.isFinite(node.position.y)).toBe(true)
      expect(node.data.title).toBe(nodes.find((source) => source.id === node.id).data.title)
    }
  })
})
