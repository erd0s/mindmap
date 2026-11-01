package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseCodexIntegrationUsesExactPluginIDAndVersion(t *testing.T) {
	original := version
	version = "0.3.0"
	t.Cleanup(func() { version = original })

	tests := []struct {
		name               string
		payload            string
		installed, current bool
		legacy             bool
	}{
		{
			name:      "current",
			payload:   `{"installed":[{"pluginId":"mindmap@erd0s-mindmap","name":"mindmap","marketplaceName":"erd0s-mindmap","version":"0.3.0"}]}`,
			installed: true, current: true,
		},
		{
			name:      "outdated",
			payload:   `{"installed":[{"pluginId":"mindmap@erd0s-mindmap","name":"mindmap","marketplaceName":"erd0s-mindmap","version":"0.2.1"}]}`,
			installed: true,
		},
		{
			name:    "legacy private marketplace",
			payload: `{"installed":[{"pluginId":"mindmap@personal","name":"mindmap","marketplaceName":"personal","version":"0.2.2"}]}`,
			legacy:  true,
		},
		{
			name:    "unrelated text in another plugin",
			payload: `{"installed":[{"pluginId":"mindmap-helper@tools","name":"mindmap helper","marketplaceName":"tools","version":"1.0.0"}]}`,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			status, err := parseIntegrationStatus("codex", []byte(test.payload))
			if err != nil {
				t.Fatal(err)
			}
			if status.Installed != test.installed || status.Current != test.current || status.Legacy != test.legacy {
				t.Fatalf("status = %#v", status)
			}
		})
	}
}

func TestParseClaudeIntegrationUsesExactPluginID(t *testing.T) {
	original := version
	version = "0.3.0"
	t.Cleanup(func() { version = original })
	status, err := parseIntegrationStatus("claude", []byte(`[
		{"id":"mindmap-helper@elsewhere","version":"9.0.0"},
		{"id":"mindmap@erd0s-mindmap","version":"0.3.0"}
	]`))
	if err != nil {
		t.Fatal(err)
	}
	if !status.Installed || !status.Current || status.PluginID != "mindmap@erd0s-mindmap" {
		t.Fatalf("status = %#v", status)
	}
}

func TestLegacyMarketplaceRemovalRequiresMindmapSource(t *testing.T) {
	mindmap := []byte(`{"marketplaces":[{"name":"personal","marketplaceSource":{"source":"git@github.com:erd0s/mindmap.git"}}]}`)
	unrelated := []byte(`{"marketplaces":[{"name":"personal","marketplaceSource":{"source":"git@github.com:someone/other.git"}}]}`)
	if !legacyMarketplaceIsMindmap(mindmap) {
		t.Fatal("Mindmap's legacy marketplace was not recognized")
	}
	if legacyMarketplaceIsMindmap(unrelated) {
		t.Fatal("an unrelated personal marketplace must never be removed")
	}
}

func TestMindmapLocalMarketplaceDetection(t *testing.T) {
	codexLocal := []byte(`{"marketplaces":[{"name":"erd0s-mindmap","marketplaceSource":{"sourceType":"local","source":"/tmp/mindmap"}}]}`)
	codexGit := []byte(`{"marketplaces":[{"name":"erd0s-mindmap","marketplaceSource":{"sourceType":"git","source":"https://github.com/erd0s/mindmap.git"}}]}`)
	claudeLocal := []byte(`[{"name":"erd0s-mindmap","source":"directory","path":"/tmp/mindmap"}]`)
	claudeGit := []byte(`[{"name":"erd0s-mindmap","source":"github","repo":"erd0s/mindmap"}]`)

	for _, test := range []struct {
		name, host string
		payload    []byte
		want       bool
	}{
		{"codex local", "codex", codexLocal, true},
		{"codex git", "codex", codexGit, false},
		{"claude local", "claude", claudeLocal, true},
		{"claude git", "claude", claudeGit, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			got, err := mindmapMarketplaceIsLocal(test.host, test.payload)
			if err != nil {
				t.Fatal(err)
			}
			if got != test.want {
				t.Fatalf("local = %v, want %v", got, test.want)
			}
		})
	}
}

func TestSetupAndRefreshCannotTouchClientsOrData(t *testing.T) {
	home := t.TempDir()
	bin := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_CONFIG_HOME", home)
	t.Setenv("CODEX_HOME", filepath.Join(home, ".codex"))
	t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(home, ".claude"))
	t.Setenv("MINDMAP_DATA_DIR", filepath.Join(home, "data"))
	t.Setenv("PATH", bin)
	for _, name := range []string{"codex", "claude", "python3"} {
		if err := os.WriteFile(filepath.Join(bin, name), []byte("#!/bin/sh\necho invoked >> \"$HOME/client-invoked\"\nexit 97\n"), 0700); err != nil {
			t.Fatal(err)
		}
	}
	sentinel := filepath.Join(home, "existing-data")
	if err := os.WriteFile(sentinel, []byte("retained maps, transcripts and credentials"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"setup"}, {"setup", "codex"}, {"setup", "claude"}, {"setup", "--all"},
		{"setup", "--refresh", "--all"}, {"setup", "--refresh", "claude"},
		{"setup", "--dry-run", "--all"}, {"setup", "--source", "somewhere/else", "codex"},
	} {
		err := run(args)
		if err == nil || !strings.Contains(err.Error(), "integration is paused") {
			t.Fatalf("%v: %v", args, err)
		}
	}
	entries, err := os.ReadDir(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != "existing-data" {
		t.Fatalf("setup changed client home: %v", entries)
	}
	content, err := os.ReadFile(sentinel)
	if err != nil || string(content) != "retained maps, transcripts and credentials" {
		t.Fatalf("existing data changed: %s, %v", content, err)
	}
}
