package tui

import "sort"

const (
	NodeWidth   = 30
	ColumnWidth = 40
	LeafSpacing = 3
)

type Point struct {
	X int
	Y int
}

type branchScore struct {
	activeDepth int
	activeCount int
	totalDepth  int
}

type Graph struct {
	Items      []Item
	ByID       map[string]Item
	Children   map[string][]string
	Roots      []string
	Depth      map[string]int
	Position   map[string]Point
	Order      map[string]int
	Frontier   map[string]bool
	depthOrder map[int][]string
	scores     map[string]branchScore
	scoring    map[string]bool
}

func NewGraph(items []Item) *Graph {
	graph := &Graph{
		Items:      append([]Item(nil), items...),
		ByID:       make(map[string]Item, len(items)),
		Children:   make(map[string][]string),
		Depth:      make(map[string]int),
		Position:   make(map[string]Point),
		Order:      make(map[string]int),
		Frontier:   make(map[string]bool),
		depthOrder: make(map[int][]string),
		scores:     make(map[string]branchScore),
		scoring:    make(map[string]bool),
	}
	for index, item := range graph.Items {
		graph.ByID[item.ID] = item
		graph.Order[item.ID] = index
	}
	for _, item := range graph.Items {
		if item.ParentID == "" || item.ParentID == item.ID {
			graph.Roots = append(graph.Roots, item.ID)
			continue
		}
		if _, exists := graph.ByID[item.ParentID]; !exists {
			graph.Roots = append(graph.Roots, item.ID)
			continue
		}
		graph.Children[item.ParentID] = append(graph.Children[item.ParentID], item.ID)
	}
	for _, item := range graph.Items {
		children := graph.Children[item.ID]
		graph.Frontier[item.ID] = item.State != "settled" && len(children) == 0
	}

	nextLeaf := 1
	visited := make(map[string]bool, len(items))
	var place func(string, int) int
	place = func(id string, depth int) int {
		if visited[id] {
			return nextLeaf
		}
		visited[id] = true
		graph.Depth[id] = depth
		children := graph.Children[id]
		var y int
		if len(children) == 0 {
			y = nextLeaf
			nextLeaf += LeafSpacing
		} else {
			first := place(children[0], depth+1)
			last := first
			for _, child := range children[1:] {
				last = place(child, depth+1)
			}
			y = (first + last) / 2
		}
		graph.Position[id] = Point{X: 2 + depth*ColumnWidth, Y: y}
		graph.depthOrder[depth] = append(graph.depthOrder[depth], id)
		return y
	}
	for _, root := range graph.Roots {
		place(root, 0)
		nextLeaf += 1
	}
	// A corrupt legacy map should remain inspectable instead of disappearing.
	for _, item := range graph.Items {
		if !visited[item.ID] {
			graph.Roots = append(graph.Roots, item.ID)
			place(item.ID, 0)
			nextLeaf++
		}
	}
	for depth := range graph.depthOrder {
		sort.SliceStable(graph.depthOrder[depth], func(i, j int) bool {
			left, right := graph.depthOrder[depth][i], graph.depthOrder[depth][j]
			if graph.Position[left].Y != graph.Position[right].Y {
				return graph.Position[left].Y < graph.Position[right].Y
			}
			return graph.Order[left] < graph.Order[right]
		})
	}
	for _, root := range graph.Roots {
		graph.score(root)
	}
	return graph
}

func (g *Graph) Root() string {
	if len(g.Roots) == 0 {
		return ""
	}
	return g.Roots[0]
}

func (g *Graph) Parent(id string) string {
	item, exists := g.ByID[id]
	if !exists {
		return id
	}
	if _, exists := g.ByID[item.ParentID]; !exists {
		return id
	}
	return item.ParentID
}

func statePriority(state string) int {
	switch state {
	case "open":
		return 0
	case "planned":
		return 1
	default:
		return 2
	}
}

func (g *Graph) score(id string) branchScore {
	if value, exists := g.scores[id]; exists {
		return value
	}
	if g.scoring[id] {
		return branchScore{}
	}
	g.scoring[id] = true
	defer delete(g.scoring, id)
	item := g.ByID[id]
	result := branchScore{totalDepth: 1}
	if item.State != "settled" {
		result.activeDepth = 1
		result.activeCount = 1
	}
	for _, child := range g.Children[id] {
		childScore := g.score(child)
		if childScore.totalDepth+1 > result.totalDepth {
			result.totalDepth = childScore.totalDepth + 1
		}
		if childScore.activeDepth > 0 && childScore.activeDepth+1 > result.activeDepth {
			result.activeDepth = childScore.activeDepth + 1
		}
		result.activeCount += childScore.activeCount
	}
	g.scores[id] = result
	return result
}

func (g *Graph) Deeper(id string) string {
	children := g.Children[id]
	if len(children) == 0 {
		return id
	}
	best := children[0]
	for _, candidate := range children[1:] {
		if g.prefer(candidate, best) {
			best = candidate
		}
	}
	return best
}

func (g *Graph) prefer(candidate, current string) bool {
	left, right := g.ByID[candidate], g.ByID[current]
	if statePriority(left.State) != statePriority(right.State) {
		return statePriority(left.State) < statePriority(right.State)
	}
	leftScore, rightScore := g.score(candidate), g.score(current)
	if leftScore.activeDepth != rightScore.activeDepth {
		return leftScore.activeDepth > rightScore.activeDepth
	}
	if leftScore.activeCount != rightScore.activeCount {
		return leftScore.activeCount > rightScore.activeCount
	}
	if leftScore.totalDepth != rightScore.totalDepth {
		return leftScore.totalDepth > rightScore.totalDepth
	}
	return g.Order[candidate] < g.Order[current]
}

func (g *Graph) Vertical(id string, delta int) string {
	depth, exists := g.Depth[id]
	if !exists || delta == 0 {
		return id
	}
	ordered := g.depthOrder[depth]
	for index, candidate := range ordered {
		if candidate != id {
			continue
		}
		target := index + delta
		if target < 0 || target >= len(ordered) {
			return id
		}
		return ordered[target]
	}
	return id
}

func (g *Graph) FrontierCount() int {
	count := 0
	for _, frontier := range g.Frontier {
		if frontier {
			count++
		}
	}
	return count
}
