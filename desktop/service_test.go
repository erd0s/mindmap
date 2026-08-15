//go:build server

package main

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	"github.com/erd0s/mindmap/internal/store"
	_ "modernc.org/sqlite"
)

func TestDesktopServiceLoadsAndDeletesLiveData(t *testing.T) {
	home := t.TempDir()
	data := filepath.Join(home, "data")
	projectRoot := filepath.Join(home, "project")
	t.Setenv("HOME", home)
	t.Setenv("MINDMAP_DATA_DIR", data)
	if err := os.MkdirAll(projectRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(projectRoot, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	service, err := NewDesktopService()
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	project, err := service.repository.Activate(context.Background(), projectRoot)
	if err != nil {
		t.Fatal(err)
	}
	database := filepath.Join(data, "mindmap.sqlite3")
	writer, err := sql.Open("sqlite", database)
	if err != nil {
		t.Fatal(err)
	}
	defer writer.Close()
	for _, statement := range []string{
		`INSERT INTO items (project_id, item_id, parent_id, title, summary, resume, state, kind, sort_order, created_at, updated_at, revision)
		 VALUES (?, 'root', NULL, 'Root', '', '', 'open', 'goal', 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1)`,
		`INSERT INTO items (project_id, item_id, parent_id, title, summary, resume, state, kind, sort_order, created_at, updated_at, revision)
		 VALUES (?, 'child', 'root', 'Child', '', '', 'planned', 'task', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1)`,
	} {
		if _, err := writer.Exec(statement, project.ID); err != nil {
			t.Fatal(err)
		}
	}
	projects, err := service.Projects()
	if err != nil || len(projects) != 1 || projects[0].ItemCount != 2 {
		t.Fatalf("projects = %#v, err = %v", projects, err)
	}
	snapshot, err := service.Snapshot(project.ID)
	if err != nil || len(snapshot.Items) != 2 {
		t.Fatalf("snapshot = %#v, err = %v", snapshot, err)
	}
	confirmed, err := store.ConfirmSubtree(snapshot.Items, "root")
	if err != nil {
		t.Fatal(err)
	}
	notified := make(chan int64, 1)
	service.changeNotifier = func(projectID int64) { notified <- projectID }
	deleted, err := service.DeleteSubtree(project.ID, "root", confirmed)
	if err != nil || len(deleted.Deleted) != 2 {
		t.Fatalf("deleted = %#v, err = %v", deleted, err)
	}
	select {
	case got := <-notified:
		if got != project.ID {
			t.Fatalf("change notification project = %d", got)
		}
	default:
		t.Fatal("same-process deletion did not broadcast a change")
	}
}

func TestProjectRootArgumentFromSecondInstance(t *testing.T) {
	for _, test := range []struct {
		arguments []string
		want      string
	}{
		{[]string{"Mindmap", "--project-root", "/tmp/example"}, "/tmp/example"},
		{[]string{"Mindmap", "--project-root=/tmp/other"}, "/tmp/other"},
		{[]string{"Mindmap"}, ""},
	} {
		if got := projectRootArgument(test.arguments); got != test.want {
			t.Fatalf("projectRootArgument(%q) = %q, want %q", test.arguments, got, test.want)
		}
	}
}
