package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/erd0s/mindmap/internal/store"
)

const marketplaceSource = "erd0s/mindmap"
const marketplaceName = "erd0s-mindmap"

type integrationStatus struct {
	Host                   string `json:"host"`
	Available              bool   `json:"available"`
	Installed              bool   `json:"installed"`
	Current                bool   `json:"current"`
	Legacy                 bool   `json:"legacy"`
	LegacyMarketplaceOwned bool   `json:"-"`
	Version                string `json:"version,omitempty"`
	PluginID               string `json:"plugin_id,omitempty"`
	CheckFailed            bool   `json:"-"`
	Detail                 string `json:"detail"`
}

func integrationStatuses() []integrationStatus {
	return []integrationStatus{inspectIntegration("codex"), inspectIntegration("claude")}
}

func inspectIntegration(host string) integrationStatus {
	status := integrationStatus{Host: host}
	path, err := exec.LookPath(host)
	if err != nil {
		status.Detail = "agent command not found"
		return status
	}
	status.Available = true
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	output, err := exec.CommandContext(ctx, path, "plugin", "list", "--json").CombinedOutput()
	if ctx.Err() != nil {
		status.Detail = "plugin check timed out"
		return status
	}
	text := string(output)
	if err != nil {
		status.CheckFailed = true
		status.Detail = "plugin check failed" + outputSuffix(strings.TrimSpace(text))
		return status
	}
	parsed, err := parseIntegrationStatus(host, output)
	if err != nil {
		status.CheckFailed = true
		status.Detail = "unrecognized plugin-list response: " + err.Error()
		return status
	}
	parsed.Available = true
	if parsed.Legacy && host == "codex" {
		marketplaceOutput, marketplaceErr := exec.CommandContext(ctx, path, "plugin", "marketplace", "list", "--json").CombinedOutput()
		if marketplaceErr == nil {
			parsed.LegacyMarketplaceOwned = legacyMarketplaceIsMindmap(marketplaceOutput)
		}
	}
	return parsed
}

func parseIntegrationStatus(host string, output []byte) (integrationStatus, error) {
	status := integrationStatus{Host: host, Available: true}
	currentID := "mindmap@" + marketplaceName
	switch host {
	case "codex":
		var payload struct {
			Installed []struct {
				PluginID        string `json:"pluginId"`
				Name            string `json:"name"`
				MarketplaceName string `json:"marketplaceName"`
				Version         string `json:"version"`
			} `json:"installed"`
		}
		if err := json.Unmarshal(output, &payload); err != nil {
			return status, err
		}
		for _, plugin := range payload.Installed {
			if plugin.PluginID == currentID {
				status.Installed, status.PluginID, status.Version = true, plugin.PluginID, plugin.Version
			}
			if plugin.PluginID == "mindmap@personal" {
				status.Legacy = true
			}
		}
	case "claude":
		var payload []struct {
			ID      string `json:"id"`
			Version string `json:"version"`
		}
		if err := json.Unmarshal(output, &payload); err != nil {
			return status, err
		}
		for _, plugin := range payload {
			if plugin.ID == currentID {
				status.Installed, status.PluginID, status.Version = true, plugin.ID, plugin.Version
			}
		}
	default:
		return status, fmt.Errorf("unsupported host %q", host)
	}
	status.Current = status.Installed && (version == "dev" || status.Version == version)
	switch {
	case status.Legacy:
		status.Detail = "legacy Mindmap plugin requires migration"
	case status.Installed && !status.Current:
		status.Detail = fmt.Sprintf("Mindmap %s installed; %s available", status.Version, version)
	case status.Current:
		status.Detail = "Mindmap " + status.Version + " installed"
	default:
		status.Detail = "agent found; Mindmap plugin not installed"
	}
	return status, nil
}

func legacyMarketplaceIsMindmap(output []byte) bool {
	var payload struct {
		Marketplaces []struct {
			Name   string `json:"name"`
			Source struct {
				Source string `json:"source"`
			} `json:"marketplaceSource"`
		} `json:"marketplaces"`
	}
	if json.Unmarshal(output, &payload) != nil {
		return false
	}
	for _, marketplace := range payload.Marketplaces {
		if marketplace.Name != "personal" {
			continue
		}
		source := strings.ToLower(strings.TrimSuffix(marketplace.Source.Source, ".git"))
		source = strings.TrimPrefix(source, "git@github.com:")
		source = strings.TrimPrefix(source, "https://github.com/")
		source = strings.TrimPrefix(source, "http://github.com/")
		return source == "erd0s/mindmap"
	}
	return false
}

func showIntegrations(arguments []string) error {
	flags := flag.NewFlagSet("mindmap integrations", flag.ContinueOnError)
	jsonOutput := flags.Bool("json", false, "emit JSON")
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	statuses := integrationStatuses()
	if *jsonOutput {
		return printJSON(statuses)
	}
	for _, status := range statuses {
		state := "missing"
		if status.Available {
			state = "ready to set up"
		}
		if status.Current && !status.Legacy {
			state = "installed"
		} else if status.Installed || status.Legacy {
			state = "needs update"
		}
		fmt.Printf("%-7s %-16s %s\n", status.Host, state, status.Detail)
	}
	return nil
}

func setupIntegrations(arguments []string) error {
	flags := flag.NewFlagSet("mindmap setup", flag.ContinueOnError)
	all := flags.Bool("all", false, "set up every agent currently installed")
	dryRun := flags.Bool("dry-run", false, "print commands without running them")
	refresh := flags.Bool("refresh", false, "refresh the marketplace and update an existing plugin")
	source := flags.String("source", marketplaceSource, "GitHub marketplace source")
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if runtime.GOOS != "darwin" && runtime.GOOS != "linux" {
		return errors.New("agent integrations are available on macOS and Linux in this release")
	}
	pythonPath, pythonOK, pythonDetail := inspectPythonRuntime()
	if !pythonOK {
		return fmt.Errorf("agent integrations require Python 3.10 or later: %s", pythonDetail)
	}
	hosts := flags.Args()
	if *all || len(hosts) == 0 {
		hosts = nil
		for _, host := range []string{"codex", "claude"} {
			if _, err := exec.LookPath(host); err == nil {
				hosts = append(hosts, host)
			}
		}
	}
	selectedHosts := make([]string, 0, len(hosts))
	seen := make(map[string]bool)
	for _, host := range hosts {
		host = strings.ToLower(host)
		if host != "codex" && host != "claude" {
			return fmt.Errorf("unsupported integration %q; use codex or claude", host)
		}
		if !seen[host] {
			seen[host] = true
			selectedHosts = append(selectedHosts, host)
		}
	}
	if !*dryRun {
		if err := rememberPythonRuntime(pythonPath); err != nil {
			return fmt.Errorf("save Python runtime for desktop agent hooks: %w", err)
		}
	}
	if len(selectedHosts) == 0 {
		if *dryRun {
			return errors.New("no supported agent is installed; rerun after installing Codex or Claude Code")
		}
		return errors.New("no supported agent is installed; saved the Python hook runtime; rerun after installing Codex or Claude Code")
	}
	for _, host := range selectedHosts {
		if err := setupIntegration(host, *source, *dryRun, *refresh); err != nil {
			return err
		}
	}
	return nil
}

func setupIntegration(host, source string, dryRun, refresh bool) error {
	path, err := exec.LookPath(host)
	if err != nil {
		return fmt.Errorf("%s is not installed; install it, then rerun mindmap setup %s", host, host)
	}
	status := inspectIntegration(host)
	if status.CheckFailed {
		return fmt.Errorf("inspect %s integration: %s", host, status.Detail)
	}
	if status.Current && !status.Legacy && !refresh {
		fmt.Printf("%s: Mindmap is already installed.\n", host)
		return nil
	}
	commands, err := integrationSetupCommands(host, source, status, refresh)
	if err != nil {
		return err
	}
	for _, arguments := range commands {
		fmt.Printf("%s %s\n", host, strings.Join(arguments, " "))
		if dryRun {
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		output, runErr := exec.CommandContext(ctx, path, arguments...).CombinedOutput()
		cancel()
		text := strings.TrimSpace(string(output))
		if runErr != nil && !strings.Contains(strings.ToLower(text), "already") {
			return fmt.Errorf("set up %s: %w%s", host, runErr, outputSuffix(text))
		}
		if text != "" {
			fmt.Println(text)
		}
	}
	action := "installed"
	if status.Installed || status.Legacy {
		action = "updated"
	}
	fmt.Printf("%s: %s. Restart the desktop app or begin a new CLI session.\n", host, action)
	return nil
}

func integrationSetupCommands(host, source string, status integrationStatus, refresh bool) ([][]string, error) {
	var commands [][]string
	if status.Legacy && host == "codex" {
		if !status.LegacyMarketplaceOwned {
			return nil, errors.New("refusing to remove mindmap@personal because the personal marketplace is not a verified erd0s/mindmap source; remove it manually if it belongs to an old Mindmap installation")
		}
		commands = append(commands, []string{"plugin", "remove", "mindmap@personal"})
		commands = append(commands, []string{"plugin", "marketplace", "remove", "personal"})
	}
	if status.Installed {
		if host == "codex" {
			commands = append(commands,
				[]string{"plugin", "marketplace", "upgrade", marketplaceName},
				[]string{"plugin", "remove", "mindmap@" + marketplaceName},
				[]string{"plugin", "add", "mindmap@" + marketplaceName},
			)
		} else {
			commands = append(commands, []string{"plugin", "marketplace", "update", marketplaceName})
			if refresh {
				// Claude's update command is a no-op when the manifest version is
				// unchanged, even if the marketplace package contents changed. A
				// forced refresh must therefore reinstall while preserving plugin data.
				commands = append(commands,
					[]string{"plugin", "uninstall", "mindmap@" + marketplaceName, "--scope", "user", "--keep-data", "--yes"},
					[]string{"plugin", "install", "mindmap@" + marketplaceName, "--scope", "user", "--yes"},
				)
			} else {
				commands = append(commands,
					[]string{"plugin", "update", "mindmap@" + marketplaceName, "--scope", "user", "--yes"},
				)
			}
		}
	} else {
		commands = append(commands, []string{"plugin", "marketplace", "add", source})
		if host == "codex" {
			commands = append(commands, []string{"plugin", "add", "mindmap@" + marketplaceName})
		} else {
			commands = append(commands, []string{"plugin", "install", "mindmap@" + marketplaceName, "--scope", "user", "--yes"})
		}
	}
	return commands, nil
}

func doctor(arguments []string) error {
	flags := flag.NewFlagSet("mindmap doctor", flag.ContinueOnError)
	database := databaseFlag(flags)
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	type check struct{ name, state, detail string }
	checks := make([]check, 0)
	if repository, err := store.OpenExisting(*database); err != nil {
		checks = append(checks, check{"database", "warn", err.Error()})
	} else {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		healthErr := repository.Health(ctx)
		projects, projectErr := repository.Projects(ctx)
		cancel()
		repository.Close()
		if healthErr != nil {
			checks = append(checks, check{"database", "fail", healthErr.Error()})
		} else if projectErr != nil {
			checks = append(checks, check{"database", "fail", projectErr.Error()})
		} else {
			checks = append(checks, check{"database", "ok", fmt.Sprintf("%s (%d projects)", *database, len(projects))})
		}
	}
	term := strings.TrimSpace(getenv("TERM"))
	if term == "" || term == "dumb" {
		detail := "TERM=" + term + "; limited terminal"
		if term == "dumb" {
			detail += "; viewer prints a static ASCII snapshot"
		}
		checks = append(checks, check{"terminal", "warn", detail})
	} else {
		detail := "TERM=" + term
		if getenv("TMUX") != "" {
			detail += "; tmux detected"
		}
		checks = append(checks, check{"terminal", "ok", detail})
	}
	pythonOK, pythonDetail := inspectPython()
	pythonState := "warn"
	if pythonOK {
		pythonState = "ok"
	}
	checks = append(checks, check{"python", pythonState, pythonDetail})
	for _, integration := range integrationStatuses() {
		state := "warn"
		if integration.Installed {
			state = "ok"
		}
		checks = append(checks, check{integration.Host, state, integration.Detail})
	}
	if runtime.GOOS == "darwin" {
		if output, err := exec.Command("mdfind", "kMDItemCFBundleIdentifier == 'io.github.erd0s.mindmap'").Output(); err == nil && strings.TrimSpace(string(output)) != "" {
			checks = append(checks, check{"desktop", "ok", "Mindmap.app found"})
		} else {
			checks = append(checks, check{"desktop", "warn", "Mindmap.app not found"})
		}
	} else {
		checks = append(checks, check{"desktop", "info", "macOS-only in this release"})
	}
	order := map[string]int{"fail": 0, "warn": 1, "info": 2, "ok": 3}
	sort.SliceStable(checks, func(i, j int) bool { return order[checks[i].state] < order[checks[j].state] })
	failed := false
	for _, result := range checks {
		fmt.Printf("[%-4s] %-10s %s\n", result.state, result.name, result.detail)
		failed = failed || result.state == "fail"
	}
	if failed {
		return errors.New("one or more checks failed")
	}
	return nil
}

func inspectPython() (bool, string) {
	_, ok, detail := inspectPythonRuntime()
	return ok, detail
}

func inspectPythonRuntime() (string, bool, string) {
	path := strings.TrimSpace(os.Getenv("MINDMAP_PYTHON"))
	if path == "" {
		path = "python3"
	}
	resolved, err := exec.LookPath(path)
	if err != nil {
		return "", false, path + " not found; required only for Codex and Claude integration"
	}
	path, err = filepath.Abs(resolved)
	if err != nil {
		return "", false, "unable to resolve python3: " + err.Error()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	output, err := exec.CommandContext(ctx, path, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").CombinedOutput()
	if err != nil {
		return "", false, "unable to run python3: " + strings.TrimSpace(string(output))
	}
	version := strings.TrimSpace(string(output))
	var major, minor int
	if _, err := fmt.Sscanf(version, "%d.%d", &major, &minor); err != nil {
		return "", false, "unrecognized python3 version " + version
	}
	if major < 3 || major == 3 && minor < 10 {
		return "", false, "python3 " + version + " found; 3.10 or later is required for agent integration"
	}
	runtimeOutput, err := exec.CommandContext(ctx, path, "-S", "-c", "import os, sys; print(os.path.realpath(sys.executable))").CombinedOutput()
	if err != nil {
		return "", false, "unable to resolve the Python runtime: " + strings.TrimSpace(string(runtimeOutput))
	}
	runtimePath := strings.TrimSpace(string(runtimeOutput))
	if !filepath.IsAbs(runtimePath) || strings.ContainsAny(runtimePath, "\r\n") {
		return "", false, "Python reported an invalid runtime path " + runtimePath
	}
	return filepath.Clean(runtimePath), true, "python3 " + version + " (agent hook runtime)"
}

func pythonRuntimeConfigPath() (string, error) {
	directory, err := os.UserConfigDir()
	if err != nil {
		return "", fmt.Errorf("find user configuration directory: %w", err)
	}
	return filepath.Join(directory, "mindmap", "python-path"), nil
}

func rememberPythonRuntime(path string) error {
	target, err := pythonRuntimeConfigPath()
	if err != nil {
		return err
	}
	directory := filepath.Dir(target)
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return err
	}
	temporary, err := os.CreateTemp(directory, ".python-path-*")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := fmt.Fprintln(temporary, path); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return os.Rename(temporaryPath, target)
}

func outputSuffix(value string) string {
	if value == "" {
		return ""
	}
	return ": " + value
}

func getenv(name string) string {
	return os.Getenv(name)
}
