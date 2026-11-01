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
	"sort"
	"strings"
	"time"

	"github.com/erd0s/mindmap/internal/store"
)

const marketplaceName = "erd0s-mindmap"

type integrationStatus struct {
	Host                   string `json:"host"`
	Available              bool   `json:"available"`
	Installed              bool   `json:"installed"`
	Current                bool   `json:"current"`
	Legacy                 bool   `json:"legacy"`
	LegacyMarketplaceOwned bool   `json:"-"`
	LocalMarketplace       bool   `json:"-"`
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
	if parsed.Installed || parsed.Legacy {
		marketplaceOutput, marketplaceErr := exec.CommandContext(ctx, path, "plugin", "marketplace", "list", "--json").CombinedOutput()
		if marketplaceErr != nil {
			parsed.CheckFailed = true
			parsed.Detail = "marketplace check failed" + outputSuffix(strings.TrimSpace(string(marketplaceOutput)))
			return parsed
		}
		if parsed.Legacy && host == "codex" {
			parsed.LegacyMarketplaceOwned = legacyMarketplaceIsMindmap(marketplaceOutput)
		}
		local, parseErr := mindmapMarketplaceIsLocal(host, marketplaceOutput)
		if parseErr != nil {
			parsed.CheckFailed = true
			parsed.Detail = "unrecognized marketplace-list response: " + parseErr.Error()
			return parsed
		}
		parsed.LocalMarketplace = local
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

func mindmapMarketplaceIsLocal(host string, output []byte) (bool, error) {
	switch host {
	case "codex":
		var payload struct {
			Marketplaces []struct {
				Name   string `json:"name"`
				Source struct {
					Type string `json:"sourceType"`
				} `json:"marketplaceSource"`
			} `json:"marketplaces"`
		}
		if err := json.Unmarshal(output, &payload); err != nil {
			return false, err
		}
		for _, marketplace := range payload.Marketplaces {
			if marketplace.Name == marketplaceName {
				return strings.EqualFold(marketplace.Source.Type, "local"), nil
			}
		}
	case "claude":
		var payload []struct {
			Name   string `json:"name"`
			Source string `json:"source"`
		}
		if err := json.Unmarshal(output, &payload); err != nil {
			return false, err
		}
		for _, marketplace := range payload {
			if marketplace.Name == marketplaceName {
				return strings.EqualFold(marketplace.Source, "directory"), nil
			}
		}
	default:
		return false, fmt.Errorf("unsupported host %q", host)
	}
	return false, nil
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
	for i := range statuses {
		statuses[i].Detail = "integration paused; " + statuses[i].Detail
	}
	if *jsonOutput {
		return printJSON(statuses)
	}
	for _, status := range statuses {
		state := "missing"
		if status.Available {
			state = "paused"
		}
		if status.CheckFailed {
			state = "check failed"
		} else if status.Current && !status.Legacy {
			state = "installed"
		} else if status.Installed || status.Legacy {
			state = "legacy install"
		}
		fmt.Printf("%-7s %-16s %s\n", status.Host, state, status.Detail)
	}
	return nil
}

func setupIntegrations(arguments []string) error {
	return errors.New("agent integration is paused; setup and refresh are disabled pending review and an explicit installation-scope decision")
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
	checks = append(checks, check{"integration", "info", "paused; automatic capture, context injection, setup and refresh disabled"})
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

func outputSuffix(value string) string {
	if value == "" {
		return ""
	}
	return ": " + value
}

func getenv(name string) string {
	return os.Getenv(name)
}
