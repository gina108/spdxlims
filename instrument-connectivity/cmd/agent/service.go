package main

import (
	"strconv"

	"instrument-connectivity/internal/config"
)

type windowsServiceOptions struct {
	Name        string
	DisplayName string
	Description string
	Args        []string
}

func buildServiceArgs(cfg config.Config) []string {
	args := []string{
		"-data-dir", cfg.DataDir,
		"-listen", cfg.ListenAddr,
		"-retention-days", strconv.Itoa(cfg.RetentionDays),
		"-session-event-max", strconv.Itoa(cfg.SessionEventMax),
		"-runtime-error-max", strconv.Itoa(cfg.RuntimeErrorMax),
		"-capture-max", strconv.Itoa(cfg.CaptureMax),
		"-cleanup-interval", cfg.CleanupInterval.String(),
	}
	if cfg.APIAuthToken != "" {
		args = append(args, "-api-token", cfg.APIAuthToken)
	}
	return args
}
