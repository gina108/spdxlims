//go:build !windows

package main

import (
	"errors"

	"instrument-connectivity/internal/config"
)

func runningAsWindowsService() (bool, error) {
	return false, nil
}

func installWindowsService(opts windowsServiceOptions) error {
	return errors.New("Windows service installation is only supported on Windows")
}

func uninstallWindowsService(name string) error {
	return errors.New("Windows service uninstallation is only supported on Windows")
}

func runWindowsService(name string, cfg config.Config) error {
	return errors.New("Windows service runtime is only supported on Windows")
}
