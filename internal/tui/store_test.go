package tui

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"
	"time"

	_ "modernc.org/sqlite"
)

func createTestDatabase(t *testing.T) (string, *sql.DB) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "mindmap.sqlite3")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	statements := []string{
		`PRAGMA journal_mode = WAL`,
		`CREATE TABLE projects (
			id INTEGER PRIMARY KEY, root_path TEXT NOT NULL, route_path TEXT NOT NULL,
			name TEXT NOT NULL, active INTEGER NOT NULL, updated_at TEXT NOT NULL
		)`,
		`CREATE TABLE items (
			project_id INTEGER NOT NULL, item_id TEXT NOT NULL, parent_id TEXT,
			title TEXT NOT NULL, summary TEXT NOT NULL, resume TEXT NOT NULL,
			state TEXT NOT NULL, kind TEXT NOT NULL, sort_order INTEGER NOT NULL,
			created_at TEXT NOT NULL, updated_at TEXT NOT NULL, settled_at TEXT,
			revision INTEGER NOT NULL
		)`,
		`INSERT INTO projects VALUES
			(1, '/home/test', '/test', 'test', 1, '2026-01-01T00:00:00Z'),
			(2, '/home/test/deep', '/test/deep', 'deep', 1, '2026-01-01T00:00:00Z')`,
		`INSERT INTO items VALUES
			(2, 'root', NULL, 'Root node', 'Summary', 'Resume here', 'open', 'goal', 0,
			 '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL, 1)`,
	}
	for _, statement := range statements {
		if _, err := db.Exec(statement); err != nil {
			db.Close()
			t.Fatal(err)
		}
	}
	return path, db
}

func TestRepositoryResolvesDeepestProjectAndLoadsGraph(t *testing.T) {
	path, writer := createTestDatabase(t)
	defer writer.Close()
	repository, err := OpenRepository(path)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	project, err := repository.ResolveProject("/home/test/deep/subdir", "")
	if err != nil {
		t.Fatal(err)
	}
	if project.ID != 2 {
		t.Fatalf("resolved project = %d", project.ID)
	}
	ctx := context.Background()
	snapshot, err := repository.LoadSnapshot(ctx, project.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.Items) != 1 || snapshot.Items[0].Title != "Root node" {
		t.Fatalf("unexpected snapshot: %#v", snapshot)
	}
}

func TestDataVersionDetectsExternalGraphChanges(t *testing.T) {
	path, writer := createTestDatabase(t)
	defer writer.Close()
	repository, err := OpenRepository(path)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	before, err := repository.DataVersion(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Exec(`INSERT INTO items VALUES
		(2, 'child', 'root', 'Live child', '', '', 'planned', 'task', 1,
		 '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z', NULL, 1)`); err != nil {
		t.Fatal(err)
	}
	after, err := repository.DataVersion(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if after == before {
		t.Fatalf("data_version did not change: %d", before)
	}
	snapshot, err := repository.LoadSnapshot(ctx, 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.Items) != 2 || snapshot.Items[1].ID != "child" {
		t.Fatalf("live snapshot was not refreshed: %#v", snapshot.Items)
	}
}
