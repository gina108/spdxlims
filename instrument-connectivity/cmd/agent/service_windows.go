//go:build windows

package main

import (
	"fmt"
	"os"
	"time"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"

	"instrument-connectivity/internal/config"
	"instrument-connectivity/internal/runtime"
)

func runningAsWindowsService() (bool, error) {
	return svc.IsWindowsService()
}

func installWindowsService(opts windowsServiceOptions) error {
	exePath, err := os.Executable()
	if err != nil {
		return err
	}
	manager, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer manager.Disconnect()
	if existing, err := manager.OpenService(opts.Name); err == nil {
		existing.Close()
		return fmt.Errorf("service %q already exists", opts.Name)
	}
	service, err := manager.CreateService(opts.Name, exePath, mgr.Config{
		DisplayName: opts.DisplayName,
		Description: opts.Description,
		StartType:   mgr.StartAutomatic,
	}, opts.Args...)
	if err != nil {
		return err
	}
	defer service.Close()
	return nil
}

func uninstallWindowsService(name string) error {
	manager, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer manager.Disconnect()
	service, err := manager.OpenService(name)
	if err != nil {
		return err
	}
	defer service.Close()
	status, err := service.Control(svc.Stop)
	if err == nil {
		deadline := time.Now().Add(15 * time.Second)
		for status.State != svc.Stopped && time.Now().Before(deadline) {
			time.Sleep(300 * time.Millisecond)
			status, err = service.Query()
			if err != nil {
				break
			}
		}
	}
	return service.Delete()
}

func runWindowsService(name string, cfg config.Config) error {
	return svc.Run(name, &agentWindowsService{cfg: cfg})
}

type agentWindowsService struct {
	cfg config.Config
}

func (s *agentWindowsService) Execute(_ []string, requests <-chan svc.ChangeRequest, status chan<- svc.Status) (bool, uint32) {
	const accepted = svc.AcceptStop | svc.AcceptShutdown
	status <- svc.Status{State: svc.StartPending}
	app, err := runtime.New(s.cfg)
	if err != nil {
		return false, 1
	}
	if err := app.Start(); err != nil {
		_ = app.Close()
		return false, 1
	}
	status <- svc.Status{State: svc.Running, Accepts: accepted}
	for req := range requests {
		switch req.Cmd {
		case svc.Interrogate:
			status <- req.CurrentStatus
		case svc.Stop, svc.Shutdown:
			status <- svc.Status{State: svc.StopPending}
			_ = app.Close()
			_ = app.Wait()
			return false, 0
		default:
		}
	}
	_ = app.Close()
	_ = app.Wait()
	return false, 0
}
