import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const styles = readFileSync(new URL('./styles.css', import.meta.url), 'utf8')

describe('desktop interaction styles', () => {
  it('uses Wails drag regions while leaving title-bar controls interactive', () => {
    expect(styles).toMatch(/\.topbar\s*\{[^}]*--wails-draggable:\s*drag;/s)
    expect(styles).toMatch(/\.topbar button\s*\{[^}]*--wails-draggable:\s*no-drag;/s)
    expect(styles).toMatch(/\.picker-shell\s*\{[^}]*--wails-draggable:\s*drag;/s)
    expect(styles).toMatch(/\.picker-header\s*\{[^}]*--wails-draggable:\s*drag;/s)
    expect(styles).toMatch(/\.project-list\s*\{[^}]*--wails-draggable:\s*no-drag;/s)
  })

  it('keeps graph chrome clear of the macOS traffic-light controls', () => {
    expect(styles).toMatch(/\.topbar\s*\{[^}]*padding:\s*6px 14px 0 96px;/s)
  })

  it('shows keyboard focus on graph nodes', () => {
    expect(styles).toMatch(/\.react-flow__node:focus-visible \.thought-node\s*\{/)
    expect(styles).toMatch(/\.react-flow__node:focus\s*\{\s*outline:\s*none;/)
  })

  it('prevents accidental webview text selection', () => {
    expect(styles).toMatch(/body\s*\{[^}]*user-select:\s*none;/s)
  })
})
