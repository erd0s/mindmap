import { Handle } from '@xyflow/react'

export default function ThoughtNode({ data, targetPosition, sourcePosition, selected }) {
  const classes = [
    'thought-node',
    `state-${data.state}`,
    data.isRoot && 'root',
    data.isFrontier && 'frontier',
    selected && 'selected',
  ].filter(Boolean).join(' ')

  return (
    <div className={classes}>
      <Handle type="target" position={targetPosition} />
      <span className={`dot dot-${data.state}${data.isFrontier ? ' glow' : ''}`} />
      <span className="node-title">{data.title}</span>
      <Handle type="source" position={sourcePosition} />
    </div>
  )
}
