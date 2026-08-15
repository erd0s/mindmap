package tui

import (
	"os"
	"sort"
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

const (
	lineUp uint8 = 1 << iota
	lineRight
	lineDown
	lineLeft
)

type nodeSpan struct {
	X        int
	Text     string
	State    string
	Root     bool
	Selected bool
}

type GraphCanvas struct {
	lines  map[Point]uint8
	spans  map[int][]nodeSpan
	Width  int
	Height int
}

func BuildCanvas(graph *Graph, selected string) *GraphCanvas {
	canvas := &GraphCanvas{
		lines: make(map[Point]uint8),
		spans: make(map[int][]nodeSpan),
	}
	for parentID, children := range graph.Children {
		if len(children) == 0 {
			continue
		}
		parent := graph.Position[parentID]
		childX := graph.Position[children[0]].X
		junctionX := childX - 4
		startX := parent.X + NodeWidth
		canvas.horizontal(startX, junctionX, parent.Y)
		minimumY, maximumY := parent.Y, parent.Y
		for _, childID := range children {
			child := graph.Position[childID]
			if child.Y < minimumY {
				minimumY = child.Y
			}
			if child.Y > maximumY {
				maximumY = child.Y
			}
			canvas.horizontal(junctionX, child.X-1, child.Y)
		}
		canvas.vertical(junctionX, minimumY, maximumY)
	}
	for _, item := range graph.Items {
		position, exists := graph.Position[item.ID]
		if !exists {
			continue
		}
		marker := "●"
		if graph.Frontier[item.ID] {
			marker = "◉"
		}
		if item.ParentID == "" {
			marker = "◆"
		}
		if asciiMode() {
			marker = "o"
			if graph.Frontier[item.ID] {
				marker = "@"
			}
			if item.ParentID == "" {
				marker = "#"
			}
		}
		isSelected := item.ID == selected
		prefix := "  " + marker + " "
		textWidth := NodeWidth
		titleWidth := NodeWidth - lipgloss.Width(prefix) - 1
		if isSelected {
			prefix = " " + marker + " "
			textWidth = NodeWidth - 2
			titleWidth = textWidth - lipgloss.Width(prefix)
		}
		title := ansi.Truncate(sanitizeTerminalText(item.Title), titleWidth, truncationMarker())
		text := prefix + title
		text += strings.Repeat(" ", max(0, textWidth-lipgloss.Width(text)))
		spans := []struct {
			y    int
			text string
		}{{position.Y, text}}
		if isSelected {
			topLeft, horizontal, topRight := "╭", "─", "╮"
			vertical, bottomLeft, bottomRight := "│", "╰", "╯"
			if asciiMode() {
				topLeft, horizontal, topRight = "+", "-", "+"
				vertical, bottomLeft, bottomRight = "|", "+", "+"
			}
			spans = []struct {
				y    int
				text string
			}{
				{position.Y - 1, topLeft + strings.Repeat(horizontal, NodeWidth-2) + topRight},
				{position.Y, vertical + text + vertical},
				{position.Y + 1, bottomLeft + strings.Repeat(horizontal, NodeWidth-2) + bottomRight},
			}
		}
		for _, value := range spans {
			canvas.spans[value.y] = append(canvas.spans[value.y], nodeSpan{
				X:        position.X,
				Text:     value.text,
				State:    item.State,
				Root:     item.ParentID == "",
				Selected: isSelected,
			})
		}
		canvas.Width = max(canvas.Width, position.X+NodeWidth+1)
		canvas.Height = max(canvas.Height, position.Y+2)
	}
	for row := range canvas.spans {
		sort.Slice(canvas.spans[row], func(i, j int) bool {
			return canvas.spans[row][i].X < canvas.spans[row][j].X
		})
	}
	return canvas
}

func (c *GraphCanvas) connect(left, right Point) {
	dx, dy := right.X-left.X, right.Y-left.Y
	switch {
	case dx == 1 && dy == 0:
		c.lines[left] |= lineRight
		c.lines[right] |= lineLeft
	case dx == -1 && dy == 0:
		c.lines[left] |= lineLeft
		c.lines[right] |= lineRight
	case dx == 0 && dy == 1:
		c.lines[left] |= lineDown
		c.lines[right] |= lineUp
	case dx == 0 && dy == -1:
		c.lines[left] |= lineUp
		c.lines[right] |= lineDown
	}
}

func (c *GraphCanvas) horizontal(from, to, y int) {
	if from > to {
		from, to = to, from
	}
	for x := from; x < to; x++ {
		c.connect(Point{X: x, Y: y}, Point{X: x + 1, Y: y})
	}
}

func (c *GraphCanvas) vertical(x, from, to int) {
	if from > to {
		from, to = to, from
	}
	for y := from; y < to; y++ {
		c.connect(Point{X: x, Y: y}, Point{X: x, Y: y + 1})
	}
}

func lineRune(mask uint8) rune {
	if asciiMode() {
		switch mask {
		case lineUp, lineDown, lineUp | lineDown:
			return '|'
		case lineLeft, lineRight, lineLeft | lineRight:
			return '-'
		default:
			return '+'
		}
	}
	switch mask {
	case lineUp, lineDown, lineUp | lineDown:
		return '│'
	case lineLeft, lineRight, lineLeft | lineRight:
		return '─'
	case lineRight | lineDown:
		return '┌'
	case lineLeft | lineDown:
		return '┐'
	case lineRight | lineUp:
		return '└'
	case lineLeft | lineUp:
		return '┘'
	case lineUp | lineDown | lineRight:
		return '├'
	case lineUp | lineDown | lineLeft:
		return '┤'
	case lineLeft | lineRight | lineDown:
		return '┬'
	case lineLeft | lineRight | lineUp:
		return '┴'
	case lineUp | lineRight | lineDown | lineLeft:
		return '┼'
	default:
		return '·'
	}
}

func asciiMode() bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("MINDMAP_ASCII")))
	term := strings.ToLower(strings.TrimSpace(os.Getenv("TERM")))
	if value == "never" {
		return false
	}
	return value == "1" || value == "true" || value == "always" || term == "dumb" ||
		strings.HasPrefix(term, "vt100") || strings.HasPrefix(term, "vt220") ||
		!localeSupportsUTF8()
}

func localeSupportsUTF8() bool {
	locale := ""
	for _, name := range []string{"LC_ALL", "LC_CTYPE", "LANG"} {
		if value := strings.TrimSpace(os.Getenv(name)); value != "" {
			locale = strings.ToLower(value)
			break
		}
	}
	if locale == "" {
		return true
	}
	return strings.Contains(locale, "utf-8") || strings.Contains(locale, "utf8")
}

func truncationMarker() string {
	if asciiMode() {
		return "..."
	}
	return "…"
}

func sanitizeTerminalText(value string) string {
	var safe strings.Builder
	for _, character := range value {
		switch {
		case character == '\n' || character == '\r' || character == '\t':
			safe.WriteByte(' ')
		case character < 0x20 || (character >= 0x7f && character <= 0x9f):
			safe.WriteByte('?')
		case asciiMode() && character > 0x7e:
			safe.WriteByte('?')
		default:
			safe.WriteRune(character)
		}
	}
	return safe.String()
}

type renderToken struct {
	text  string
	width int
}

func (c *GraphCanvas) Render(theme Theme, originX, originY, width, height int) string {
	if width <= 0 || height <= 0 {
		return ""
	}
	rows := make([]string, height)
	for screenY := 0; screenY < height; screenY++ {
		canvasY := originY + screenY
		base := make([]rune, width)
		for index := range base {
			base[index] = ' '
		}
		for screenX := 0; screenX < width; screenX++ {
			if mask := c.lines[Point{X: originX + screenX, Y: canvasY}]; mask != 0 {
				base[screenX] = lineRune(mask)
			}
		}
		overlays := make(map[int]renderToken)
		covered := make([]bool, width)
		for _, span := range c.spans[canvasY] {
			spanEnd := span.X + lipgloss.Width(span.Text)
			viewEnd := originX + width
			if spanEnd <= originX || span.X >= viewEnd {
				continue
			}
			leftClip := max(0, originX-span.X)
			available := min(spanEnd, viewEnd) - max(span.X, originX)
			text := ansi.TruncateLeft(span.Text, leftClip, "")
			text = ansi.Truncate(text, available, "")
			visibleWidth := lipgloss.Width(text)
			if visibleWidth == 0 {
				continue
			}
			start := max(span.X, originX) - originX
			overlays[start] = renderToken{
				text:  theme.Node(text, span.State, span.Root, span.Selected),
				width: visibleWidth,
			}
			for column := start; column < min(width, start+visibleWidth); column++ {
				covered[column] = true
			}
		}

		var row strings.Builder
		var edge strings.Builder
		flushEdge := func() {
			if edge.Len() > 0 {
				row.WriteString(theme.Edge.Render(edge.String()))
				edge.Reset()
			}
		}
		for column := 0; column < width; {
			if token, exists := overlays[column]; exists {
				flushEdge()
				row.WriteString(token.text)
				column += token.width
				continue
			}
			if covered[column] {
				column++
				continue
			}
			edge.WriteRune(base[column])
			column++
		}
		flushEdge()
		rows[screenY] = row.String()
	}
	return strings.Join(rows, "\n")
}
