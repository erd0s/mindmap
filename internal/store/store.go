// Package store owns the stable SQLite boundary shared by Mindmap's terminal
// and desktop viewers. Agent hooks may be upgraded independently as long as
// they preserve this schema.
package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	_ "modernc.org/sqlite"
)

type Project struct {
	ID           int64  `json:"id"`
	RootPath     string `json:"root_path"`
	RoutePath    string `json:"route_path"`
	Name         string `json:"name"`
	Active       bool   `json:"active"`
	UpdatedAt    string `json:"updated_at"`
	ItemCount    int    `json:"item_count,omitempty"`
	SessionCount int    `json:"session_count,omitempty"`
	OpenCount    int    `json:"open_count,omitempty"`
	PlannedCount int    `json:"planned_count,omitempty"`
}

type Item struct {
	ID        string `json:"id"`
	ParentID  string `json:"parent_id,omitempty"`
	Title     string `json:"title"`
	Summary   string `json:"summary"`
	Resume    string `json:"resume"`
	State     string `json:"state"`
	Kind      string `json:"kind"`
	SortOrder int    `json:"sort_order"`
	CreatedAt string `json:"created_at"`
	UpdatedAt string `json:"updated_at"`
	SettledAt string `json:"settled_at,omitempty"`
	Revision  int    `json:"revision"`
}

type Snapshot struct {
	Project             Project         `json:"project"`
	Items               []Item          `json:"items"`
	UserDeletedBranches []DeletedBranch `json:"user_deleted_branches"`
}

type DeletedBranch struct {
	ID    string `json:"id"`
	Title string `json:"title"`
}

type DeleteResult struct {
	ProjectID int64    `json:"project_id"`
	Deleted   []string `json:"deleted"`
}

type ItemRevision struct {
	ID       string `json:"id"`
	Revision int    `json:"revision"`
}

var ErrSubtreeChanged = errors.New("subtree changed since confirmation; review it and confirm again")

type Repository struct {
	db       *sql.DB
	writeDB  *sql.DB
	path     string
	readOnly bool
}

func DefaultDatabasePath() (string, error) {
	if override := os.Getenv("MINDMAP_DATA_DIR"); override != "" {
		return filepath.Join(expandHome(override), "mindmap.sqlite3"), nil
	}
	base := os.Getenv("XDG_DATA_HOME")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", fmt.Errorf("find home directory: %w", err)
		}
		base = filepath.Join(home, ".local", "share")
	}
	return filepath.Join(expandHome(base), "mindmap", "mindmap.sqlite3"), nil
}

func expandHome(value string) string {
	if value == "~" || strings.HasPrefix(value, "~"+string(filepath.Separator)) {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, strings.TrimPrefix(value, "~"+string(filepath.Separator)))
		}
	}
	return value
}

func Open(path string, readOnly bool) (*Repository, error) {
	abs, err := filepath.Abs(expandHome(path))
	if err != nil {
		return nil, fmt.Errorf("resolve database path: %w", err)
	}
	if readOnly {
		if _, err := os.Stat(abs); err != nil {
			if errors.Is(err, os.ErrNotExist) {
				return nil, fmt.Errorf("mindmap database not found at %s", abs)
			}
			return nil, fmt.Errorf("inspect database: %w", err)
		}
	} else {
		if err := os.MkdirAll(filepath.Dir(abs), 0o700); err != nil {
			return nil, fmt.Errorf("create Mindmap data directory: %w", err)
		}
		if file, err := os.OpenFile(abs, os.O_CREATE|os.O_WRONLY, 0o600); err != nil {
			return nil, fmt.Errorf("create Mindmap database: %w", err)
		} else if err := file.Close(); err != nil {
			return nil, fmt.Errorf("close Mindmap database: %w", err)
		}
		_ = os.Chmod(abs, 0o600)
	}

	u := databaseURL(abs, runtime.GOOS)
	query := u.Query()
	if readOnly {
		query.Set("mode", "ro")
		query.Add("_pragma", "query_only(1)")
	} else {
		query.Set("mode", "rwc")
		query.Add("_pragma", "journal_mode(WAL)")
		query.Add("_pragma", "foreign_keys(1)")
	}
	query.Add("_pragma", "busy_timeout(10000)")
	u.RawQuery = query.Encode()
	db, err := sql.Open("sqlite", u.String())
	if err != nil {
		return nil, fmt.Errorf("open Mindmap database: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("open Mindmap database: %w", err)
	}
	repository := &Repository{db: db, path: abs, readOnly: readOnly}
	if !readOnly {
		if err := repository.ensureSchema(); err != nil {
			db.Close()
			return nil, err
		}
		// Keep reads on the ordinary connection and mutations on a connection
		// whose transactions begin IMMEDIATE. A writer therefore reserves its
		// slot before reading without making snapshot reads take write locks.
		writeURL := u
		writeQuery := writeURL.Query()
		writeQuery.Set("_txlock", "immediate")
		writeURL.RawQuery = writeQuery.Encode()
		writeDB, err := sql.Open("sqlite", writeURL.String())
		if err != nil {
			db.Close()
			return nil, fmt.Errorf("open Mindmap writer: %w", err)
		}
		writeDB.SetMaxOpenConns(1)
		writeDB.SetMaxIdleConns(1)
		if err := writeDB.Ping(); err != nil {
			writeDB.Close()
			db.Close()
			return nil, fmt.Errorf("open Mindmap writer: %w", err)
		}
		repository.writeDB = writeDB
	}
	return repository, nil
}

func databaseURL(path, goos string) url.URL {
	slashPath := strings.ReplaceAll(path, "\\", "/")
	// url.URL treats an unprefixed drive letter as a URI authority. SQLite
	// expects an empty authority and an absolute /C:/... path instead.
	if goos == "windows" && len(slashPath) >= 2 && slashPath[1] == ':' {
		slashPath = "/" + slashPath
	}
	return url.URL{Scheme: "file", Path: slashPath}
}

func OpenDefault(readOnly bool) (*Repository, error) {
	path, err := DefaultDatabasePath()
	if err != nil {
		return nil, err
	}
	return Open(path, readOnly)
}

// OpenExisting opens an existing database with migrations enabled. Commands
// that primarily read still need this writable open so an older installation
// is upgraded before newer columns are queried.
func OpenExisting(path string) (*Repository, error) {
	abs, err := filepath.Abs(expandHome(path))
	if err != nil {
		return nil, fmt.Errorf("resolve database path: %w", err)
	}
	if _, err := os.Stat(abs); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("mindmap database not found at %s", abs)
		}
		return nil, fmt.Errorf("inspect database: %w", err)
	}
	return Open(abs, false)
}

func (r *Repository) Close() error {
	if r.writeDB != nil {
		return errors.Join(r.writeDB.Close(), r.db.Close())
	}
	return r.db.Close()
}
func (r *Repository) Path() string { return r.path }

func (r *Repository) ensureSchema() error {
	_, err := r.db.Exec(`
		CREATE TABLE IF NOT EXISTS projects (
			id INTEGER PRIMARY KEY,
			root_path TEXT NOT NULL UNIQUE,
			route_path TEXT NOT NULL UNIQUE COLLATE NOCASE,
			name TEXT NOT NULL,
			active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
			concept_model_version INTEGER NOT NULL DEFAULT 2,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			activated_at TEXT NOT NULL,
			deactivated_at TEXT
		);
		CREATE TABLE IF NOT EXISTS sessions (
			id INTEGER PRIMARY KEY,
			project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
			host TEXT NOT NULL CHECK (host IN ('codex', 'claude', 'unknown')),
			session_id TEXT NOT NULL,
			transcript_path TEXT,
			transcript_cursor INTEGER NOT NULL DEFAULT 0,
			transcript_device INTEGER,
			transcript_inode INTEGER,
			transcript_anchor_length INTEGER NOT NULL DEFAULT 0,
			transcript_anchor_hash TEXT,
			started_at TEXT NOT NULL,
			last_seen_at TEXT NOT NULL,
			ended_at TEXT,
			UNIQUE(host, session_id)
		);
		CREATE TABLE IF NOT EXISTS turns (
			id INTEGER PRIMARY KEY,
			project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
			session_pk INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
			interaction_id TEXT NOT NULL,
			prompt_excerpt TEXT,
			started_at TEXT NOT NULL,
			checkpointed_at TEXT,
			checkpoint_summary TEXT,
			checkpoint_payload_hash TEXT,
			last_assistant_message TEXT,
			UNIQUE(session_pk, interaction_id)
		);
		CREATE TABLE IF NOT EXISTS items (
			project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
			item_id TEXT NOT NULL,
			parent_id TEXT,
			title TEXT NOT NULL,
			summary TEXT NOT NULL DEFAULT '',
			resume TEXT NOT NULL DEFAULT '',
			state TEXT NOT NULL CHECK (state IN ('planned', 'open', 'settled')),
			kind TEXT NOT NULL CHECK (kind IN ('goal', 'thread', 'decision', 'task', 'question', 'note')),
			sort_order INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			settled_at TEXT,
			source_session_pk INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
			source_interaction_id TEXT,
			revision INTEGER NOT NULL DEFAULT 1,
			PRIMARY KEY(project_id, item_id),
			FOREIGN KEY(project_id, parent_id) REFERENCES items(project_id, item_id)
				DEFERRABLE INITIALLY DEFERRED
		);
		CREATE TABLE IF NOT EXISTS events (
			id INTEGER PRIMARY KEY,
			project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
			session_pk INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
			interaction_id TEXT,
			event_type TEXT NOT NULL,
			item_id TEXT,
			payload_json TEXT NOT NULL,
			idempotency_key TEXT UNIQUE,
			created_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS messages (
			id INTEGER PRIMARY KEY,
			project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
			session_pk INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
			message_key TEXT NOT NULL,
			role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
			content TEXT NOT NULL,
			message_at TEXT,
			source_offset INTEGER NOT NULL DEFAULT 0,
			UNIQUE(session_pk, message_key)
		);
		CREATE INDEX IF NOT EXISTS idx_projects_active ON projects(active, root_path);
		CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id, id DESC);
		CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_pk, id);
	`)
	if err != nil {
		return fmt.Errorf("initialise Mindmap database: %w", err)
	}
	conn, err := r.db.Conn(context.Background())
	if err != nil {
		return fmt.Errorf("prepare Mindmap schema upgrade: %w", err)
	}
	defer conn.Close()
	if _, err := conn.ExecContext(context.Background(), "BEGIN IMMEDIATE"); err != nil {
		return fmt.Errorf("lock Mindmap schema upgrade: %w", err)
	}
	committed := false
	defer func() {
		if !committed {
			_, _ = conn.ExecContext(context.Background(), "ROLLBACK")
		}
	}()
	migrations := map[string][]string{
		"sessions": {
			"transcript_device INTEGER",
			"transcript_inode INTEGER",
			"transcript_anchor_length INTEGER NOT NULL DEFAULT 0",
			"transcript_anchor_hash TEXT",
		},
		"turns": {
			"checkpoint_payload_hash TEXT",
		},
		"projects": {
			"concept_model_version INTEGER NOT NULL DEFAULT 1",
		},
		"items": {
			"resume TEXT NOT NULL DEFAULT ''",
		},
	}
	for table, columns := range migrations {
		rows, err := conn.QueryContext(context.Background(), "PRAGMA table_info("+table+")")
		if err != nil {
			return fmt.Errorf("inspect %s schema: %w", table, err)
		}
		existing := make(map[string]bool)
		for rows.Next() {
			var cid, notNull, primaryKey int
			var name, columnType string
			var defaultValue sql.NullString
			if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
				rows.Close()
				return fmt.Errorf("read %s schema: %w", table, err)
			}
			existing[name] = true
		}
		if err := rows.Close(); err != nil {
			return fmt.Errorf("finish %s schema read: %w", table, err)
		}
		for _, definition := range columns {
			name := strings.Fields(definition)[0]
			if existing[name] {
				continue
			}
			if _, err := conn.ExecContext(context.Background(), "ALTER TABLE "+table+" ADD COLUMN "+definition); err != nil {
				return fmt.Errorf("upgrade %s.%s: %w", table, name, err)
			}
		}
	}
	if _, err := conn.ExecContext(context.Background(), "COMMIT"); err != nil {
		return fmt.Errorf("finish Mindmap schema upgrade: %w", err)
	}
	committed = true
	return nil
}

func (r *Repository) ResolveProject(root, route string) (Project, error) {
	projects, err := r.Projects(context.Background())
	if err != nil {
		return Project{}, err
	}
	if route != "" {
		normalized := "/" + strings.ToLower(strings.Trim(route, "/"))
		for _, project := range projects {
			if strings.EqualFold(project.RoutePath, normalized) {
				return project, nil
			}
		}
		return Project{}, fmt.Errorf("no Mindmap project has route %q", normalized)
	}
	if root == "" {
		var err error
		root, err = os.Getwd()
		if err != nil {
			return Project{}, fmt.Errorf("find current directory: %w", err)
		}
	}
	candidate, err := CanonicalPath(root)
	if err != nil {
		return Project{}, err
	}
	var best Project
	for _, project := range projects {
		if !PathWithin(candidate, project.RootPath) {
			continue
		}
		if best.RootPath == "" || len(filepath.Clean(project.RootPath)) > len(filepath.Clean(best.RootPath)) {
			best = project
		}
	}
	if best.RootPath != "" {
		return best, nil
	}
	return Project{}, fmt.Errorf("no Mindmap project contains %s", candidate)
}

func (r *Repository) Projects(ctx context.Context) ([]Project, error) {
	rows, err := r.db.QueryContext(ctx, `
		SELECT p.id, p.root_path, p.route_path, p.name, p.active, p.updated_at,
		       (SELECT count(*) FROM items i WHERE i.project_id = p.id),
		       (SELECT count(*) FROM sessions s WHERE s.project_id = p.id),
		       (SELECT count(*) FROM items i WHERE i.project_id = p.id AND i.state = 'open'),
		       (SELECT count(*) FROM items i WHERE i.project_id = p.id AND i.state = 'planned')
		FROM projects p ORDER BY p.updated_at DESC, length(p.root_path) DESC`)
	if err != nil {
		return nil, fmt.Errorf("read projects: %w", err)
	}
	defer rows.Close()
	projects := make([]Project, 0)
	for rows.Next() {
		var project Project
		if err := rows.Scan(&project.ID, &project.RootPath, &project.RoutePath, &project.Name,
			&project.Active, &project.UpdatedAt, &project.ItemCount, &project.SessionCount,
			&project.OpenCount, &project.PlannedCount); err != nil {
			return nil, fmt.Errorf("read project: %w", err)
		}
		projects = append(projects, project)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("read projects: %w", err)
	}
	return projects, nil
}

func (r *Repository) DataVersion(ctx context.Context) (int64, error) {
	var version int64
	if err := r.db.QueryRowContext(ctx, "PRAGMA data_version").Scan(&version); err != nil {
		return 0, fmt.Errorf("watch database: %w", err)
	}
	return version, nil
}

func (r *Repository) Health(ctx context.Context) error {
	var result string
	if err := r.db.QueryRowContext(ctx, "PRAGMA quick_check").Scan(&result); err != nil {
		return fmt.Errorf("check database integrity: %w", err)
	}
	if result != "ok" {
		return fmt.Errorf("database integrity check failed: %s", result)
	}
	rows, err := r.db.QueryContext(ctx, "PRAGMA foreign_key_check")
	if err != nil {
		return fmt.Errorf("check database relationships: %w", err)
	}
	if rows.Next() {
		rows.Close()
		return errors.New("database contains an invalid foreign-key relationship")
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return fmt.Errorf("check database relationships: %w", err)
	}
	if err := rows.Close(); err != nil {
		return fmt.Errorf("finish database relationship check: %w", err)
	}

	itemRows, err := r.db.QueryContext(ctx, `
		SELECT project_id, item_id, parent_id
		FROM items ORDER BY project_id, item_id`)
	if err != nil {
		return fmt.Errorf("check concept graph: %w", err)
	}
	parentsByProject := make(map[int64]map[string]string)
	for itemRows.Next() {
		var projectID int64
		var itemID string
		var parentID sql.NullString
		if err := itemRows.Scan(&projectID, &itemID, &parentID); err != nil {
			itemRows.Close()
			return fmt.Errorf("read concept graph: %w", err)
		}
		if parentsByProject[projectID] == nil {
			parentsByProject[projectID] = make(map[string]string)
		}
		parentsByProject[projectID][itemID] = parentID.String
	}
	if err := itemRows.Err(); err != nil {
		itemRows.Close()
		return fmt.Errorf("read concept graph: %w", err)
	}
	if err := itemRows.Close(); err != nil {
		return fmt.Errorf("finish concept graph check: %w", err)
	}
	for projectID, parents := range parentsByProject {
		for itemID, parentID := range parents {
			if parentID != "" {
				if _, exists := parents[parentID]; !exists {
					return fmt.Errorf("project %d concept %q has unknown parent %q", projectID, itemID, parentID)
				}
			}
		}
		for itemID := range parents {
			seen := make(map[string]bool)
			for current := itemID; current != ""; current = parents[current] {
				if seen[current] {
					return fmt.Errorf("project %d concept graph contains a cycle at %q", projectID, current)
				}
				seen[current] = true
			}
		}
	}
	return nil
}

func (r *Repository) LoadSnapshot(ctx context.Context, projectID int64) (Snapshot, error) {
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return Snapshot{}, fmt.Errorf("begin graph read: %w", err)
	}
	defer tx.Rollback()
	var snapshot Snapshot
	if err := tx.QueryRowContext(ctx, `
		SELECT id, root_path, route_path, name, active, updated_at
		FROM projects WHERE id = ?`, projectID).Scan(
		&snapshot.Project.ID, &snapshot.Project.RootPath, &snapshot.Project.RoutePath,
		&snapshot.Project.Name, &snapshot.Project.Active, &snapshot.Project.UpdatedAt,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return Snapshot{}, fmt.Errorf("mindmap project %d no longer exists", projectID)
		}
		return Snapshot{}, fmt.Errorf("read project: %w", err)
	}
	rows, err := tx.QueryContext(ctx, `
		SELECT item_id, parent_id, title, summary, resume, state, kind,
		       sort_order, created_at, updated_at, settled_at, revision
		FROM items WHERE project_id = ?
		ORDER BY sort_order, created_at, item_id`, projectID)
	if err != nil {
		return Snapshot{}, fmt.Errorf("read graph nodes: %w", err)
	}
	snapshot.Items = make([]Item, 0)
	for rows.Next() {
		var item Item
		var parent, settled sql.NullString
		if err := rows.Scan(&item.ID, &parent, &item.Title, &item.Summary, &item.Resume,
			&item.State, &item.Kind, &item.SortOrder, &item.CreatedAt,
			&item.UpdatedAt, &settled, &item.Revision); err != nil {
			rows.Close()
			return Snapshot{}, fmt.Errorf("read graph node: %w", err)
		}
		if parent.Valid {
			item.ParentID = parent.String
		}
		if settled.Valid {
			item.SettledAt = settled.String
		}
		snapshot.Items = append(snapshot.Items, item)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return Snapshot{}, fmt.Errorf("read graph nodes: %w", err)
	}
	if err := rows.Close(); err != nil {
		return Snapshot{}, fmt.Errorf("finish graph node read: %w", err)
	}
	snapshot.UserDeletedBranches, err = loadUserDeletedBranches(ctx, tx, projectID)
	if err != nil {
		return Snapshot{}, err
	}
	if err := tx.Commit(); err != nil {
		return Snapshot{}, fmt.Errorf("finish graph read: %w", err)
	}
	return snapshot, nil
}

func loadUserDeletedBranches(ctx context.Context, tx *sql.Tx, projectID int64) ([]DeletedBranch, error) {
	rows, err := tx.QueryContext(ctx, `
		SELECT id, event_type, item_id, payload_json FROM events
		WHERE project_id = ?
		  AND event_type IN ('item.subtree_deleted', 'item.restored', 'item.created')
		ORDER BY id`, projectID)
	if err != nil {
		return nil, fmt.Errorf("read user-deleted branches: %w", err)
	}
	tombstones := make(map[string]string)
	for rows.Next() {
		var eventID int64
		var eventType, payloadJSON string
		var itemID sql.NullString
		if err := rows.Scan(&eventID, &eventType, &itemID, &payloadJSON); err != nil {
			rows.Close()
			return nil, fmt.Errorf("read user-deleted branch event: %w", err)
		}
		if eventType == "item.restored" || eventType == "item.created" {
			if !itemID.Valid || strings.TrimSpace(itemID.String) == "" {
				rows.Close()
				return nil, fmt.Errorf("read user-deleted branches: event %d (%s) has no concept id", eventID, eventType)
			}
			delete(tombstones, itemID.String)
			continue
		}
		var payload struct {
			Deleted      *[]string        `json:"deleted"`
			DeletedItems *[]DeletedBranch `json:"deleted_items"`
		}
		if err := json.Unmarshal([]byte(payloadJSON), &payload); err != nil {
			rows.Close()
			return nil, fmt.Errorf("read user-deleted branches: event %d has invalid item.subtree_deleted payload: %w", eventID, err)
		}
		if payload.Deleted == nil && payload.DeletedItems == nil {
			rows.Close()
			return nil, fmt.Errorf("read user-deleted branches: event %d has invalid item.subtree_deleted payload: deleted ids are missing", eventID)
		}
		titles := make(map[string]string)
		if payload.DeletedItems != nil {
			for _, item := range *payload.DeletedItems {
				if strings.TrimSpace(item.ID) == "" {
					rows.Close()
					return nil, fmt.Errorf("read user-deleted branches: event %d has invalid item.subtree_deleted payload: deleted item id is blank", eventID)
				}
				if _, duplicate := titles[item.ID]; duplicate {
					rows.Close()
					return nil, fmt.Errorf("read user-deleted branches: event %d has invalid item.subtree_deleted payload: duplicate id %q", eventID, item.ID)
				}
				title := item.Title
				if title == "" {
					title = item.ID
				}
				titles[item.ID] = title
			}
		}
		deleted := make([]string, 0)
		if payload.Deleted != nil {
			deleted = append(deleted, (*payload.Deleted)...)
		} else {
			for id := range titles {
				deleted = append(deleted, id)
			}
			sort.Strings(deleted)
		}
		if len(deleted) == 0 {
			rows.Close()
			return nil, fmt.Errorf("read user-deleted branches: event %d has invalid item.subtree_deleted payload: deleted ids are empty", eventID)
		}
		seen := make(map[string]bool, len(deleted))
		for _, id := range deleted {
			if strings.TrimSpace(id) == "" || seen[id] {
				rows.Close()
				return nil, fmt.Errorf("read user-deleted branches: event %d has invalid item.subtree_deleted payload: blank or duplicate deleted id", eventID)
			}
			seen[id] = true
			if payload.DeletedItems != nil {
				if _, exists := titles[id]; !exists {
					rows.Close()
					return nil, fmt.Errorf("read user-deleted branches: event %d has invalid item.subtree_deleted payload: title missing for %q", eventID, id)
				}
			}
			title := titles[id]
			if title == "" {
				title = id
			}
			tombstones[id] = title
		}
		if payload.DeletedItems != nil && len(titles) != len(seen) {
			rows.Close()
			return nil, fmt.Errorf("read user-deleted branches: event %d has invalid item.subtree_deleted payload: id/title sets differ", eventID)
		}
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, fmt.Errorf("read user-deleted branches: %w", err)
	}
	if err := rows.Close(); err != nil {
		return nil, fmt.Errorf("finish user-deleted branch read: %w", err)
	}
	ids := make([]string, 0, len(tombstones))
	for id := range tombstones {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	branches := make([]DeletedBranch, 0, len(ids))
	for _, id := range ids {
		branches = append(branches, DeletedBranch{ID: id, Title: tombstones[id]})
	}
	return branches, nil
}

func (r *Repository) Activate(ctx context.Context, root string) (Project, error) {
	if r.readOnly {
		return Project{}, errors.New("database is read-only")
	}
	discovered, err := DiscoverProjectRoot(root)
	if err != nil {
		return Project{}, err
	}
	if runtime.GOOS == "windows" {
		var stored string
		err := r.db.QueryRowContext(ctx,
			"SELECT root_path FROM projects WHERE root_path = ? COLLATE NOCASE", discovered).Scan(&stored)
		if err == nil {
			discovered = stored
		} else if !errors.Is(err, sql.ErrNoRows) {
			return Project{}, fmt.Errorf("match existing Windows project: %w", err)
		}
	}
	route, err := RouteForRoot(discovered)
	if err != nil {
		return Project{}, err
	}
	now := time.Now().UTC().Format("2006-01-02T15:04:05.000Z07:00")
	tx, err := r.writeDB.BeginTx(ctx, nil)
	if err != nil {
		return Project{}, fmt.Errorf("begin activation: %w", err)
	}
	defer tx.Rollback()
	var collision string
	err = tx.QueryRowContext(ctx,
		"SELECT root_path FROM projects WHERE route_path = ? COLLATE NOCASE AND root_path <> ?",
		route, discovered).Scan(&collision)
	if err == nil {
		return Project{}, fmt.Errorf("%s maps to %s, already owned by %s", discovered, route, collision)
	}
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return Project{}, fmt.Errorf("check project route: %w", err)
	}
	_, err = tx.ExecContext(ctx, `
		INSERT INTO projects
		  (root_path, route_path, name, active, concept_model_version,
		   created_at, updated_at, activated_at, deactivated_at)
		VALUES (?, ?, ?, 1, 2, ?, ?, ?, NULL)
		ON CONFLICT(root_path) DO UPDATE SET active = 1, updated_at = excluded.updated_at,
		  activated_at = excluded.activated_at, deactivated_at = NULL`,
		discovered, route, filepath.Base(discovered), now, now, now)
	if err != nil {
		return Project{}, fmt.Errorf("activate project: %w", err)
	}
	var project Project
	if err := tx.QueryRowContext(ctx, `SELECT id, root_path, route_path, name, active, updated_at
		FROM projects WHERE root_path = ?`, discovered).Scan(&project.ID, &project.RootPath,
		&project.RoutePath, &project.Name, &project.Active, &project.UpdatedAt); err != nil {
		return Project{}, fmt.Errorf("read activated project: %w", err)
	}
	payload, _ := json.Marshal(map[string]string{"root_path": discovered})
	if _, err := tx.ExecContext(ctx, `INSERT INTO events
		(project_id, event_type, payload_json, created_at) VALUES (?, 'project.activated', ?, ?)`,
		project.ID, string(payload), now); err != nil {
		return Project{}, fmt.Errorf("record activation: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return Project{}, fmt.Errorf("finish activation: %w", err)
	}
	return project, nil
}

func (r *Repository) Deactivate(ctx context.Context, root string) (Project, error) {
	if r.readOnly {
		return Project{}, errors.New("database is read-only")
	}
	project, err := r.ResolveProject(root, "")
	if err != nil || !project.Active {
		return Project{}, fmt.Errorf("no active Mindmap project contains %s", root)
	}
	now := time.Now().UTC().Format("2006-01-02T15:04:05.000Z07:00")
	tx, err := r.writeDB.BeginTx(ctx, nil)
	if err != nil {
		return Project{}, fmt.Errorf("begin deactivation: %w", err)
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `UPDATE projects SET active = 0, updated_at = ?, deactivated_at = ? WHERE id = ?`, now, now, project.ID); err != nil {
		return Project{}, fmt.Errorf("deactivate project: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO events
		(project_id, event_type, payload_json, created_at) VALUES (?, 'project.deactivated', '{}', ?)`, project.ID, now); err != nil {
		return Project{}, fmt.Errorf("record deactivation: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return Project{}, fmt.Errorf("finish deactivation: %w", err)
	}
	project.Active = false
	project.UpdatedAt = now
	return project, nil
}

func ConfirmSubtree(items []Item, itemID string) ([]ItemRevision, error) {
	byID := make(map[string]Item, len(items))
	children := make(map[string][]string)
	for _, item := range items {
		byID[item.ID] = item
		children[item.ParentID] = append(children[item.ParentID], item.ID)
	}
	if _, exists := byID[itemID]; !exists {
		return nil, fmt.Errorf("concept %q does not exist", itemID)
	}
	confirmed := make([]ItemRevision, 0)
	seen := make(map[string]bool)
	var visit func(string) error
	visit = func(id string) error {
		if seen[id] {
			return fmt.Errorf("concept graph contains a cycle at %q", id)
		}
		seen[id] = true
		item := byID[id]
		confirmed = append(confirmed, ItemRevision{ID: id, Revision: item.Revision})
		for _, child := range children[id] {
			if err := visit(child); err != nil {
				return err
			}
		}
		return nil
	}
	if err := visit(itemID); err != nil {
		return nil, err
	}
	sort.Slice(confirmed, func(i, j int) bool { return confirmed[i].ID < confirmed[j].ID })
	return confirmed, nil
}

func (r *Repository) DeleteSubtree(ctx context.Context, projectID int64, itemID string, confirmed []ItemRevision) (DeleteResult, error) {
	if r.readOnly {
		return DeleteResult{}, errors.New("database is read-only")
	}
	itemID = strings.TrimSpace(itemID)
	if itemID == "" {
		return DeleteResult{}, errors.New("concept id is required")
	}
	tx, err := r.writeDB.BeginTx(ctx, nil)
	if err != nil {
		return DeleteResult{}, fmt.Errorf("begin subtree deletion: %w", err)
	}
	defer tx.Rollback()
	rows, err := tx.QueryContext(ctx, `WITH RECURSIVE subtree(item_id) AS (
		SELECT item_id FROM items WHERE project_id = ? AND item_id = ?
		UNION
		SELECT child.item_id FROM items child
		JOIN subtree ON child.parent_id = subtree.item_id WHERE child.project_id = ?
	) SELECT item.item_id, item.revision, item.parent_id, item.title
	  FROM items item JOIN subtree ON subtree.item_id = item.item_id
	  WHERE item.project_id = ? ORDER BY item.item_id`, projectID, itemID, projectID, projectID)
	if err != nil {
		return DeleteResult{}, fmt.Errorf("find concept subtree: %w", err)
	}
	deleted := make([]string, 0)
	actual := make(map[string]int)
	children := make(map[string][]string)
	titles := make(map[string]string)
	for rows.Next() {
		var id, title string
		var revision int
		var parentID sql.NullString
		if err := rows.Scan(&id, &revision, &parentID, &title); err != nil {
			rows.Close()
			return DeleteResult{}, fmt.Errorf("read concept subtree: %w", err)
		}
		actual[id] = revision
		titles[id] = title
		children[parentID.String] = append(children[parentID.String], id)
	}
	if err := rows.Close(); err != nil {
		return DeleteResult{}, fmt.Errorf("finish concept subtree read: %w", err)
	}
	if len(actual) == 0 {
		return DeleteResult{}, fmt.Errorf("concept %q does not exist in project %d", itemID, projectID)
	}
	// Build a deterministic child-before-parent result after the cycle-safe
	// reachability query. The visited set also keeps a corrupted cycle from
	// trapping deletion in recursive SQL.
	visited := make(map[string]bool, len(actual))
	var visit func(string)
	visit = func(id string) {
		if visited[id] {
			return
		}
		visited[id] = true
		sort.Strings(children[id])
		for _, childID := range children[id] {
			visit(childID)
		}
		deleted = append(deleted, id)
	}
	visit(itemID)
	if len(confirmed) != len(actual) {
		return DeleteResult{}, ErrSubtreeChanged
	}
	seen := make(map[string]bool, len(confirmed))
	for _, item := range confirmed {
		revision, exists := actual[item.ID]
		if seen[item.ID] || !exists || revision != item.Revision {
			return DeleteResult{}, ErrSubtreeChanged
		}
		seen[item.ID] = true
	}
	now := time.Now().UTC().Format("2006-01-02T15:04:05.000Z07:00")
	deletedItems := make([]map[string]string, 0, len(deleted))
	for _, id := range deleted {
		deletedItems = append(deletedItems, map[string]string{"id": id, "title": titles[id]})
	}
	payload, _ := json.Marshal(map[string]any{
		"root_id": itemID, "deleted": deleted, "deleted_items": deletedItems, "source": "user",
	})
	if _, err := tx.ExecContext(ctx, `INSERT INTO events
		(project_id, event_type, item_id, payload_json, created_at)
		VALUES (?, 'item.subtree_deleted', ?, ?, ?)`, projectID, itemID, string(payload), now); err != nil {
		return DeleteResult{}, fmt.Errorf("record subtree deletion: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `WITH RECURSIVE subtree(item_id) AS (
		SELECT item_id FROM items WHERE project_id = ? AND item_id = ?
		UNION
		SELECT child.item_id FROM items child JOIN subtree ON child.parent_id = subtree.item_id
		WHERE child.project_id = ?
	) DELETE FROM items WHERE project_id = ? AND item_id IN (SELECT item_id FROM subtree)`,
		projectID, itemID, projectID, projectID); err != nil {
		return DeleteResult{}, fmt.Errorf("delete concept subtree: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `UPDATE projects SET updated_at = ? WHERE id = ?`, now, projectID); err != nil {
		return DeleteResult{}, fmt.Errorf("update project after deletion: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return DeleteResult{}, fmt.Errorf("finish subtree deletion: %w", err)
	}
	return DeleteResult{ProjectID: projectID, Deleted: deleted}, nil
}

func SnapshotEqual(left, right Snapshot) bool {
	if left.Project != right.Project || len(left.Items) != len(right.Items) ||
		len(left.UserDeletedBranches) != len(right.UserDeletedBranches) {
		return false
	}
	for index := range left.Items {
		if left.Items[index] != right.Items[index] {
			return false
		}
	}
	for index := range left.UserDeletedBranches {
		if left.UserDeletedBranches[index] != right.UserDeletedBranches[index] {
			return false
		}
	}
	return true
}

func CanonicalPath(value string) (string, error) {
	abs, err := filepath.Abs(expandHome(value))
	if err != nil {
		return "", fmt.Errorf("resolve project path: %w", err)
	}
	if resolved, err := filepath.EvalSymlinks(abs); err == nil {
		abs = resolved
	}
	return filepath.Clean(abs), nil
}

func DiscoverProjectRoot(value string) (string, error) {
	if value == "" {
		var err error
		value, err = os.Getwd()
		if err != nil {
			return "", fmt.Errorf("find current directory: %w", err)
		}
	}
	path, err := CanonicalPath(value)
	if err != nil {
		return "", err
	}
	info, err := os.Stat(path)
	if err != nil {
		return "", fmt.Errorf("inspect project path: %w", err)
	}
	if !info.IsDir() {
		path = filepath.Dir(path)
	}
	for current := path; ; current = filepath.Dir(current) {
		if info, err := os.Stat(filepath.Join(current, ".git")); err == nil && (info.IsDir() || info.Mode().IsRegular()) {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			break
		}
	}
	return path, nil
}

func RouteForRoot(root string) (string, error) {
	home, err := homeDirectory()
	if err != nil {
		return "", fmt.Errorf("find home directory: %w", err)
	}
	relative, err := filepath.Rel(home, root)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("project root %s must be within the home directory", root)
	}
	if relative == "." {
		return "", errors.New("the home directory itself cannot be a Mindmap project root")
	}
	parts := strings.Split(filepath.ToSlash(relative), "/")
	for index := range parts {
		// Match Python's Unicode-aware str.lower() so both writers derive the
		// same stable route for non-ASCII project names (for example U+0130).
		parts[index] = quoteRoutePart(cases.Lower(language.Und).String(parts[index]))
	}
	return "/" + strings.Join(parts, "/"), nil
}

func quoteRoutePart(value string) string {
	const hex = "0123456789ABCDEF"
	var encoded strings.Builder
	for _, b := range []byte(value) {
		if b >= 'a' && b <= 'z' || b >= 'A' && b <= 'Z' || b >= '0' && b <= '9' || b == '-' || b == '.' || b == '_' || b == '~' {
			encoded.WriteByte(b)
			continue
		}
		encoded.WriteByte('%')
		encoded.WriteByte(hex[b>>4])
		encoded.WriteByte(hex[b&0x0f])
	}
	return encoded.String()
}

func homeDirectory() (string, error) {
	if override := os.Getenv("MINDMAP_HOME_DIR"); override != "" {
		return CanonicalPath(override)
	}
	return os.UserHomeDir()
}

func PathWithin(candidate, root string) bool {
	return pathWithin(candidate, root, runtime.GOOS)
}

func pathWithin(candidate, root, goos string) bool {
	if goos == "windows" {
		candidate = strings.ReplaceAll(candidate, `\`, "/")
		root = strings.ReplaceAll(root, `\`, "/")
	}
	candidate = filepath.Clean(candidate)
	root = filepath.Clean(root)
	if goos == "windows" {
		candidate = strings.ToLower(candidate)
		root = strings.ToLower(root)
	}
	relative, err := filepath.Rel(root, candidate)
	return err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}
