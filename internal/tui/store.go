package tui

import "github.com/erd0s/mindmap/internal/store"

type Project = store.Project
type Item = store.Item
type Snapshot = store.Snapshot
type ItemRevision = store.ItemRevision
type Repository = store.Repository

func DefaultDatabasePath() (string, error) { return store.DefaultDatabasePath() }

func OpenRepository(path string) (*Repository, error) { return store.Open(path, false) }

func SnapshotEqual(left, right Snapshot) bool { return store.SnapshotEqual(left, right) }

func ConfirmSubtree(items []Item, itemID string) ([]ItemRevision, error) {
	return store.ConfirmSubtree(items, itemID)
}
