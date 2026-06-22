// Package orderfile retires instrument order files (e.g. the CM250 `.ANA`
// worklist files dropped in Z:\Pedidos) once a result comes back for the order.
// The order file is named by the order/sample number, which is also field 0 of
// the result record, so reconciliation is a direct filename lookup — no folder
// diffing required.
package orderfile

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Config describes where an instrument's order files live and how to retire
// them after a result is stored. It is populated from a profile's orders block.
type Config struct {
	Directory       string // folder holding the order files (e.g. Z:\Pedidos)
	FileExtension   string // order file extension, e.g. ".ANA"
	ArchiveOnResult bool   // move the file to ArchiveDir when the result arrives
	ArchiveDir      string // destination; defaults to <Directory>\archive
}

// normExt returns the extension with a leading dot, or "" if unset.
func (c Config) normExt() string {
	e := strings.TrimSpace(c.FileExtension)
	if e == "" {
		return ""
	}
	if !strings.HasPrefix(e, ".") {
		e = "." + e
	}
	return e
}

// ArchiveResult retires the order file for sampleID after its result is stored.
//
// It returns the archive path on success, or "" when there is nothing to do
// (archiving disabled, no directory configured, or the order file is already
// gone). A file the analyzer still holds open (locked) yields a non-nil error;
// callers should treat archiving as best-effort and must NOT fail result
// processing on it — a later result or sweep can retry.
func ArchiveResult(cfg Config, sampleID string) (string, error) {
	sampleID = strings.TrimSpace(sampleID)
	if sampleID == "" || !cfg.ArchiveOnResult || strings.TrimSpace(cfg.Directory) == "" {
		return "", nil
	}

	src := filepath.Join(cfg.Directory, sampleID+cfg.normExt())
	if _, err := os.Stat(src); err != nil {
		if os.IsNotExist(err) {
			return "", nil // order file already retired; nothing to do
		}
		return "", err
	}

	archiveDir := strings.TrimSpace(cfg.ArchiveDir)
	if archiveDir == "" {
		archiveDir = filepath.Join(cfg.Directory, "archive")
	}
	if err := os.MkdirAll(archiveDir, 0o755); err != nil {
		return "", err
	}

	// Timestamp prefix keeps an audit trail and avoids clobbering a prior
	// archived file when an order number is reused on a later day.
	dst := filepath.Join(archiveDir, fmt.Sprintf("%s_%s%s",
		time.Now().Format("20060102-150405"), sampleID, cfg.normExt()))
	if err := os.Rename(src, dst); err != nil {
		// On Windows the analyzer may still hold the .ANA open; surface the
		// error so the caller can log it and a later attempt can retry.
		return "", fmt.Errorf("archive order file %s: %w", src, err)
	}
	return dst, nil
}
