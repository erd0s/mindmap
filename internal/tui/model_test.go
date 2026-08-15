package tui

import (
	"context"
	"errors"
	"strings"
	"testing"
	"unicode/utf8"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

func testSnapshot(items ...Item) Snapshot {
	return Snapshot{
		Project: Project{
			ID: 1, RootPath: "/home/test/project", RoutePath: "/project",
			Name: "project", Active: true, UpdatedAt: "2026-01-01T00:00:00Z",
		},
		Items: items,
	}
}

func TestModelStartsOnRootAndArrowKeysNavigate(t *testing.T) {
	model := NewModel(nil, testSnapshot(
		graphItem("root", "", "open"),
		graphItem("child", "root", "planned"),
	), 1)
	if model.selected != "root" {
		t.Fatalf("initial selection = %q", model.selected)
	}
	model.handleKey(tea.Key{Code: tea.KeyRight})
	if model.selected != "child" {
		t.Fatalf("right selection = %q", model.selected)
	}
	model.handleKey(tea.Key{Code: tea.KeyLeft})
	if model.selected != "root" {
		t.Fatalf("left selection = %q", model.selected)
	}
}

func TestPanModeUsesExplicitPortableSteps(t *testing.T) {
	model := NewModel(nil, testSnapshot(graphItem("root", "", "open")), 1)
	model.handleKey(tea.Key{Code: 'p', Text: "p"})
	if !model.panMode || model.panStep != 1 {
		t.Fatalf("pan mode = %v step = %d", model.panMode, model.panStep)
	}
	model.handleKey(tea.Key{Code: '2', Text: "2"})
	model.handleKey(tea.Key{Code: tea.KeyRight})
	model.handleKey(tea.Key{Code: tea.KeyDown})
	if model.panX != 10 || model.panY != 10 {
		t.Fatalf("pan = %d,%d", model.panX, model.panY)
	}
	model.handleKey(tea.Key{Code: '3', Text: "3"})
	model.handleKey(tea.Key{Code: tea.KeyLeft})
	if model.panX != -20 {
		t.Fatalf("30-character pan = %d", model.panX)
	}
	model.handleKey(tea.Key{Code: 'p', Text: "p"})
	if model.panMode {
		t.Fatal("p should leave pan mode")
	}
}

func TestLiveSnapshotPreservesSelectionAndFallsBackToRoot(t *testing.T) {
	initial := testSnapshot(
		graphItem("root", "", "open"),
		graphItem("child", "root", "open"),
	)
	model := NewModel(nil, initial, 1)
	model.selected = "child"
	updated := testSnapshot(
		graphItem("root", "", "open"),
		graphItem("child", "root", "settled"),
		graphItem("new", "root", "planned"),
	)
	model.Update(pollResult{Version: 2, Snapshot: &updated})
	if model.selected != "child" {
		t.Fatalf("selection was not preserved: %q", model.selected)
	}
	removed := testSnapshot(graphItem("root", "", "open"))
	model.Update(pollResult{Version: 3, Snapshot: &removed})
	if model.selected != "root" {
		t.Fatalf("deleted selection did not fall back to root: %q", model.selected)
	}
}

func TestFailedLiveReloadDoesNotAdvanceDataVersion(t *testing.T) {
	model := NewModel(nil, testSnapshot(graphItem("root", "", "open")), 7)
	model.Update(pollResult{Version: 8, Err: errors.New("temporary read failure")})
	if model.dataVersion != 7 {
		t.Fatalf("data version advanced to %d after a failed reload", model.dataVersion)
	}
}

func TestRefreshFailureForcesReloadWhenDataVersionIsUnchanged(t *testing.T) {
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
	snapshot, err := repository.LoadSnapshot(context.Background(), project.ID)
	if err != nil {
		t.Fatal(err)
	}
	version, err := repository.DataVersion(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	model := NewModel(repository, snapshot, version)
	model.Update(deleteResult{Deleted: []string{"child"}, RefreshErr: errors.New("temporary read failure")})
	if !model.reloadPending {
		t.Fatal("a post-delete refresh failure must leave a forced reload pending")
	}
	message, ok := model.pollCommand()().(pollResult)
	if !ok {
		t.Fatal("poll command returned an unexpected message")
	}
	if message.Err != nil {
		t.Fatal(message.Err)
	}
	if message.Snapshot == nil {
		t.Fatal("forced reload skipped the snapshot when data_version was unchanged")
	}
	model.Update(message)
	if model.reloadPending {
		t.Fatal("successful forced reload did not clear the pending state")
	}
}

func TestPollStartedBeforeDeleteCannotRestoreStaleSnapshot(t *testing.T) {
	oldSnapshot := testSnapshot(
		graphItem("root", "", "open"),
		graphItem("child", "root", "open"),
	)
	newSnapshot := testSnapshot(graphItem("root", "", "open"))
	model := NewModel(nil, oldSnapshot, 4)
	model.Update(deleteResult{Deleted: []string{"child"}, Snapshot: &newSnapshot, Version: 4})
	if model.pollGeneration != 1 {
		t.Fatalf("poll generation = %d", model.pollGeneration)
	}
	model.Update(pollResult{Generation: 0, Version: 4, Snapshot: &oldSnapshot})
	if len(model.snapshot.Items) != 1 || model.snapshot.Items[0].ID != "root" {
		t.Fatalf("stale poll restored deleted items: %#v", model.snapshot.Items)
	}
}

func TestInformationPanelMirrorsNodeFields(t *testing.T) {
	item := graphItem("root", "", "open")
	item.Title = "Build the terminal graph"
	item.Summary = "Shows the causal map."
	item.Resume = "Continue from the selected node."
	model := NewModel(nil, testSnapshot(item), 1)
	model.width, model.height = 100, 30
	model.handleKey(tea.Key{Code: 'i', Text: "i"})
	if !model.details {
		t.Fatal("i should open node information")
	}
	panel := model.renderDetails()
	if lipgloss.Height(panel) > model.height-2 {
		t.Fatalf("details panel is too tall: %d", lipgloss.Height(panel))
	}
	for _, expected := range []string{"Build the terminal graph", "Shows the causal map", "Continue from the selected node", "revision 1"} {
		if !stringsContainANSI(panel, expected) {
			t.Fatalf("details panel missing %q", expected)
		}
	}
	model.details = true
	rendered := model.render()
	if !stringsContainANSI(strings.SplitN(rendered, "\n", 2)[0], "mindmap") {
		t.Fatal("details panel should overlay the graph without replacing the header")
	}
}

func TestInformationPanelScrollsWithoutChangingSelection(t *testing.T) {
	root := graphItem("root", "", "open")
	root.Title = "A selected root with a complete information panel"
	root.Summary = strings.Repeat("full wrapped information ", 30) + "TAILMARKER"
	child := graphItem("child", "root", "planned")
	child.Title = "A child title that should remain intact when it wraps across several overlay lines"
	model := NewModel(nil, testSnapshot(root, child), 1)
	model.width, model.height = 58, 14
	model.handleKey(tea.Key{Code: 'i', Text: "i"})

	if stringsContainANSI(model.renderDetails(), "TAILMARKER") {
		t.Fatal("tail should begin below the information viewport")
	}
	foundTail := false
	for range 100 {
		model.handleKey(tea.Key{Code: tea.KeyDown})
		foundTail = foundTail || stringsContainANSI(model.renderDetails(), "TAILMARKER")
	}
	if model.selected != "root" {
		t.Fatalf("overlay arrow key changed graph selection to %q", model.selected)
	}
	if model.detailScroll != model.maxDetailScroll() || model.detailScroll == 0 {
		t.Fatalf("detail scroll = %d, max = %d", model.detailScroll, model.maxDetailScroll())
	}
	if !foundTail {
		t.Fatal("scrolling did not reveal complete wrapped information")
	}
	model.handleKey(tea.Key{Code: tea.KeyUp})
	if model.detailScroll != model.maxDetailScroll()-1 {
		t.Fatal("up should scroll the information viewport by one line")
	}
	model.handleKey(tea.Key{Code: tea.KeyRight})
	if model.selected != "root" {
		t.Fatal("left/right should not navigate while information is open")
	}
}

func TestInformationWrappingDoesNotEllipsizeLongTokens(t *testing.T) {
	value := strings.Repeat("abcdefghij", 10)
	lines := wrapText(value, 17)
	if strings.Contains(strings.Join(lines, ""), "…") {
		t.Fatal("wrapped information should not be ellipsized")
	}
	if strings.Join(lines, "") != value {
		t.Fatal("wrapped information did not preserve the complete token")
	}
}

func TestMouseWheelIsCapturedAndIgnored(t *testing.T) {
	model := NewModel(nil, testSnapshot(
		graphItem("root", "", "open"),
		graphItem("child", "root", "open"),
	), 1)
	view := model.View()
	if view.MouseMode != tea.MouseModeCellMotion {
		t.Fatalf("mouse mode = %v, want cell motion", view.MouseMode)
	}
	model.Update(tea.MouseWheelMsg(tea.Mouse{Button: tea.MouseWheelDown}))
	if model.selected != "root" || model.detailScroll != 0 {
		t.Fatal("mouse wheel should not navigate or scroll")
	}
}

func TestQuitKeysReturnQuitCommand(t *testing.T) {
	for _, key := range []tea.Key{
		{Code: 'q', Text: "q"},
		{Code: 'c', Mod: tea.ModCtrl},
	} {
		model := NewModel(nil, testSnapshot(graphItem("root", "", "open")), 1)
		_, command := model.handleKey(key)
		if command == nil {
			t.Fatalf("%s did not request quit", key.Keystroke())
		}
	}
}

func TestCommonTerminalProfilesRenderAtExactDimensions(t *testing.T) {
	for _, term := range []string{"xterm-256color", "screen-256color", "tmux-256color", "vt100", "dumb"} {
		t.Run(term, func(t *testing.T) {
			t.Setenv("TERM", term)
			t.Setenv("MINDMAP_ASCII", "auto")
			model := NewModel(nil, testSnapshot(
				graphItem("root", "", "open"),
				graphItem("child", "root", "planned"),
			), 1)
			model.width, model.height = 92, 24
			model.help = true
			rendered := model.render()
			lines := strings.Split(rendered, "\n")
			if len(lines) != model.height {
				t.Fatalf("rendered height = %d, want %d", len(lines), model.height)
			}
			for index, line := range lines {
				if width := lipgloss.Width(line); width > model.width {
					t.Fatalf("line %d width = %d, exceeds %d", index, width, model.width)
				}
			}
		})
	}
}

func TestDumbTerminalIsASCIIAndRejectsControlSequences(t *testing.T) {
	t.Setenv("TERM", "dumb")
	t.Setenv("MINDMAP_ASCII", "auto")
	item := graphItem("root", "", "open")
	item.Title = "unsafe\x1b]52;c;payload\a café"
	item.Summary = "line one\nline two\x1b[31m"
	model := NewModel(nil, testSnapshot(item), 1)
	model.snapshot.Project.Name = "project\x1b[2J"
	model.width, model.height = 92, 24
	model.help = true
	rendered := model.render()
	if strings.ContainsRune(rendered, '\x1b') {
		t.Fatal("dumb-terminal output contains an escape byte")
	}
	for len(rendered) > 0 {
		character, size := utf8.DecodeRuneInString(rendered)
		if character > 0x7e && character != '\n' {
			t.Fatalf("dumb-terminal output contains non-ASCII rune %q", character)
		}
		rendered = rendered[size:]
	}
}

func TestAutomaticASCIIHonoursLocaleAndLegacyTerminal(t *testing.T) {
	t.Setenv("MINDMAP_ASCII", "auto")
	t.Setenv("TERM", "xterm-256color")
	t.Setenv("LC_ALL", "C")
	if !asciiMode() {
		t.Fatal("the C locale must use ASCII")
	}
	t.Setenv("LC_ALL", "en_GB.UTF-8")
	if asciiMode() {
		t.Fatal("a UTF-8 xterm should use Unicode")
	}
	t.Setenv("TERM", "vt100")
	if !asciiMode() {
		t.Fatal("vt100 must use ASCII")
	}
}

func stringsContainANSI(value, expected string) bool {
	// ANSI control bytes do not split the plain field contents we assert here.
	return strings.Contains(value, expected)
}
