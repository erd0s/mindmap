package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type userConfig struct {
	Color string `json:"color"`
	ASCII string `json:"ascii"`
}

func defaultConfig() userConfig { return userConfig{Color: "auto", ASCII: "auto"} }

func configPath() (string, error) {
	base := os.Getenv("XDG_CONFIG_HOME")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", fmt.Errorf("find home directory: %w", err)
		}
		base = filepath.Join(home, ".config")
	}
	return filepath.Join(base, "mindmap", "config.json"), nil
}

func loadConfig() (userConfig, error) {
	config := defaultConfig()
	path, err := configPath()
	if err != nil {
		return config, err
	}
	content, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return config, nil
	}
	if err != nil {
		return config, fmt.Errorf("read config: %w", err)
	}
	if err := json.Unmarshal(content, &config); err != nil {
		return config, fmt.Errorf("parse %s: %w", path, err)
	}
	if err := validateDisplayOptions(config.Color, config.ASCII); err != nil {
		return config, fmt.Errorf("invalid %s: %w", path, err)
	}
	return config, nil
}

func saveConfig(config userConfig) error {
	if err := validateDisplayOptions(config.Color, config.ASCII); err != nil {
		return err
	}
	path, err := configPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("create config directory: %w", err)
	}
	content, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return fmt.Errorf("encode config: %w", err)
	}
	content = append(content, '\n')
	temporary, err := os.CreateTemp(filepath.Dir(path), ".config-*.json")
	if err != nil {
		return fmt.Errorf("create temporary config: %w", err)
	}
	temporaryName := temporary.Name()
	defer os.Remove(temporaryName)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return fmt.Errorf("protect temporary config: %w", err)
	}
	if _, err := temporary.Write(content); err != nil {
		temporary.Close()
		return fmt.Errorf("write temporary config: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return fmt.Errorf("finish temporary config: %w", err)
	}
	if err := replaceFile(temporaryName, path); err != nil {
		return fmt.Errorf("replace config: %w", err)
	}
	return nil
}

func configure(arguments []string) error {
	current, err := loadConfig()
	if err != nil {
		return err
	}
	flags := flag.NewFlagSet("mindmap config", flag.ContinueOnError)
	color := flags.String("color", current.Color, "color mode: auto or none")
	ascii := flags.String("ascii", current.ASCII, "character mode: auto, always, or never")
	show := flags.Bool("show", false, "show the saved configuration without changing it")
	if err := flags.Parse(arguments); err != nil {
		return commandFlagError(err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected argument %q", flags.Arg(0))
	}
	updated := userConfig{Color: strings.ToLower(*color), ASCII: strings.ToLower(*ascii)}
	if !*show {
		if err := saveConfig(updated); err != nil {
			return err
		}
		current = updated
	}
	return printJSON(current)
}

func validateDisplayOptions(color, ascii string) error {
	if color != "auto" && color != "none" {
		return fmt.Errorf("--color must be auto or none, got %q", color)
	}
	if ascii != "auto" && ascii != "always" && ascii != "never" {
		return fmt.Errorf("--ascii must be auto, always, or never, got %q", ascii)
	}
	return nil
}

func applyDisplayOptions(color, ascii string) error {
	color, ascii = strings.ToLower(color), strings.ToLower(ascii)
	if err := validateDisplayOptions(color, ascii); err != nil {
		return err
	}
	if color == "none" {
		if err := os.Setenv("MINDMAP_COLOR", "none"); err != nil {
			return err
		}
	} else {
		_ = os.Unsetenv("MINDMAP_COLOR")
	}
	switch ascii {
	case "always":
		return os.Setenv("MINDMAP_ASCII", "always")
	case "never":
		return os.Setenv("MINDMAP_ASCII", "never")
	default:
		return os.Unsetenv("MINDMAP_ASCII")
	}
}
