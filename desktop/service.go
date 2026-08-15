package main

import (
	"context"
	"fmt"
	"net/url"
	"sync"
	"time"

	"github.com/erd0s/mindmap/internal/store"
	"github.com/wailsapp/wails/v3/pkg/application"
)

const databasePollInterval = 250 * time.Millisecond

type DesktopService struct {
	repository     *store.Repository
	app            *application.App
	mu             sync.RWMutex
	cancel         context.CancelFunc
	changeNotifier func(int64)
}

func NewDesktopService() (*DesktopService, error) {
	repository, err := store.OpenDefault(false)
	if err != nil {
		return nil, err
	}
	return &DesktopService{repository: repository}, nil
}

func (s *DesktopService) ServiceName() string { return "Mindmap" }

func (s *DesktopService) SetApplication(app *application.App) {
	s.mu.Lock()
	s.app = app
	s.mu.Unlock()
}

func (s *DesktopService) Close() error {
	if s.cancel != nil {
		s.cancel()
	}
	return s.repository.Close()
}

func (s *DesktopService) ServiceStartup(ctx context.Context, _ application.ServiceOptions) error {
	watchContext, cancel := context.WithCancel(ctx)
	s.cancel = cancel
	go s.watch(watchContext)
	return nil
}

func (s *DesktopService) Projects() ([]store.Project, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	return s.repository.Projects(ctx)
}

func (s *DesktopService) Snapshot(projectID int64) (store.Snapshot, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	return s.repository.LoadSnapshot(ctx, projectID)
}

func (s *DesktopService) DeleteSubtree(projectID int64, itemID string, confirmed []store.ItemRevision) (store.DeleteResult, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	result, err := s.repository.DeleteSubtree(ctx, projectID, itemID, confirmed)
	if err == nil {
		s.emitChanged(projectID)
	}
	return result, err
}

func (s *DesktopService) NewProjectWindow(projectID int64) error {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	snapshot, err := s.repository.LoadSnapshot(ctx, projectID)
	if err != nil {
		return err
	}
	s.newWindow("Mindmap — "+snapshot.Project.Name, "/?project="+url.QueryEscape(fmt.Sprint(projectID)))
	return nil
}

func (s *DesktopService) NewPickerWindow() {
	s.newWindow("Open Mindmap Project", "/")
}

func (s *DesktopService) NewWindowForRoot(root string) error {
	project, err := s.repository.ResolveProject(root, "")
	if err != nil {
		return err
	}
	return s.NewProjectWindow(project.ID)
}

func (s *DesktopService) newWindow(title, route string) {
	s.mu.RLock()
	app := s.app
	s.mu.RUnlock()
	if app == nil {
		return
	}
	app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title:            title,
		URL:              route,
		Width:            1180,
		Height:           760,
		MinWidth:         680,
		MinHeight:        480,
		BackgroundColour: application.NewRGB(9, 9, 11),
		Mac: application.MacWindow{
			Backdrop: application.MacBackdropTranslucent,
			TitleBar: application.MacTitleBarHiddenInsetUnified,
		},
	})
}

func (s *DesktopService) watch(ctx context.Context) {
	version, _ := s.repository.DataVersion(ctx)
	ticker := time.NewTicker(databasePollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			next, err := s.repository.DataVersion(ctx)
			if err != nil || next == version {
				continue
			}
			version = next
			s.emitChanged(0)
		}
	}
}

func (s *DesktopService) emitChanged(projectID int64) {
	s.mu.RLock()
	app := s.app
	notify := s.changeNotifier
	s.mu.RUnlock()
	if app != nil {
		app.Event.Emit("mindmap:changed", projectID)
	}
	if notify != nil {
		notify(projectID)
	}
}
