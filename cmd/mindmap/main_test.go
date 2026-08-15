package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/erd0s/mindmap/internal/store"
)

func TestNullDeviceIsNotInteractive(t *testing.T) {
	file, err := os.Open(os.DevNull)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if isTerminal(file) {
		t.Fatal("the null device must not satisfy destructive confirmation")
	}
}

func TestItemTitleFindsRequestedConcept(t *testing.T) {
	title := itemTitle([]store.Item{
		{ID: "root", Title: "Root"},
		{ID: "child", ParentID: "root"},
	}, "root")
	if title != "Root" {
		t.Fatalf("title = %q", title)
	}
}

func TestDeleteRejectsRootAndRouteBeforeOpeningDatabase(t *testing.T) {
	database := filepath.Join(t.TempDir(), "must-not-exist.sqlite3")
	err := deleteBranch([]string{
		"--database", database,
		"--root", "/one",
		"--route", "/two",
		"node",
	})
	if err == nil || !strings.Contains(err.Error(), "cannot be used together") {
		t.Fatalf("delete error = %v", err)
	}
	if _, statErr := os.Stat(database); !os.IsNotExist(statErr) {
		t.Fatalf("selector validation touched database: %v", statErr)
	}
}

func TestResolveDesktopProjectRootRejectsUnknownProjectSynchronously(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "data"))
	known := filepath.Join(home, "known")
	unknown := filepath.Join(home, "unknown")
	for _, path := range []string{known, unknown} {
		if err := os.MkdirAll(path, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.Mkdir(filepath.Join(path, ".git"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	repository, err := store.OpenDefault(false)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := repository.Activate(t.Context(), known); err != nil {
		repository.Close()
		t.Fatal(err)
	}
	if err := repository.Close(); err != nil {
		t.Fatal(err)
	}

	child := filepath.Join(known, "nested")
	if err := os.Mkdir(child, 0o755); err != nil {
		t.Fatal(err)
	}
	resolved, err := resolveDesktopProjectRoot(child)
	if err != nil {
		t.Fatal(err)
	}
	if resolved != known {
		t.Fatalf("desktop project root = %q, want %q", resolved, known)
	}
	if _, err := resolveDesktopProjectRoot(unknown); err == nil || !strings.Contains(err.Error(), "no Mindmap project") {
		t.Fatalf("unknown project error = %v", err)
	}
}
