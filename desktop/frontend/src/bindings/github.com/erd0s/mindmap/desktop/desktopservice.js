// @ts-check
// Generated-compatible Wails bindings. IDs are registered in desktop/bindings.go.
import { Call as $Call } from "/wails/runtime.js"

export function DeleteSubtree(projectID, itemID, confirmed) {
  return $Call.ByID(3681081292, projectID, itemID, confirmed)
}

export function NewPickerWindow() {
  return $Call.ByID(3897382207)
}

export function Projects() {
  return $Call.ByID(1648432611)
}

export function Snapshot(projectID) {
  return $Call.ByID(2093151385, projectID)
}
