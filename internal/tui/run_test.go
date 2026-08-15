package tui

import (
	"bytes"
	"strings"
	"testing"
	"unicode/utf8"
)

func TestLimitedTerminalRunPrintsStaticSnapshotWithoutControls(t *testing.T) {
	for _, term := range []string{"", "dumb", "vt100", "vt100-am", "vt220"} {
		t.Run(term, func(t *testing.T) {
			path, writer := createTestDatabase(t)
			defer writer.Close()
			t.Setenv("TERM", term)
			t.Setenv("MINDMAP_ASCII", "auto")
			var output bytes.Buffer
			if err := Run(RunOptions{Database: path, Root: "/home/test/deep/subdir", Output: &output}); err != nil {
				t.Fatal(err)
			}
			value := output.String()
			if strings.ContainsRune(value, '\x1b') {
				t.Fatal("static output contains an escape byte")
			}
			if !strings.Contains(value, "Limited terminal: printed a static snapshot") {
				t.Fatalf("static fallback note missing from %q", value)
			}
			for len(value) > 0 {
				character, size := utf8.DecodeRuneInString(value)
				if character > 0x7e && character != '\n' {
					t.Fatalf("static output contains non-ASCII rune %q", character)
				}
				value = value[size:]
			}
		})
	}
}

func TestStaticSnapshotUsesDeterministicDepthFirstPreorder(t *testing.T) {
	snapshot := testSnapshot(
		Item{ID: "root-a", Title: "Root A", State: "open", SortOrder: 0},
		Item{ID: "root-b", Title: "Root B", State: "open", SortOrder: 1},
		Item{ID: "child-a", ParentID: "root-a", Title: "Child A", State: "open", SortOrder: 0},
		Item{ID: "grand-a", ParentID: "child-a", Title: "Grand A", State: "planned", SortOrder: 0},
		Item{ID: "child-b", ParentID: "root-b", Title: "Child B", State: "settled", SortOrder: 0},
	)
	got := renderStaticSnapshot(snapshot)
	want := "mindmap / project\n/home/test/project\n5 concepts, 1 frontier\n" +
		"- [open] Root A (root-a)\n" +
		"  - [open] Child A (child-a)\n" +
		"    - [planned] Grand A (grand-a)\n" +
		"- [open] Root B (root-b)\n" +
		"  - [settled] Child B (child-b)\n" +
		"\nLimited terminal: printed a static snapshot; use a capable terminal for the live viewer."
	if got != want {
		t.Fatalf("static snapshot mismatch\n--- got ---\n%s\n--- want ---\n%s", got, want)
	}
}

func TestStaticSnapshotRendersOrphansAndCyclesOnce(t *testing.T) {
	snapshot := testSnapshot(
		Item{ID: "orphan", ParentID: "missing", Title: "Orphan", State: "open"},
		Item{ID: "cycle-a", ParentID: "cycle-b", Title: "Cycle A", State: "open"},
		Item{ID: "cycle-b", ParentID: "cycle-a", Title: "Cycle B", State: "open"},
	)
	value := renderStaticSnapshot(snapshot)
	for _, id := range []string{"orphan", "cycle-a", "cycle-b"} {
		if count := strings.Count(value, "("+id+")"); count != 1 {
			t.Fatalf("%s rendered %d times in %q", id, count, value)
		}
	}
}
