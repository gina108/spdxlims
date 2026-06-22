// Package orderfile writes instrument order files (the CM250 `.ANA` worklist
// files dropped in Z:\Pedidos) and retires them once a result comes back.
//
// The order file is named by the order/sample number — optionally followed by
// the patient name for staff readability (`<order> <name>.ANA`). That same
// order number is field 0 of the result record, so reconciliation is a direct
// order-number lookup — no folder diffing required.
package orderfile

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Config describes where an instrument's order files live, how to retire them
// after a result is stored, and whether to write them on order push. It is
// populated from a profile's orders block.
type Config struct {
	Directory       string // folder holding the order files (e.g. Z:\Pedidos)
	FileExtension   string // order file extension, e.g. ".ANA"
	WriteOnPush     bool   // write an order file when the LIMS pushes an order
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

// matchesOrder reports whether a file base name (without extension) belongs to
// the given order number: either exactly `<order>` or `<order> <patient name>`.
func matchesOrder(base, order string) bool {
	return base == order || strings.HasPrefix(base, order+" ")
}

// ArchiveResult retires the order file for sampleID after its result is stored.
//
// It finds the file by order-number prefix (so `2006196 Rosa Mendoza.ANA`
// matches order 2006196) and moves it into the archive subfolder with a
// timestamp prefix. Returns the archive path on success, or "" when there is
// nothing to do (archiving disabled, no directory configured, or no matching
// file). A file the analyzer still holds open (locked) yields a non-nil error;
// callers must treat archiving as best-effort and not fail result processing on
// it — a later result or run retries.
func ArchiveResult(cfg Config, sampleID string) (string, error) {
	sampleID = strings.TrimSpace(sampleID)
	if sampleID == "" || !cfg.ArchiveOnResult || strings.TrimSpace(cfg.Directory) == "" {
		return "", nil
	}

	ext := cfg.normExt()
	entries, err := os.ReadDir(cfg.Directory)
	if err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", err
	}

	matches := make([]string, 0, 1)
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if ext != "" && !strings.EqualFold(filepath.Ext(name), ext) {
			continue
		}
		if matchesOrder(strings.TrimSuffix(name, filepath.Ext(name)), sampleID) {
			matches = append(matches, name)
		}
	}
	if len(matches) == 0 {
		return "", nil // order file already retired; nothing to do
	}

	archiveDir := strings.TrimSpace(cfg.ArchiveDir)
	if archiveDir == "" {
		archiveDir = filepath.Join(cfg.Directory, "archive")
	}
	if err := os.MkdirAll(archiveDir, 0o755); err != nil {
		return "", err
	}

	stamp := time.Now().Format("20060102-150405")
	var firstDst string
	var firstErr error
	for _, name := range matches {
		src := filepath.Join(cfg.Directory, name)
		// Timestamp prefix keeps an audit trail and avoids clobbering a prior
		// archived file when an order number is reused on a later day.
		dst := filepath.Join(archiveDir, stamp+"_"+name)
		if err := os.Rename(src, dst); err != nil {
			// On Windows the analyzer may still hold the .ANA open (locked);
			// surface the error so the caller can log it and retry later.
			if firstErr == nil {
				firstErr = fmt.Errorf("archive order file %s: %w", src, err)
			}
			continue
		}
		if firstDst == "" {
			firstDst = dst
		}
	}
	return firstDst, firstErr
}
