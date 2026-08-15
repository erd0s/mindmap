import { Events } from '@wailsio/runtime'
import {
  DeleteSubtree,
  NewPickerWindow,
  Projects,
  Snapshot,
} from './bindings/github.com/erd0s/mindmap/desktop/desktopservice.js'

export const backend = {
  deleteSubtree: DeleteSubtree,
  newPickerWindow: NewPickerWindow,
  projects: Projects,
  snapshot: Snapshot,
  onChanged(callback) {
    return Events.On('mindmap:changed', callback)
  },
}
