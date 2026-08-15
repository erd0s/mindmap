package main

import (
	"embed"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"os"
	"os/exec"
	"runtime"
	"strings"

	"github.com/wailsapp/wails/v3/pkg/application"
)

//go:embed all:frontend/dist
var bundledFrontend embed.FS

var version = "dev"

func main() {
	if err := run(); err != nil {
		log.Print(err)
		showStartupError(err)
		os.Exit(1)
	}
}

func run() error {
	flags := flag.NewFlagSet("Mindmap", flag.ContinueOnError)
	projectRoot := flags.String("project-root", "", "open the project containing this path")
	showVersion := flags.Bool("version", false, "print version and exit")
	if err := flags.Parse(os.Args[1:]); err != nil {
		return err
	}
	if *showVersion {
		fmt.Println(version)
		return nil
	}
	assets, err := fs.Sub(bundledFrontend, "frontend/dist")
	if err != nil {
		return fmt.Errorf("load frontend assets: %w", err)
	}
	service, err := NewDesktopService()
	if err != nil {
		return err
	}
	defer service.Close()
	var app *application.App
	app = application.New(application.Options{
		Name:        "Mindmap",
		Description: "A small causal map of the work in each coding project.",
		Services: []application.Service{
			application.NewService(service),
		},
		Assets: application.AssetOptions{
			Handler: application.BundledAssetFileServer(assets),
		},
		Mac: application.MacOptions{
			ApplicationShouldTerminateAfterLastWindowClosed: true,
		},
		SingleInstance: &application.SingleInstanceOptions{
			UniqueID: "io.github.erd0s.mindmap",
			OnSecondInstanceLaunch: func(data application.SecondInstanceData) {
				root := projectRootArgument(data.Args)
				if root == "" {
					service.NewPickerWindow()
					return
				}
				if err := service.NewWindowForRoot(root); err != nil && app != nil {
					app.Logger.Error("Unable to open requested project", "root", root, "error", err)
				}
			},
		},
	})
	service.SetApplication(app)
	if *projectRoot == "" {
		service.NewPickerWindow()
	} else if err := service.NewWindowForRoot(*projectRoot); err != nil {
		service.NewPickerWindow()
		app.Logger.Error("Unable to open requested project", "error", err)
	}
	return app.Run()
}

func projectRootArgument(arguments []string) string {
	for index, argument := range arguments {
		if argument == "--project-root" && index+1 < len(arguments) {
			return arguments[index+1]
		}
		if strings.HasPrefix(argument, "--project-root=") {
			return strings.TrimPrefix(argument, "--project-root=")
		}
	}
	return ""
}

func showStartupError(err error) {
	if err == nil || runtime.GOOS != "darwin" {
		return
	}
	script := `display alert "Mindmap could not start" message (item 1 of argv) as critical`
	_ = exec.Command("osascript", "-e", script, "--", err.Error()).Run()
}
