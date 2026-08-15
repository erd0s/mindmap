package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
)

type RunOptions struct {
	Database string
	Root     string
	Route    string
	Output   io.Writer
}

func Run(options RunOptions) error {
	repository, err := OpenRepository(options.Database)
	if err != nil {
		return err
	}
	defer repository.Close()
	project, err := repository.ResolveProject(options.Root, options.Route)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	snapshot, err := repository.LoadSnapshot(ctx, project.ID)
	if err != nil {
		return err
	}
	if limitedTerminal() {
		output := options.Output
		if output == nil {
			output = os.Stdout
		}
		_, err := fmt.Fprintln(output, renderStaticSnapshot(snapshot))
		return err
	}
	dataVersion, err := repository.DataVersion(ctx)
	if err != nil {
		return err
	}
	program := tea.NewProgram(NewModel(repository, snapshot, dataVersion))
	if _, err := program.Run(); err != nil && !errors.Is(err, tea.ErrInterrupted) {
		return err
	}
	return nil
}

func limitedTerminal() bool {
	term := strings.ToLower(strings.TrimSpace(os.Getenv("TERM")))
	return term == "" || term == "dumb" || strings.HasPrefix(term, "vt100") || strings.HasPrefix(term, "vt220")
}

func renderStaticSnapshot(snapshot Snapshot) string {
	children := make(map[string][]Item)
	byID := make(map[string]Item, len(snapshot.Items))
	for _, item := range snapshot.Items {
		byID[item.ID] = item
		if item.ParentID != "" {
			children[item.ParentID] = append(children[item.ParentID], item)
		}
	}
	less := func(left, right Item) bool {
		if left.SortOrder != right.SortOrder {
			return left.SortOrder < right.SortOrder
		}
		if left.CreatedAt != right.CreatedAt {
			return left.CreatedAt < right.CreatedAt
		}
		return left.ID < right.ID
	}
	items := append([]Item(nil), snapshot.Items...)
	sort.Slice(items, func(i, j int) bool { return less(items[i], items[j]) })
	for parentID := range children {
		sort.Slice(children[parentID], func(i, j int) bool {
			return less(children[parentID][i], children[parentID][j])
		})
	}
	roots := make([]Item, 0)
	for _, item := range items {
		if item.ParentID == "" {
			roots = append(roots, item)
			continue
		}
		if _, exists := byID[item.ParentID]; !exists {
			// A corrupt orphan is still rendered as a top-level fallback so a
			// diagnostic snapshot never silently hides stored concepts.
			roots = append(roots, item)
		}
	}
	frontier := 0
	for _, item := range items {
		if item.State != "settled" && len(children[item.ID]) == 0 {
			frontier++
		}
	}
	var output strings.Builder
	fmt.Fprintf(&output, "mindmap / %s\n%s\n%d concepts, %d frontier\n",
		sanitizeASCII(snapshot.Project.Name), sanitizeASCII(snapshot.Project.RootPath), len(items), frontier)
	visited := make(map[string]bool, len(items))
	var visit func(Item, int)
	visit = func(item Item, depth int) {
		if visited[item.ID] {
			return
		}
		visited[item.ID] = true
		fmt.Fprintf(&output, "%s- [%s] %s (%s)\n", strings.Repeat("  ", depth),
			sanitizeASCII(item.State), sanitizeASCII(item.Title), sanitizeASCII(item.ID))
		for _, child := range children[item.ID] {
			visit(child, depth+1)
		}
	}
	for _, item := range roots {
		visit(item, 0)
	}
	// Cyclic components have no root. Render each unvisited component once
	// instead of recursing forever or omitting it from the static fallback.
	for _, item := range items {
		visit(item, 0)
	}
	output.WriteString("\nLimited terminal: printed a static snapshot; use a capable terminal for the live viewer.")
	return output.String()
}

func sanitizeASCII(value string) string {
	var output strings.Builder
	for _, character := range value {
		switch {
		case character == '\n' || character == '\r' || character == '\t':
			output.WriteByte(' ')
		case character < 0x20 || character > 0x7e:
			output.WriteByte('?')
		default:
			output.WriteRune(character)
		}
	}
	return output.String()
}
