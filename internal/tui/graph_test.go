package tui

import (
	"strings"
	"testing"
)

func graphItem(id, parent, state string) Item {
	return Item{
		ID: id, ParentID: parent, Title: id, State: state, Kind: "task",
		CreatedAt: "2026-01-01T00:00:00Z", UpdatedAt: "2026-01-01T00:00:00Z",
		Revision: 1,
	}
}

func TestGraphSelectsRootAndNavigatesParent(t *testing.T) {
	graph := NewGraph([]Item{
		graphItem("root", "", "open"),
		graphItem("child", "root", "planned"),
	})
	if graph.Root() != "root" {
		t.Fatalf("root = %q", graph.Root())
	}
	if graph.Deeper("root") != "child" {
		t.Fatalf("right from root = %q", graph.Deeper("root"))
	}
	if graph.Parent("child") != "root" {
		t.Fatalf("left from child = %q", graph.Parent("child"))
	}
	if graph.Parent("root") != "root" {
		t.Fatalf("left from root should do nothing")
	}
}

func TestDeeperPrefersStateBeforeBranchDepth(t *testing.T) {
	graph := NewGraph([]Item{
		graphItem("root", "", "open"),
		graphItem("settled", "root", "settled"),
		graphItem("planned", "root", "planned"),
		graphItem("planned-child", "planned", "open"),
		graphItem("open", "root", "open"),
	})
	if got := graph.Deeper("root"); got != "open" {
		t.Fatalf("right should prefer open state, got %q", got)
	}
}

func TestDeeperBreaksStateTieWithActiveBranchDepth(t *testing.T) {
	graph := NewGraph([]Item{
		graphItem("root", "", "open"),
		graphItem("shallow", "root", "open"),
		graphItem("deep", "root", "open"),
		graphItem("deep-child", "deep", "planned"),
		graphItem("deep-leaf", "deep-child", "open"),
	})
	if got := graph.Deeper("root"); got != "deep" {
		t.Fatalf("right should prefer the deeper active branch, got %q", got)
	}
}

func TestVerticalNavigationUsesGlobalDepthOrderAndStopsAtEdges(t *testing.T) {
	graph := NewGraph([]Item{
		graphItem("root", "", "open"),
		graphItem("a", "root", "open"),
		graphItem("a1", "a", "open"),
		graphItem("a2", "a", "open"),
		graphItem("b", "root", "open"),
		graphItem("b1", "b", "open"),
		graphItem("b2", "b", "open"),
	})
	if got := graph.Vertical("b1", -1); got != "a2" {
		t.Fatalf("up should cross lineages at the same depth, got %q", got)
	}
	if got := graph.Vertical("a1", -1); got != "a1" {
		t.Fatalf("up at top should do nothing, got %q", got)
	}
	if got := graph.Vertical("b2", 1); got != "b2" {
		t.Fatalf("down at bottom should do nothing, got %q", got)
	}
}

func TestCanvasDrawsConnectorsAndSelection(t *testing.T) {
	graph := NewGraph([]Item{
		graphItem("root", "", "open"),
		graphItem("child", "root", "planned"),
	})
	canvas := BuildCanvas(graph, "root")
	if len(canvas.lines) == 0 {
		t.Fatal("expected connector cells")
	}
	rendered := canvas.Render(NewTheme(), 0, 0, 80, 8)
	if !strings.Contains(rendered, "root") || !strings.Contains(rendered, "child") {
		t.Fatalf("rendered graph is missing nodes: %q", rendered)
	}
	for _, border := range []string{"╭", "│", "╰"} {
		if !strings.Contains(rendered, border) {
			t.Fatalf("rendered graph is missing selection box %q: %q", border, rendered)
		}
	}
}
