package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestInspectPythonRuntimeResolvesInterpreterSymlink(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("python3 is not installed")
	}
	target, err := filepath.EvalSymlinks(python)
	if err != nil {
		t.Fatal(err)
	}
	shim := filepath.Join(t.TempDir(), "python3")
	if err := os.Symlink(target, shim); err != nil {
		t.Fatal(err)
	}
	t.Setenv("MINDMAP_PYTHON", shim)
	resolved, ok, detail := inspectPythonRuntime()
	if !ok {
		t.Fatal(detail)
	}
	output, err := exec.Command(target, "-S", "-c", "import os, sys; print(os.path.realpath(sys.executable))").Output()
	if err != nil {
		t.Fatal(err)
	}
	want := strings.TrimSpace(string(output))
	if resolved != want {
		t.Fatalf("resolved Python runtime = %q, want %q", resolved, want)
	}
}

func TestRememberPythonRuntimeUsesPrivateUserConfig(t *testing.T) {
	config := t.TempDir()
	t.Setenv("HOME", config)
	t.Setenv("XDG_CONFIG_HOME", config)
	path := filepath.Join(config, "bin", "python3")
	if err := rememberPythonRuntime(path); err != nil {
		t.Fatal(err)
	}
	target, err := pythonRuntimeConfigPath()
	if err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(contents) != path+"\n" {
		t.Fatalf("saved Python path = %q", contents)
	}
	info, err := os.Stat(target)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("saved Python path mode = %o", info.Mode().Perm())
	}
}

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

func TestLegacyMigrationRefusesUnverifiedPersonalMarketplace(t *testing.T) {
	_, err := integrationSetupCommands("codex", marketplaceSource, integrationStatus{Legacy: true}, false)
	if err == nil || !strings.Contains(err.Error(), "refusing to remove mindmap@personal") {
		t.Fatalf("error = %v", err)
	}
}

func TestLegacyMigrationRemovesOnlyVerifiedPersonalMarketplace(t *testing.T) {
	commands, err := integrationSetupCommands("codex", marketplaceSource, integrationStatus{
		Legacy:                 true,
		LegacyMarketplaceOwned: true,
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"plugin", "remove", "mindmap@personal"},
		{"plugin", "marketplace", "remove", "personal"},
		{"plugin", "marketplace", "add", marketplaceSource},
		{"plugin", "add", "mindmap@" + marketplaceName},
	}
	if !reflect.DeepEqual(commands, want) {
		t.Fatalf("commands = %#v, want %#v", commands, want)
	}
}

func TestClaudeRefreshReinstallsSameVersionAndPreservesPluginData(t *testing.T) {
	commands, err := integrationSetupCommands("claude", marketplaceSource, integrationStatus{
		Installed: true,
		Current:   true,
	}, true)
	if err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"plugin", "marketplace", "update", marketplaceName},
		{"plugin", "uninstall", "mindmap@" + marketplaceName, "--scope", "user", "--keep-data", "--yes"},
		{"plugin", "install", "mindmap@" + marketplaceName, "--scope", "user", "--yes"},
	}
	if !reflect.DeepEqual(commands, want) {
		t.Fatalf("commands = %#v, want %#v", commands, want)
	}
}

func TestClaudeOrdinaryUpgradeUsesUpdate(t *testing.T) {
	commands, err := integrationSetupCommands("claude", marketplaceSource, integrationStatus{
		Installed: true,
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"plugin", "marketplace", "update", marketplaceName},
		{"plugin", "update", "mindmap@" + marketplaceName, "--scope", "user", "--yes"},
	}
	if !reflect.DeepEqual(commands, want) {
		t.Fatalf("commands = %#v, want %#v", commands, want)
	}
}

func TestCodexLocalMarketplaceIsReplacedBeforePublicInstall(t *testing.T) {
	commands, err := integrationSetupCommands("codex", marketplaceSource, integrationStatus{
		Installed:        true,
		LocalMarketplace: true,
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"plugin", "remove", "mindmap@" + marketplaceName},
		{"plugin", "marketplace", "remove", marketplaceName},
		{"plugin", "marketplace", "add", marketplaceSource},
		{"plugin", "add", "mindmap@" + marketplaceName},
	}
	if !reflect.DeepEqual(commands, want) {
		t.Fatalf("commands = %#v, want %#v", commands, want)
	}
}

func TestClaudeLocalMarketplaceIsReplacedAndDataIsPreserved(t *testing.T) {
	commands, err := integrationSetupCommands("claude", marketplaceSource, integrationStatus{
		Installed:        true,
		LocalMarketplace: true,
	}, false)
	if err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"plugin", "uninstall", "mindmap@" + marketplaceName, "--scope", "user", "--keep-data", "--yes"},
		{"plugin", "marketplace", "remove", marketplaceName, "--scope", "user"},
		{"plugin", "marketplace", "add", marketplaceSource},
		{"plugin", "install", "mindmap@" + marketplaceName, "--scope", "user", "--yes"},
	}
	if !reflect.DeepEqual(commands, want) {
		t.Fatalf("commands = %#v, want %#v", commands, want)
	}
}
