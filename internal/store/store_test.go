package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	_ "modernc.org/sqlite"
)

func TestActivateResolveAndDeleteSubtree(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	projectRoot := filepath.Join(home, "Dev", "example")
	if err := os.MkdirAll(projectRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(projectRoot, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	database := filepath.Join(t.TempDir(), "mindmap.sqlite3")
	repository, err := Open(database, false)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	project, err := repository.Activate(context.Background(), projectRoot)
	if err != nil {
		t.Fatal(err)
	}
	if project.RoutePath != "/dev/example" || !project.Active {
		t.Fatalf("unexpected activated project: %#v", project)
	}

	writer, err := sql.Open("sqlite", database)
	if err != nil {
		t.Fatal(err)
	}
	defer writer.Close()
	for _, item := range []struct{ id, parent, title string }{
		{"root", "", "Root"}, {"branch", "root", "Branch"}, {"leaf", "branch", "Leaf"}, {"sibling", "root", "Sibling"},
	} {
		var parent any
		if item.parent != "" {
			parent = item.parent
		}
		if _, err := writer.Exec(`INSERT INTO items
			(project_id, item_id, parent_id, title, summary, resume, state, kind,
			 sort_order, created_at, updated_at, revision)
			VALUES (?, ?, ?, ?, '', '', 'open', 'task', 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1)`,
			project.ID, item.id, parent, item.title); err != nil {
			t.Fatal(err)
		}
	}

	beforeDelete, err := repository.LoadSnapshot(context.Background(), project.ID)
	if err != nil {
		t.Fatal(err)
	}
	confirmed, err := ConfirmSubtree(beforeDelete.Items, "branch")
	if err != nil {
		t.Fatal(err)
	}
	result, err := repository.DeleteSubtree(context.Background(), project.ID, "branch", confirmed)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Deleted) != 2 || result.Deleted[0] != "leaf" || result.Deleted[1] != "branch" {
		t.Fatalf("deleted = %#v", result.Deleted)
	}
	snapshot, err := repository.LoadSnapshot(context.Background(), project.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.Items) != 2 || snapshot.Items[0].ID != "root" || snapshot.Items[1].ID != "sibling" {
		t.Fatalf("remaining items = %#v", snapshot.Items)
	}
	if len(snapshot.UserDeletedBranches) != 2 ||
		snapshot.UserDeletedBranches[0] != (DeletedBranch{ID: "branch", Title: "Branch"}) ||
		snapshot.UserDeletedBranches[1] != (DeletedBranch{ID: "leaf", Title: "Leaf"}) {
		t.Fatalf("user-deleted branches = %#v", snapshot.UserDeletedBranches)
	}
	var eventCount int
	if err := writer.QueryRow(`SELECT count(*) FROM events WHERE project_id = ? AND event_type = 'item.subtree_deleted'`, project.ID).Scan(&eventCount); err != nil {
		t.Fatal(err)
	}
	if eventCount != 1 {
		t.Fatalf("deletion events = %d", eventCount)
	}
	var payloadJSON string
	if err := writer.QueryRow(`SELECT payload_json FROM events
		WHERE project_id = ? AND event_type = 'item.subtree_deleted'`, project.ID).Scan(&payloadJSON); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Deleted      []string `json:"deleted"`
		DeletedItems []struct {
			ID    string `json:"id"`
			Title string `json:"title"`
		} `json:"deleted_items"`
	}
	if err := json.Unmarshal([]byte(payloadJSON), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.DeletedItems) != 2 || payload.DeletedItems[0].ID != "leaf" ||
		payload.DeletedItems[0].Title != "Leaf" || payload.DeletedItems[1].ID != "branch" ||
		payload.DeletedItems[1].Title != "Branch" {
		t.Fatalf("deletion payload = %#v", payload)
	}
}

func TestSnapshotReplaysLegacyAndCurrentDeletionEvents(t *testing.T) {
	database := filepath.Join(t.TempDir(), "events.sqlite3")
	repository, err := Open(database, false)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	now := "2026-01-01T00:00:00Z"
	if _, err := repository.db.Exec(`INSERT INTO projects
		(id, root_path, route_path, name, active, concept_model_version, created_at, updated_at, activated_at)
		VALUES (1, '/tmp/events', '/events', 'events', 1, 2, ?, ?, ?)`, now, now, now); err != nil {
		t.Fatal(err)
	}
	for _, event := range []struct{ eventType, itemID, payload string }{
		{"item.subtree_deleted", "legacy", `{"deleted":["legacy"],"source":"user"}`},
		{"item.subtree_deleted", "current", `{"deleted":["current"],"deleted_items":[{"id":"current","title":"Current title"}],"source":"user"}`},
		{"item.subtree_deleted", "compat", `{"DELETED":["compat"],"DELETED_ITEMS":[{"ID":"compat","TITLE":null}],"source":"user"}`},
		{"item.created", "legacy", `{}`},
	} {
		if _, err := repository.db.Exec(`INSERT INTO events
			(project_id, event_type, item_id, payload_json, created_at) VALUES (1, ?, ?, ?, ?)`,
			event.eventType, event.itemID, event.payload, now); err != nil {
			t.Fatal(err)
		}
	}
	snapshot, err := repository.LoadSnapshot(context.Background(), 1)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.UserDeletedBranches) != 2 ||
		snapshot.UserDeletedBranches[0] != (DeletedBranch{ID: "compat", Title: "compat"}) ||
		snapshot.UserDeletedBranches[1] != (DeletedBranch{ID: "current", Title: "Current title"}) {
		t.Fatalf("replayed tombstones = %#v", snapshot.UserDeletedBranches)
	}
	if _, err := repository.db.Exec(`INSERT INTO events
		(project_id, event_type, item_id, payload_json, created_at)
		VALUES (1, 'item.restored', 'current', '{}', ?)`, now); err != nil {
		t.Fatal(err)
	}
	snapshot, err = repository.LoadSnapshot(context.Background(), 1)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.UserDeletedBranches) != 1 ||
		snapshot.UserDeletedBranches[0] != (DeletedBranch{ID: "compat", Title: "compat"}) {
		t.Fatalf("restored tombstone was not cleared: %#v", snapshot.UserDeletedBranches)
	}
}

func TestSnapshotRejectsMalformedDeletionPayload(t *testing.T) {
	for _, payload := range []string{
		`{`,
		`{}`,
		`{"deleted":["one"],"deleted_items":[{"id":"two","title":"Two"}]}`,
	} {
		t.Run(payload, func(t *testing.T) {
			database := filepath.Join(t.TempDir(), "malformed.sqlite3")
			repository, err := Open(database, false)
			if err != nil {
				t.Fatal(err)
			}
			defer repository.Close()
			now := "2026-01-01T00:00:00Z"
			if _, err := repository.db.Exec(`INSERT INTO projects
				(id, root_path, route_path, name, active, concept_model_version, created_at, updated_at, activated_at)
				VALUES (1, '/tmp/malformed', '/malformed', 'malformed', 1, 2, ?, ?, ?)`, now, now, now); err != nil {
				t.Fatal(err)
			}
			if _, err := repository.db.Exec(`INSERT INTO events
				(project_id, event_type, item_id, payload_json, created_at)
				VALUES (1, 'item.subtree_deleted', 'broken', ?, ?)`, payload, now); err != nil {
				t.Fatal(err)
			}
			if _, err := repository.LoadSnapshot(context.Background(), 1); err == nil ||
				!strings.Contains(err.Error(), "invalid item.subtree_deleted payload") {
				t.Fatalf("snapshot error = %v", err)
			}
		})
	}
}

func TestDeleteSubtreeRejectsAChangedConfirmation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("MINDMAP_HOME_DIR", home)
	root := filepath.Join(home, "project")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(root, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	repository, err := Open(filepath.Join(t.TempDir(), "mindmap.sqlite3"), false)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	project, err := repository.Activate(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"root", "child"} {
		parent := any(nil)
		if id == "child" {
			parent = "root"
		}
		if _, err := repository.db.Exec(`INSERT INTO items
			(project_id, item_id, parent_id, title, summary, resume, state, kind,
			 sort_order, created_at, updated_at, revision)
			VALUES (?, ?, ?, ?, '', '', 'open', 'task', 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1)`,
			project.ID, id, parent, id); err != nil {
			t.Fatal(err)
		}
	}
	snapshot, err := repository.LoadSnapshot(context.Background(), project.ID)
	if err != nil {
		t.Fatal(err)
	}
	confirmed, err := ConfirmSubtree(snapshot.Items, "root")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := repository.db.Exec(`INSERT INTO items
		(project_id, item_id, parent_id, title, summary, resume, state, kind,
		 sort_order, created_at, updated_at, revision)
		VALUES (?, 'late', 'child', 'Late child', '', '', 'planned', 'task', 0,
		'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1)`, project.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := repository.DeleteSubtree(context.Background(), project.ID, "root", confirmed); !errors.Is(err, ErrSubtreeChanged) {
		t.Fatalf("delete error = %v, want ErrSubtreeChanged", err)
	}
	remaining, err := repository.LoadSnapshot(context.Background(), project.ID)
	if err != nil || len(remaining.Items) != 3 {
		t.Fatalf("changed subtree was modified: %#v, %v", remaining.Items, err)
	}
}

func TestOpenReadOnlyDoesNotCreateMissingDatabase(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.sqlite3")
	if _, err := Open(path, true); err == nil {
		t.Fatal("read-only open created a missing database")
	}
	if _, err := OpenExisting(path); err == nil {
		t.Fatal("migrating read open created a missing database")
	}
}

func TestOpenUpgradesLegacyColumns(t *testing.T) {
	database := filepath.Join(t.TempDir(), "legacy.sqlite3")
	db, err := sql.Open("sqlite", database)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`
		CREATE TABLE projects (
			id INTEGER PRIMARY KEY, root_path TEXT NOT NULL UNIQUE,
			route_path TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
			active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL, activated_at TEXT NOT NULL, deactivated_at TEXT
		);
		CREATE TABLE sessions (
			id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, host TEXT NOT NULL,
			session_id TEXT NOT NULL, transcript_path TEXT, transcript_cursor INTEGER NOT NULL DEFAULT 0,
			started_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, ended_at TEXT
		);
		CREATE TABLE turns (
			id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, session_pk INTEGER NOT NULL,
			interaction_id TEXT NOT NULL, prompt_excerpt TEXT, started_at TEXT NOT NULL,
			checkpointed_at TEXT, checkpoint_summary TEXT, last_assistant_message TEXT
		);
		CREATE TABLE items (
			project_id INTEGER NOT NULL, item_id TEXT NOT NULL, parent_id TEXT,
			title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
			kind TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL, updated_at TEXT NOT NULL, settled_at TEXT,
			source_session_pk INTEGER, source_interaction_id TEXT, revision INTEGER NOT NULL DEFAULT 1,
			PRIMARY KEY(project_id, item_id)
		);
	`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	repository, err := Open(database, false)
	if err != nil {
		t.Fatal(err)
	}
	repository.Close()

	db, err = sql.Open("sqlite", database)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	for table, required := range map[string][]string{
		"projects": {"concept_model_version"},
		"sessions": {"transcript_device", "transcript_inode", "transcript_anchor_length", "transcript_anchor_hash"},
		"turns":    {"checkpoint_payload_hash"},
		"items":    {"resume"},
	} {
		rows, err := db.Query("PRAGMA table_info(" + table + ")")
		if err != nil {
			t.Fatal(err)
		}
		columns := make(map[string]bool)
		for rows.Next() {
			var cid, notNull, primaryKey int
			var name, columnType string
			var defaultValue sql.NullString
			if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
				t.Fatal(err)
			}
			columns[name] = true
		}
		rows.Close()
		for _, name := range required {
			if !columns[name] {
				t.Fatalf("%s.%s was not migrated", table, name)
			}
		}
	}
}

func TestHealthDetectsForeignKeyDamage(t *testing.T) {
	database := filepath.Join(t.TempDir(), "damaged.sqlite3")
	repository, err := Open(database, false)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := repository.db.Exec("PRAGMA foreign_keys = OFF"); err != nil {
		t.Fatal(err)
	}
	if _, err := repository.db.Exec(`INSERT INTO sessions
		(project_id, host, session_id, started_at, last_seen_at)
		VALUES (999, 'unknown', 'orphan', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')`); err != nil {
		t.Fatal(err)
	}
	if err := repository.Health(context.Background()); err == nil {
		t.Fatal("health check accepted an orphaned foreign key")
	}
	repository.Close()
}

func TestHealthAndConfirmationRejectCyclicConceptGraph(t *testing.T) {
	database := filepath.Join(t.TempDir(), "cyclic.sqlite3")
	repository, err := Open(database, false)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	now := "2026-01-01T00:00:00Z"
	if _, err := repository.db.Exec(`INSERT INTO projects
		(id, root_path, route_path, name, active, concept_model_version, created_at, updated_at, activated_at)
		VALUES (1, '/tmp/cyclic', '/cyclic', 'cyclic', 1, 2, ?, ?, ?)`, now, now, now); err != nil {
		t.Fatal(err)
	}
	tx, err := repository.db.BeginTx(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, item := range []struct{ id, parent string }{{"cycle-a", "cycle-b"}, {"cycle-b", "cycle-a"}} {
		if _, err := tx.Exec(`INSERT INTO items
			(project_id, item_id, parent_id, title, summary, resume, state, kind,
			 sort_order, created_at, updated_at, revision)
			VALUES (1, ?, ?, ?, '', '', 'open', 'task', 0, ?, ?, 1)`,
			item.id, item.parent, item.id, now, now); err != nil {
			tx.Rollback()
			t.Fatal(err)
		}
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	if err := repository.Health(context.Background()); err == nil || !strings.Contains(err.Error(), "contains a cycle") {
		t.Fatalf("health error = %v", err)
	}
	if _, err := ConfirmSubtree([]Item{
		{ID: "cycle-a", ParentID: "cycle-b", Revision: 1},
		{ID: "cycle-b", ParentID: "cycle-a", Revision: 1},
	}, "cycle-a"); err == nil || !strings.Contains(err.Error(), "contains a cycle") {
		t.Fatalf("confirmation error = %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	result, err := repository.DeleteSubtree(ctx, 1, "cycle-a", []ItemRevision{
		{ID: "cycle-a", Revision: 1},
		{ID: "cycle-b", Revision: 1},
	})
	if err != nil {
		t.Fatalf("cycle-safe repair deletion failed: %v", err)
	}
	if len(result.Deleted) != 2 || result.Deleted[0] != "cycle-b" || result.Deleted[1] != "cycle-a" {
		t.Fatalf("cycle deletion = %#v", result.Deleted)
	}
}

func TestWriteTransactionsReserveTheWriterBeforeReading(t *testing.T) {
	home := t.TempDir()
	t.Setenv("MINDMAP_HOME_DIR", home)
	root := filepath.Join(home, "project")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(root, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	database := filepath.Join(t.TempDir(), "mindmap.sqlite3")
	repository, err := Open(database, false)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	project, err := repository.Activate(context.Background(), root)
	if err != nil {
		t.Fatal(err)
	}
	otherWriter, err := sql.Open("sqlite", database)
	if err != nil {
		t.Fatal(err)
	}
	defer otherWriter.Close()
	if _, err := otherWriter.Exec("PRAGMA busy_timeout = 25"); err != nil {
		t.Fatal(err)
	}

	tx, err := repository.writeDB.BeginTx(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	_, writeErr := otherWriter.Exec("UPDATE projects SET name = 'raced' WHERE id = ?", project.ID)
	if writeErr == nil || (!strings.Contains(strings.ToLower(writeErr.Error()), "locked") &&
		!strings.Contains(strings.ToLower(writeErr.Error()), "busy")) {
		tx.Rollback()
		t.Fatalf("competing writer error = %v, want a lock before the transaction's first read", writeErr)
	}
	if err := tx.Rollback(); err != nil {
		t.Fatal(err)
	}
	if _, err := otherWriter.Exec("UPDATE projects SET name = 'after' WHERE id = ?", project.ID); err != nil {
		t.Fatalf("competing writer remained blocked after rollback: %v", err)
	}
}

func TestRouteForRootUsesConfiguredHome(t *testing.T) {
	home := t.TempDir()
	t.Setenv("MINDMAP_HOME_DIR", home)
	root := filepath.Join(home, "Dev", "Case Sensitive")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	route, err := RouteForRoot(root)
	if err != nil {
		t.Fatal(err)
	}
	if route != "/dev/case%20sensitive" {
		t.Fatalf("route = %q", route)
	}
}

func TestRouteForRootMatchesSharedPythonGoldenCases(t *testing.T) {
	home := t.TempDir()
	t.Setenv("MINDMAP_HOME_DIR", home)
	content, err := os.ReadFile(filepath.Join("..", "..", "tests", "fixtures", "route-cases.json"))
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name         string `json:"name"`
		RelativePath string `json:"relative_path"`
		Route        string `json:"route"`
	}
	if err := json.Unmarshal(content, &cases); err != nil {
		t.Fatal(err)
	}
	for _, testCase := range cases {
		t.Run(testCase.Name, func(t *testing.T) {
			root := filepath.Join(home, testCase.RelativePath)
			if err := os.MkdirAll(root, 0o755); err != nil {
				t.Fatal(err)
			}
			route, err := RouteForRoot(root)
			if err != nil {
				t.Fatal(err)
			}
			if route != testCase.Route {
				t.Fatalf("route = %q, want shared golden %q", route, testCase.Route)
			}
		})
	}
}

func TestResolveProjectAlwaysChoosesDeepestAncestor(t *testing.T) {
	database := filepath.Join(t.TempDir(), "mindmap.sqlite3")
	repository, err := Open(database, false)
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	home := t.TempDir()
	parent := filepath.Join(home, "parent")
	child := filepath.Join(parent, "child")
	for _, root := range []string{parent, child} {
		if err := os.MkdirAll(root, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	now := "2026-01-01T00:00:00Z"
	if _, err := repository.db.Exec(`INSERT INTO projects
		(id, root_path, route_path, name, active, concept_model_version, created_at, updated_at, activated_at)
		VALUES (1, ?, '/parent', 'parent', 1, 2, ?, '2026-02-01T00:00:00Z', ?),
		       (2, ?, '/parent/child', 'child', 1, 2, ?, '2026-01-01T00:00:00Z', ?)`,
		parent, now, now, child, now, now); err != nil {
		t.Fatal(err)
	}
	resolved, err := repository.ResolveProject(filepath.Join(child, "nested"), "")
	if err != nil {
		t.Fatal(err)
	}
	if resolved.ID != 2 {
		t.Fatalf("resolved project = %d, want deepest project 2", resolved.ID)
	}
}

func TestWindowsDatabaseURLHasNoDriveLetterAuthority(t *testing.T) {
	database := databaseURL(`C:\Users\tester\mindmap.sqlite3`, "windows")
	value := database.String()
	if value != "file:///C:/Users/tester/mindmap.sqlite3" {
		t.Fatalf("database URL = %q", value)
	}
}

func TestWindowsProjectContainmentIgnoresPathCase(t *testing.T) {
	if !pathWithin(`C:\Users\Test\Project\child`, `c:\users\test\project`, "windows") {
		t.Fatal("Windows project containment should ignore path case")
	}
}
