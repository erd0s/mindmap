package tui

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

const pollInterval = 200 * time.Millisecond

type pollResult struct {
	Generation int64
	Version    int64
	Snapshot   *Snapshot
	Err        error
}

type deleteResult struct {
	Deleted    []string
	Snapshot   *Snapshot
	Version    int64
	Err        error
	RefreshErr error
}

type Model struct {
	repository      *Repository
	snapshot        Snapshot
	graph           *Graph
	selected        string
	dataVersion     int64
	pollGeneration  int64
	reloadPending   bool
	width           int
	height          int
	panX            int
	panY            int
	panMode         bool
	panStep         int
	details         bool
	detailScroll    int
	help            bool
	confirmDelete   bool
	deleteConfirmed []ItemRevision
	status          string
	updatedTill     time.Time
	theme           Theme
}

func NewModel(repository *Repository, snapshot Snapshot, dataVersion int64) *Model {
	graph := NewGraph(snapshot.Items)
	return &Model{
		repository:  repository,
		snapshot:    snapshot,
		graph:       graph,
		selected:    graph.Root(),
		dataVersion: dataVersion,
		panStep:     1,
		theme:       NewTheme(),
	}
}

func (m *Model) Init() tea.Cmd {
	return m.pollCommand()
}

func (m *Model) pollCommand() tea.Cmd {
	repository := m.repository
	projectID := m.snapshot.Project.ID
	lastVersion := m.dataVersion
	generation := m.pollGeneration
	forceReload := m.reloadPending
	return func() tea.Msg {
		time.Sleep(pollInterval)
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		version, err := repository.DataVersion(ctx)
		if err != nil {
			return pollResult{Generation: generation, Version: lastVersion, Err: err}
		}
		if version == lastVersion && !forceReload {
			return pollResult{Generation: generation, Version: version}
		}
		snapshot, err := repository.LoadSnapshot(ctx, projectID)
		if err != nil {
			return pollResult{Generation: generation, Version: lastVersion, Err: err}
		}
		return pollResult{Generation: generation, Version: version, Snapshot: &snapshot}
	}
}

func (m *Model) Update(message tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := message.(type) {
	case tea.WindowSizeMsg:
		wasUnknown := m.width == 0 || m.height == 0
		m.width, m.height = msg.Width, msg.Height
		if wasUnknown {
			m.centerSelection()
		} else {
			m.ensureSelectionVisible()
		}
		m.clampDetailScroll()
	case pollResult:
		if msg.Generation != m.pollGeneration {
			// A delete completed while this poll was in flight. Its snapshot may
			// predate the deletion, so discard it without starting a second poll.
			return m, nil
		}
		if msg.Err != nil {
			m.status = msg.Err.Error()
			return m, m.pollCommand()
		}
		m.dataVersion = msg.Version
		m.status = ""
		if msg.Snapshot != nil {
			m.reloadPending = false
		}
		if msg.Snapshot != nil && !SnapshotEqual(m.snapshot, *msg.Snapshot) {
			if m.confirmDelete {
				m.confirmDelete = false
				m.deleteConfirmed = nil
				m.status = "graph changed; review the branch before deleting"
			}
			m.snapshot = *msg.Snapshot
			m.graph = NewGraph(m.snapshot.Items)
			if _, exists := m.graph.ByID[m.selected]; !exists {
				m.selected = m.graph.Root()
				m.detailScroll = 0
			}
			m.ensureSelectionVisible()
			m.clampDetailScroll()
			m.updatedTill = time.Now().Add(1600 * time.Millisecond)
		}
		return m, m.pollCommand()
	case deleteResult:
		m.confirmDelete = false
		m.deleteConfirmed = nil
		if msg.Err != nil {
			m.status = "delete failed: " + msg.Err.Error()
			return m, m.pollCommand()
		}
		m.pollGeneration++
		if msg.RefreshErr != nil {
			m.reloadPending = true
			m.status = fmt.Sprintf("deleted %d concept(s); refresh delayed: %s", len(msg.Deleted), msg.RefreshErr)
			m.updatedTill = time.Now().Add(2 * time.Second)
			return m, m.pollCommand()
		}
		m.dataVersion = msg.Version
		m.reloadPending = false
		if msg.Snapshot != nil {
			m.snapshot = *msg.Snapshot
			m.graph = NewGraph(m.snapshot.Items)
			m.selected = m.graph.Root()
			m.centerSelection()
		}
		m.status = fmt.Sprintf("deleted %d concept(s)", len(msg.Deleted))
		m.updatedTill = time.Now().Add(2 * time.Second)
		return m, m.pollCommand()
	case tea.KeyPressMsg:
		return m.handleKey(msg.Key())
	case tea.MouseMsg:
		// Mouse reporting is enabled in View so wheel gestures arrive here as
		// mouse events instead of terminal-generated arrow key sequences.
		return m, nil
	}
	return m, nil
}

func (m *Model) handleKey(key tea.Key) (tea.Model, tea.Cmd) {
	if (key.Code == 'q' && key.Mod == 0) || (key.Code == 'c' && key.Mod&tea.ModCtrl != 0) {
		return m, tea.Quit
	}
	if m.help {
		if key.Code == tea.KeyEscape || key.Code == '?' {
			m.help = false
		}
		return m, nil
	}
	if m.confirmDelete {
		switch key.Code {
		case 'y', 'Y':
			return m, m.deleteCommand()
		case 'n', 'N', tea.KeyEscape:
			m.confirmDelete = false
			m.deleteConfirmed = nil
		}
		return m, nil
	}
	if m.details {
		switch key.Code {
		case 'i', tea.KeyEnter, tea.KeyKpEnter, tea.KeyEscape:
			m.details = false
			m.detailScroll = 0
		case '?':
			m.details = false
			m.detailScroll = 0
			m.help = true
		case tea.KeyUp:
			m.scrollDetails(-1)
		case tea.KeyDown:
			m.scrollDetails(1)
		case tea.KeyPgUp:
			m.scrollDetails(-m.detailViewportHeight())
		case tea.KeyPgDown:
			m.scrollDetails(m.detailViewportHeight())
		case tea.KeyHome:
			m.detailScroll = 0
		case tea.KeyEnd:
			m.detailScroll = m.maxDetailScroll()
		}
		return m, nil
	}
	if m.panMode {
		switch key.Code {
		case 'p', tea.KeyEscape:
			m.panMode = false
			m.ensureSelectionVisible()
		case '0':
			m.centerSelection()
		case '1':
			m.panStep = 1
		case '2':
			m.panStep = 10
		case '3':
			m.panStep = 30
		default:
			if direction, ok := keyDirection(key); ok {
				m.pan(direction, m.panStep)
			}
		}
		return m, nil
	}

	switch key.Code {
	case '?':
		m.help = true
		m.details = false
		return m, nil
	case 'p':
		m.panMode = true
		m.details = false
		return m, nil
	case 'd', tea.KeyDelete:
		if m.selected != "" {
			confirmed, err := ConfirmSubtree(m.snapshot.Items, m.selected)
			if err != nil {
				m.status = err.Error()
			} else {
				m.deleteConfirmed = confirmed
				m.confirmDelete = true
				m.details = false
			}
		}
		return m, nil
	case '0':
		m.centerSelection()
		return m, nil
	case 'i', tea.KeyEnter, tea.KeyKpEnter:
		if m.selected != "" {
			m.details = true
			m.detailScroll = 0
		}
		return m, nil
	case tea.KeyEscape:
		m.details = false
		return m, nil
	}
	if direction, ok := keyDirection(key); ok {
		m.moveSelection(direction)
	}
	return m, nil
}

func (m *Model) deleteCommand() tea.Cmd {
	repository := m.repository
	projectID := m.snapshot.Project.ID
	itemID := m.selected
	confirmed := append([]ItemRevision(nil), m.deleteConfirmed...)
	return func() tea.Msg {
		if repository == nil {
			return deleteResult{Err: errors.New("database is unavailable")}
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		result, err := repository.DeleteSubtree(ctx, projectID, itemID, confirmed)
		if err != nil {
			return deleteResult{Err: err}
		}
		// Read the version first. If another connection commits after this
		// point, the next poll observes a newer version instead of pairing an
		// old snapshot with the newest version and suppressing that reload.
		version, err := repository.DataVersion(ctx)
		if err != nil {
			return deleteResult{Deleted: result.Deleted, RefreshErr: err}
		}
		snapshot, err := repository.LoadSnapshot(ctx, projectID)
		if err != nil {
			return deleteResult{Deleted: result.Deleted, RefreshErr: err}
		}
		return deleteResult{Deleted: result.Deleted, Snapshot: &snapshot, Version: version}
	}
}

type direction int

const (
	directionUp direction = iota
	directionRight
	directionDown
	directionLeft
)

func keyDirection(key tea.Key) (direction, bool) {
	switch key.Code {
	case tea.KeyUp:
		return directionUp, true
	case tea.KeyRight:
		return directionRight, true
	case tea.KeyDown:
		return directionDown, true
	case tea.KeyLeft:
		return directionLeft, true
	default:
		return 0, false
	}
}

func (m *Model) moveSelection(value direction) {
	if m.selected == "" {
		return
	}
	next := m.selected
	switch value {
	case directionUp:
		next = m.graph.Vertical(m.selected, -1)
	case directionRight:
		next = m.graph.Deeper(m.selected)
	case directionDown:
		next = m.graph.Vertical(m.selected, 1)
	case directionLeft:
		next = m.graph.Parent(m.selected)
	}
	if next != m.selected {
		m.selected = next
		m.detailScroll = 0
		m.ensureSelectionVisible()
	}
}

func (m *Model) pan(value direction, amount int) {
	switch value {
	case directionUp:
		m.panY -= amount
	case directionRight:
		m.panX += amount
	case directionDown:
		m.panY += amount
	case directionLeft:
		m.panX -= amount
	}
}

func (m *Model) contentHeight() int { return max(0, m.height-3) }

func (m *Model) centerSelection() {
	position, exists := m.graph.Position[m.selected]
	if !exists {
		return
	}
	m.panX = max(0, position.X-3)
	m.panY = max(0, position.Y-m.contentHeight()/2)
}

func (m *Model) ensureSelectionVisible() {
	position, exists := m.graph.Position[m.selected]
	if !exists || m.width <= 0 || m.contentHeight() <= 0 {
		return
	}
	const horizontalMargin = 3
	const verticalMargin = 2
	if position.X < m.panX+horizontalMargin {
		m.panX = position.X - horizontalMargin
	}
	if position.X+NodeWidth > m.panX+m.width-horizontalMargin {
		m.panX = position.X + NodeWidth - m.width + horizontalMargin
	}
	if position.Y < m.panY+verticalMargin {
		m.panY = position.Y - verticalMargin
	}
	if position.Y >= m.panY+m.contentHeight()-verticalMargin {
		m.panY = position.Y - m.contentHeight() + verticalMargin + 1
	}
}

func (m *Model) View() tea.View {
	view := tea.NewView(m.render())
	view.AltScreen = true
	view.MouseMode = tea.MouseModeCellMotion
	view.WindowTitle = "Mindmap - " + sanitizeTerminalText(m.snapshot.Project.Name)
	return view
}

func (m *Model) render() string {
	value := m.renderStyled()
	if strings.EqualFold(strings.TrimSpace(os.Getenv("TERM")), "dumb") {
		return ansi.Strip(value)
	}
	return value
}

func (m *Model) renderStyled() string {
	if m.width < 42 || m.height < 10 {
		message := lipgloss.NewStyle().Foreground(m.theme.Muted).Render(
			"Mindmap needs a terminal at least 42 x 10.\nResize the window, or press q to quit.",
		)
		return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, message)
	}

	canvas := BuildCanvas(m.graph, m.selected)
	graphView := canvas.Render(m.theme, m.panX, m.panY, m.width, m.contentHeight())
	base := strings.Join([]string{
		m.renderHeader(),
		m.renderGuide(),
		graphView,
		m.renderFooter(),
	}, "\n")
	if !m.details && !m.help && !m.confirmDelete {
		return base
	}
	panel := m.renderDetails()
	if m.help {
		panel = m.renderHelp()
	} else if m.confirmDelete {
		panel = m.renderDeleteConfirmation()
	}
	panelWidth := lipgloss.Width(panel)
	panelHeight := lipgloss.Height(panel)
	layers := lipgloss.NewCompositor(
		lipgloss.NewLayer(base),
		lipgloss.NewLayer(panel).
			X(max(1, m.width-panelWidth-2)).
			Y(max(2, (m.height-panelHeight)/2)).
			Z(10),
	)
	return layers.Render()
}

func (m *Model) renderHeader() string {
	active := "paused"
	if m.snapshot.Project.Active {
		active = "live"
	}
	separator := " · "
	if asciiMode() {
		separator = " | "
	}
	line := fmt.Sprintf(
		" mindmap  /  %s   %d concepts%s%d frontier                         %s ",
		sanitizeTerminalText(m.snapshot.Project.Name), len(m.snapshot.Items), separator,
		m.graph.FrontierCount(), active,
	)
	line = fitLine(line, m.width)
	return lipgloss.NewStyle().
		Foreground(m.theme.Text).
		Background(m.theme.Surface).
		Bold(true).
		Render(line)
}

func (m *Model) renderGuide() string {
	marker, separator := "● ", " · "
	if asciiMode() {
		marker, separator = "o ", " | "
	}
	open := lipgloss.NewStyle().Foreground(m.theme.Open).Render(marker + "open")
	planned := lipgloss.NewStyle().Foreground(m.theme.Planned).Render(marker + "planned")
	settled := lipgloss.NewStyle().Foreground(m.theme.Settled).Render(marker + "settled")
	keys := lipgloss.NewStyle().Foreground(m.theme.Dim).Render(
		"   arrows navigate" + separator + "i inspect" + separator + "d delete" + separator + "p pan" + separator + "? help" + separator + "q quit",
	)
	return fitStyledLine(" "+open+"   "+planned+"   "+settled+keys, m.width)
}

func (m *Model) renderFooter() string {
	text := " " + sanitizeTerminalText(m.snapshot.Project.RoutePath)
	style := lipgloss.NewStyle().Foreground(m.theme.Dim)
	if m.panMode {
		text = fmt.Sprintf(" PAN ×%d  arrows move · 1/2/3 set 1/10/30 · 0 centre · p/esc navigate", m.panStep)
		if asciiMode() {
			text = fmt.Sprintf(" PAN x%d  arrows move | 1/2/3 set 1/10/30 | 0 centre | p/esc navigate", m.panStep)
		}
		style = style.Foreground(m.theme.Text).Background(m.theme.Surface2).Bold(true)
	} else if m.status != "" {
		text = " update warning: " + sanitizeTerminalText(m.status)
		style = style.Foreground(m.theme.Error)
	} else if time.Now().Before(m.updatedTill) {
		text = " ● graph updated live"
		if asciiMode() {
			text = " * graph updated live"
		}
		style = style.Foreground(m.theme.Success)
	} else {
		text += fmt.Sprintf("   canvas %+d,%+d", m.panX, m.panY)
	}
	return style.Render(fitLine(text, m.width))
}

func fitLine(value string, width int) string {
	value = ansi.Truncate(value, width, truncationMarker())
	return value + strings.Repeat(" ", max(0, width-lipgloss.Width(value)))
}

func fitStyledLine(value string, width int) string {
	value = ansi.Truncate(value, width, truncationMarker())
	return value + strings.Repeat(" ", max(0, width-lipgloss.Width(value)))
}

func (m *Model) renderDetails() string {
	panelWidth := min(66, m.width-4)
	lines := m.detailsLines(panelWidth - 4)
	viewportHeight := m.detailViewportHeight()
	offset := min(max(0, m.detailScroll), max(0, len(lines)-viewportHeight))
	end := min(len(lines), offset+viewportHeight)
	visible := append([]string(nil), lines[offset:end]...)
	above, below := offset, len(lines)-end
	position := fmt.Sprintf("↑ / ↓ scroll  ·  %d above  ·  %d below", above, below)
	if asciiMode() {
		position = fmt.Sprintf("up / down scroll  |  %d above  |  %d below", above, below)
	}
	visible = append(visible,
		lipgloss.NewStyle().Foreground(m.theme.Dim).Render(position),
		lipgloss.NewStyle().Foreground(m.theme.Dim).Render("i / enter / esc  close"),
	)
	for index, line := range visible {
		visible[index] = ansi.Truncate(line, panelWidth-4, truncationMarker())
	}
	return m.panel(strings.Join(visible, "\n"), panelWidth)
}

func (m *Model) detailsLines(innerWidth int) []string {
	item, exists := m.graph.ByID[m.selected]
	if !exists {
		return nil
	}
	state := lipgloss.NewStyle().Foreground(m.theme.stateColor(item.State)).Bold(true).
		Render(strings.ToUpper(item.State))
	kind := lipgloss.NewStyle().Foreground(m.theme.Dim).Render("  " + strings.ToUpper(item.Kind))
	lines := []string{state + kind, ""}
	for _, line := range wrapText(sanitizeTerminalText(item.Title), innerWidth) {
		lines = append(lines, lipgloss.NewStyle().Foreground(m.theme.Text).Bold(true).Render(line))
	}
	if item.Summary != "" {
		lines = append(lines, "")
		for _, line := range wrapText(sanitizeTerminalText(item.Summary), innerWidth) {
			lines = append(lines, lipgloss.NewStyle().Foreground(m.theme.Muted).Render(line))
		}
	}
	if item.Resume != "" {
		lines = append(lines, "", lipgloss.NewStyle().Foreground(m.theme.Dim).Bold(true).Render("RESUME"))
		for _, line := range wrapText(sanitizeTerminalText(item.Resume), innerWidth) {
			lines = append(lines, lipgloss.NewStyle().Foreground(m.theme.Open).Render(line))
		}
	}
	if item.ParentID != "" || len(m.graph.Children[item.ID]) > 0 {
		lines = append(lines, "", lipgloss.NewStyle().Foreground(m.theme.Dim).Bold(true).Render("BRANCHES"))
		if parent, ok := m.graph.ByID[item.ParentID]; ok {
			label := "← grew out of"
			if asciiMode() {
				label = "<- grew out of"
			}
			lines = append(lines, m.connectionLines(label, parent.Title, innerWidth)...)
		}
		for _, childID := range m.graph.Children[item.ID] {
			label := "→ branched into"
			if asciiMode() {
				label = "-> branched into"
			}
			lines = append(lines, m.connectionLines(label, m.graph.ByID[childID].Title, innerWidth)...)
		}
	}
	separator := " · "
	if asciiMode() {
		separator = " | "
	}
	meta := fmt.Sprintf("%s%srevision %d", displayDate(sanitizeTerminalText(item.UpdatedAt)), separator, item.Revision)
	lines = append(lines, "", lipgloss.NewStyle().Foreground(m.theme.Dim).Render(meta))
	return lines
}

func (m *Model) connectionLines(label, title string, width int) []string {
	plainLabel := label + "  "
	indent := strings.Repeat(" ", lipgloss.Width(plainLabel))
	wrapped := wrapText(sanitizeTerminalText(title), max(1, width-lipgloss.Width(plainLabel)))
	lines := make([]string, 0, len(wrapped))
	for index, line := range wrapped {
		prefix := indent
		if index == 0 {
			prefix = plainLabel
		}
		lines = append(lines,
			lipgloss.NewStyle().Foreground(m.theme.Dim).Render(prefix)+
				lipgloss.NewStyle().Foreground(m.theme.Planned).Render(line),
		)
	}
	return lines
}

func (m *Model) detailViewportHeight() int {
	// Leave room for two status lines and the panel border, with breathing
	// room around the overlay inside the terminal.
	return max(1, m.height-8)
}

func (m *Model) maxDetailScroll() int {
	panelWidth := min(66, m.width-4)
	return max(0, len(m.detailsLines(panelWidth-4))-m.detailViewportHeight())
}

func (m *Model) clampDetailScroll() {
	m.detailScroll = min(max(0, m.detailScroll), m.maxDetailScroll())
}

func (m *Model) scrollDetails(delta int) {
	m.detailScroll += delta
	m.clampDetailScroll()
}

func (m *Model) renderHelp() string {
	panelWidth := min(62, m.width-4)
	contentWidth := panelWidth - 4
	left, right, upDown, deeper, infoUpDown := "←", "→", "↑ / ↓", "deeper; open › planned › settled", "↑ / ↓ (info)"
	if asciiMode() {
		left, right, upDown, deeper, infoUpDown = "<-", "->", "up / down", "deeper; open > planned > settled", "up/down (info)"
	}
	lines := []string{
		lipgloss.NewStyle().Foreground(m.theme.Text).Bold(true).Render("KEYBOARD"),
		"",
		m.helpLine(left, "parent"),
		m.helpLine(right, deeper),
		m.helpLine(upDown, "previous / next node at this depth"),
		m.helpLine("i / enter", "open selected-node information"),
		m.helpLine("d / delete", "delete selected concept and descendants"),
		m.helpLine(infoUpDown, "scroll information one line"),
		m.helpLine("p", "toggle pan mode"),
		m.helpLine("1 / 2 / 3", "pan by 1 / 10 / 30 characters"),
		m.helpLine("0", "centre the selected node"),
		m.helpLine("? / esc", "close this help"),
		m.helpLine("q / ctrl-c", "quit"),
		"",
		lipgloss.NewStyle().Foreground(m.theme.Dim).Render("The graph watches SQLite and redraws automatically."),
	}
	maximumLines := max(3, m.height-6)
	if len(lines) > maximumLines {
		lines = append(lines[:maximumLines-1], lipgloss.NewStyle().Foreground(m.theme.Dim).Render(truncationMarker()))
	}
	for index, line := range lines {
		lines[index] = ansi.Truncate(line, contentWidth, truncationMarker())
	}
	return m.panel(strings.Join(lines, "\n"), panelWidth)
}

func (m *Model) renderDeleteConfirmation() string {
	item, exists := m.graph.ByID[m.selected]
	if !exists {
		return m.panel("Selected concept no longer exists.\n\nEsc  cancel", min(58, m.width-4))
	}
	count := m.subtreeSize(item.ID)
	word := "concept"
	if count != 1 {
		word = "concepts"
	}
	message := strings.Join([]string{
		lipgloss.NewStyle().Foreground(m.theme.Error).Bold(true).Render("DELETE BRANCH?"),
		"",
		lipgloss.NewStyle().Foreground(m.theme.Text).Bold(true).Render(sanitizeTerminalText(item.Title)),
		fmt.Sprintf("This permanently removes %d %s from the map.", count, word),
		"Recorded event and transcript history are retained.",
		"",
		lipgloss.NewStyle().Foreground(m.theme.Error).Bold(true).Render("y  delete") + "    " +
			lipgloss.NewStyle().Foreground(m.theme.Muted).Render("n / esc  cancel"),
	}, "\n")
	return m.panel(message, min(58, m.width-4))
}

func (m *Model) subtreeSize(itemID string) int {
	count := 1
	for _, child := range m.graph.Children[itemID] {
		count += m.subtreeSize(child)
	}
	return count
}

func (m *Model) helpLine(key, description string) string {
	panelWidth := min(62, m.width-4)
	description = ansi.Truncate(description, max(1, panelWidth-4-13), truncationMarker())
	return lipgloss.NewStyle().Foreground(m.theme.Planned).Bold(true).Width(13).Render(key) +
		lipgloss.NewStyle().Foreground(m.theme.Muted).Render(description)
}

func (m *Model) panel(content string, panelWidth int) string {
	border := lipgloss.RoundedBorder()
	if asciiMode() {
		border = lipgloss.ASCIIBorder()
	}
	return lipgloss.NewStyle().
		Width(panelWidth).
		Padding(0, 1).
		Border(border).
		BorderForeground(m.theme.Border).
		Foreground(m.theme.Text).
		Background(m.theme.Surface).
		Render(content)
}

func wrapText(value string, width int) []string {
	if width <= 0 {
		return nil
	}
	return strings.Split(ansi.Wrap(value, width, ""), "\n")
}

func displayDate(value string) string {
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return "updated " + value
	}
	return "updated " + parsed.Local().Format("2 Jan 2006, 15:04")
}
