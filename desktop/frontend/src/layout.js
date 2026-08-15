import dagre from '@dagrejs/dagre'
import { Position } from '@xyflow/react'

const dimensions = { width: 240, height: 42 }

export function layoutGraph(nodes, edges, direction) {
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  graph.setGraph({ rankdir: direction, ranksep: 65, nodesep: 26, marginx: 30, marginy: 30 })
  // Dagre mutates node geometry in place; each node must own its object.
  nodes.forEach((node) => graph.setNode(node.id, { ...dimensions }))
  edges.forEach((edge) => graph.setEdge(edge.source, edge.target))
  dagre.layout(graph)

  const horizontal = direction === 'LR'
  return {
    nodes: nodes.map((node) => {
      const point = graph.node(node.id)
      return {
        ...node,
        targetPosition: horizontal ? Position.Left : Position.Top,
        sourcePosition: horizontal ? Position.Right : Position.Bottom,
        position: { x: point.x - dimensions.width / 2, y: point.y - dimensions.height / 2 },
      }
    }),
    edges,
  }
}
