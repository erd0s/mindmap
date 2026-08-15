package main

import "github.com/wailsapp/wails/v3/pkg/application"

// Stable binding IDs keep frontend calls compatible when Go's reflection
// metadata is stripped from signed release builds.
func init() {
	application.RegisterBindingMethodID((*DesktopService).DeleteSubtree, 3681081292)
	application.RegisterBindingMethodID((*DesktopService).NewPickerWindow, 3897382207)
	application.RegisterBindingMethodID((*DesktopService).NewProjectWindow, 821774226)
	application.RegisterBindingMethodID((*DesktopService).Projects, 1648432611)
	application.RegisterBindingMethodID((*DesktopService).Snapshot, 2093151385)
}
