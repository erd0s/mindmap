package tui

import (
	"image/color"
	"os"
	"strings"

	"charm.land/lipgloss/v2"
)

type Theme struct {
	Background color.Color
	Surface    color.Color
	Surface2   color.Color
	Border     color.Color
	Text       color.Color
	Muted      color.Color
	Dim        color.Color
	Open       color.Color
	Planned    color.Color
	Settled    color.Color
	Success    color.Color
	Error      color.Color
	Edge       lipgloss.Style
}

func NewTheme() Theme {
	if _, disabled := os.LookupEnv("NO_COLOR"); disabled || strings.EqualFold(os.Getenv("MINDMAP_COLOR"), "none") || strings.EqualFold(os.Getenv("TERM"), "dumb") {
		plain := lipgloss.NoColor{}
		return Theme{
			Background: plain, Surface: plain, Surface2: plain, Border: plain,
			Text: plain, Muted: plain, Dim: plain, Open: plain, Planned: plain,
			Settled: plain, Success: plain, Error: plain,
			Edge: lipgloss.NewStyle(),
		}
	}
	theme := Theme{
		Background: lipgloss.Color("#09090b"),
		Surface:    lipgloss.Color("#121214"),
		Surface2:   lipgloss.Color("#202024"),
		Border:     lipgloss.Color("#3f3f46"),
		Text:       lipgloss.Color("#e4e4e7"),
		Muted:      lipgloss.Color("#a1a1aa"),
		Dim:        lipgloss.Color("#62626b"),
		Open:       lipgloss.Color("#fbbf24"),
		Planned:    lipgloss.Color("#22d3ee"),
		Settled:    lipgloss.Color("#71717a"),
		Success:    lipgloss.Color("#34d399"),
		Error:      lipgloss.Color("#f87171"),
	}
	theme.Edge = lipgloss.NewStyle().Foreground(theme.Border)
	return theme
}

func (t Theme) stateColor(state string) color.Color {
	switch state {
	case "open":
		return t.Open
	case "planned":
		return t.Planned
	default:
		return t.Settled
	}
}

func (t Theme) Node(text, state string, root, selected bool) string {
	style := lipgloss.NewStyle().Foreground(t.stateColor(state))
	if root {
		style = style.Bold(true)
	}
	if selected {
		style = style.Background(t.Surface2).Bold(true)
	}
	return style.Render(text)
}
