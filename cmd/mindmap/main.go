package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"

	"github.com/charmbracelet/x/term"
	"github.com/erd0s/mindmap/internal/store"
	"github.com/erd0s/mindmap/internal/tui"
)

var version = "dev"

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "mindmap: %v\n", err)
		os.Exit(2)
	}
}

func run(arguments []string) error {
	if len(arguments) == 0 {
		return runTUI(nil)
	}
	switch arguments[0] {
	case "-h", "--help", "help":
		printHelp()
		return nil
	case "-v", "--version", "version":
		fmt.Println(version)
		return nil
	case "start", "activate":
		return changeActivation(arguments[1:], true)
	case "stop", "deactivate":
		return changeActivation(arguments[1:], false)
	case "status":
		return showStatus(arguments[1:])
	case "projects":
		return listProjects(arguments[1:])
	case "snapshot":
		return showSnapshot(arguments[1:])
	case "delete":
		return deleteBranch(arguments[1:])
	case "open":
		return openDesktop(arguments[1:])
	case "setup":
		return setupIntegrations(arguments[1:])
	case "integrations":
		return showIntegrations(arguments[1:])
	case "doctor":
		return doctor(arguments[1:])
	case "config":
		return configure(arguments[1:])
	default:
		if strings.HasPrefix(arguments[0], "-") {
			return runTUI(arguments)
		}
		return fmt.Errorf("unknown command %q (run mindmap --help)", arguments[0])
	}
}

func printHelp() {
	fmt.Print(`Mindmap keeps a small causal map of the work in each coding project.

Usage:
  mindmap [viewer options]       Open the live terminal viewer
  mindmap <command> [options]

Commands:
  start          Track the current project persistently
  stop           Stop tracking; keep the project's history
  status         Show the project and its current graph
  projects       List every local project map
  snapshot       Export one project as JSON
  delete         Delete a concept and all descendants
  open           Open a project in Mindmap Desktop (macOS)
  setup          Install or repair Codex and Claude integrations
  integrations   Report installed agent integrations
  doctor         Check the database, terminal, desktop, and agents
  config         Set terminal color and character preferences

Viewer options:
  --root PATH        Project path (default: current directory)
  --route ROUTE      Project route, such as /dev/mindmap
  --database PATH    Override mindmap.sqlite3
  --color MODE       auto or none
  --ascii MODE       auto, always, or never

Run "mindmap <command> --help" for command-specific options. Press ? in the
terminal viewer for the complete keyboard reference.
`)
}

func databaseFlag(flags *flag.FlagSet) *string {
	value, err := store.DefaultDatabasePath()
	if err != nil {
		value = "mindmap.sqlite3"
	}
	return flags.String("database", value, "path to mindmap.sqlite3")
}

func runTUI(arguments []string) error {
	defaults, err := loadConfig()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("mindmap", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	root := flags.String("root", "", "project path (defaults to current directory)")
	route := flags.String("route", "", "project route, such as /dev/mindmap")
	database := databaseFlag(flags)
	color := flags.String("color", defaults.Color, "color mode: auto or none")
	ascii := flags.String("ascii", defaults.ASCII, "character mode: auto, always, or never")
	flags.Usage = printHelp
	if err := flags.Parse(arguments); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	if *root != "" && *route != "" {
		return errors.New("--root and --route cannot be used together")
	}
	if err := applyDisplayOptions(*color, *ascii); err != nil {
		return err
	}
	return tui.Run(tui.RunOptions{Database: *database, Root: *root, Route: *route})
}

func changeActivation(arguments []string, active bool) error {
	name := "start"
	if !active {
		name = "stop"
	}
	flags := flag.NewFlagSet("mindmap "+name, flag.ContinueOnError)
	root := flags.String("root", "", "project path (default: current directory)")
	database := databaseFlag(flags)
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	repository, err := store.Open(*database, false)
	if err != nil {
		return err
	}
	defer repository.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	var project store.Project
	if active {
		project, err = repository.Activate(ctx, *root)
	} else {
		project, err = repository.Deactivate(ctx, *root)
	}
	if err != nil {
		return err
	}
	state := "tracking"
	if !active {
		state = "stopped; history retained"
	}
	fmt.Printf("Mindmap %s for %s (%s)\n", state, project.RootPath, project.RoutePath)
	return nil
}

func showStatus(arguments []string) error {
	flags := flag.NewFlagSet("mindmap status", flag.ContinueOnError)
	root := flags.String("root", "", "project path (default: current directory)")
	route := flags.String("route", "", "project route")
	database := databaseFlag(flags)
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	return withSnapshot(*database, *root, *route, func(snapshot store.Snapshot) error {
		frontier := frontierCount(snapshot.Items)
		state := "paused"
		if snapshot.Project.Active {
			state = "active"
		}
		fmt.Printf("%s  %s\n%s\n%d concepts, %d frontier\n", snapshot.Project.Name, state,
			snapshot.Project.RootPath, len(snapshot.Items), frontier)
		return nil
	})
}

func listProjects(arguments []string) error {
	flags := flag.NewFlagSet("mindmap projects", flag.ContinueOnError)
	database := databaseFlag(flags)
	jsonOutput := flags.Bool("json", false, "emit JSON")
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	repository, err := store.OpenExisting(*database)
	if err != nil {
		return err
	}
	defer repository.Close()
	projects, err := repository.Projects(context.Background())
	if err != nil {
		return err
	}
	if *jsonOutput {
		return printJSON(projects)
	}
	for _, project := range projects {
		state := "paused"
		if project.Active {
			state = "active"
		}
		fmt.Printf("%-8s %-24s %s\n", state, project.Name, project.RootPath)
	}
	return nil
}

func showSnapshot(arguments []string) error {
	flags := flag.NewFlagSet("mindmap snapshot", flag.ContinueOnError)
	root := flags.String("root", "", "project path (default: current directory)")
	route := flags.String("route", "", "project route")
	database := databaseFlag(flags)
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	return withSnapshot(*database, *root, *route, func(snapshot store.Snapshot) error {
		return printJSON(snapshot)
	})
}

func deleteBranch(arguments []string) error {
	flags := flag.NewFlagSet("mindmap delete", flag.ContinueOnError)
	root := flags.String("root", "", "project path (default: current directory)")
	route := flags.String("route", "", "project route")
	database := databaseFlag(flags)
	yes := flags.Bool("yes", false, "delete without an interactive confirmation")
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 1 {
		return errors.New("usage: mindmap delete [--root PATH | --route ROUTE] [--yes] CONCEPT_ID")
	}
	if *root != "" && *route != "" {
		return errors.New("--root and --route cannot be used together")
	}
	repository, err := store.Open(*database, false)
	if err != nil {
		return err
	}
	defer repository.Close()
	project, err := repository.ResolveProject(*root, *route)
	if err != nil {
		return err
	}
	itemID := flags.Arg(0)
	snapshot, err := repository.LoadSnapshot(context.Background(), project.ID)
	if err != nil {
		return err
	}
	confirmed, err := store.ConfirmSubtree(snapshot.Items, itemID)
	if err != nil {
		return err
	}
	count, title := len(confirmed), itemTitle(snapshot.Items, itemID)
	if !*yes {
		if !isTerminal(os.Stdin) {
			return errors.New("refusing non-interactive deletion without --yes")
		}
		fmt.Printf("Delete %q and %d concept(s)? [y/N] ", title, count)
		var response string
		if _, err := fmt.Fscanln(os.Stdin, &response); err != nil && !errors.Is(err, os.ErrClosed) {
			return fmt.Errorf("read confirmation: %w", err)
		}
		if !strings.EqualFold(response, "y") && !strings.EqualFold(response, "yes") {
			fmt.Println("Cancelled.")
			return nil
		}
	}
	result, err := repository.DeleteSubtree(context.Background(), project.ID, itemID, confirmed)
	if err != nil {
		return err
	}
	fmt.Printf("Deleted %d concept(s). Transcript and event history were retained.\n", len(result.Deleted))
	return nil
}

func withSnapshot(database, root, route string, action func(store.Snapshot) error) error {
	if root != "" && route != "" {
		return errors.New("--root and --route cannot be used together")
	}
	repository, err := store.OpenExisting(database)
	if err != nil {
		return err
	}
	defer repository.Close()
	project, err := repository.ResolveProject(root, route)
	if err != nil {
		return err
	}
	snapshot, err := repository.LoadSnapshot(context.Background(), project.ID)
	if err != nil {
		return err
	}
	return action(snapshot)
}

func openDesktop(arguments []string) error {
	flags := flag.NewFlagSet("mindmap open", flag.ContinueOnError)
	root := flags.String("root", "", "project path (default: current directory)")
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	if runtime.GOOS != "darwin" {
		return errors.New("desktop app v1 is available for macOS; use mindmap for the terminal viewer")
	}
	canonical, err := resolveDesktopProjectRoot(valueOrCurrent(*root))
	if err != nil {
		return err
	}
	// -n starts a short-lived second instance; Wails forwards its arguments to
	// the existing process, which creates another native project window.
	command := exec.Command("open", "-n", "-a", "Mindmap", "--args", "--project-root", canonical)
	if output, err := command.CombinedOutput(); err != nil {
		return fmt.Errorf("open Mindmap Desktop: %w (%s)", err, strings.TrimSpace(string(output)))
	}
	return nil
}

func resolveDesktopProjectRoot(root string) (string, error) {
	canonical, err := store.CanonicalPath(root)
	if err != nil {
		return "", err
	}
	database, err := store.DefaultDatabasePath()
	if err != nil {
		return "", err
	}
	repository, err := store.OpenExisting(database)
	if err != nil {
		return "", err
	}
	defer repository.Close()
	project, err := repository.ResolveProject(canonical, "")
	if err != nil {
		return "", err
	}
	return project.RootPath, nil
}

func frontierCount(items []store.Item) int {
	parents := make(map[string]bool)
	for _, item := range items {
		if item.ParentID != "" {
			parents[item.ParentID] = true
		}
	}
	count := 0
	for _, item := range items {
		if item.State != "settled" && !parents[item.ID] {
			count++
		}
	}
	return count
}

func itemTitle(items []store.Item, itemID string) string {
	for _, item := range items {
		if item.ID == itemID {
			return item.Title
		}
	}
	return ""
}

func printJSON(value any) error {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	encoder.SetEscapeHTML(false)
	return encoder.Encode(value)
}

func valueOrCurrent(value string) string {
	if value != "" {
		return value
	}
	current, err := os.Getwd()
	if err != nil {
		return "."
	}
	return current
}

func isTerminal(file *os.File) bool {
	return term.IsTerminal(file.Fd())
}

func commandFlagError(err error) error {
	if errors.Is(err, flag.ErrHelp) {
		return nil
	}
	return err
}
