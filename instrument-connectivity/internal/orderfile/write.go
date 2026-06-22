package orderfile

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// OrderRecord is one order to write as a CM250 `.ANA` worklist file.
type OrderRecord struct {
	OrderNumber string   // becomes field 0 and the filename stem
	PatientName string   // field 2, and appended to the filename when present
	Date        string   // MM/DD/YY; defaults to today
	Time        string   // HH:MM:SS; defaults to 00:00:00
	TestCodes   []string // instrument codes (e.g. "GLU L"), already mapped from LIS codes
}

// invalidFileChars are characters not allowed in Windows file names.
const invalidFileChars = `\/:*?"<>|`

// sanitizeFilePart strips characters that are illegal in a Windows filename and
// collapses surrounding whitespace, so a patient name can be embedded safely.
func sanitizeFilePart(s string) string {
	s = strings.TrimSpace(s)
	var b strings.Builder
	for _, r := range s {
		if strings.ContainsRune(invalidFileChars, r) {
			continue
		}
		b.WriteRune(r)
	}
	return strings.TrimSpace(b.String())
}

// padRight left-justifies s to at least width columns with spaces. Strings
// already at or beyond width are returned unchanged.
func padRight(s string, width int) string {
	if len(s) >= width {
		return s
	}
	return s + strings.Repeat(" ", width-len(s))
}

// formatOrderLine renders the confirmed CM250 import grammar:
//
//	OrderNumber;Flag;PatientName;<blank>;<blank>;<blank>;Date;Time;CODE1;CODE2;...
//
// Critically it has NO status/test-count fields (those exist only in the export)
// and NO trailing empty field — a dangling empty field is read by the analyzer
// as an empty test code and silently defaults to ALB.
func formatOrderLine(rec OrderRecord) string {
	date := strings.TrimSpace(rec.Date)
	if date == "" {
		date = time.Now().Format("01/02/06")
	}
	tm := strings.TrimSpace(rec.Time)
	if tm == "" {
		tm = "00:00:00"
	}

	var sb strings.Builder
	sb.WriteString(padRight(strings.TrimSpace(rec.OrderNumber), 10))
	sb.WriteString(";N;")
	sb.WriteString(padRight(strings.TrimSpace(rec.PatientName), 20))
	// Three blank header fields (widths 12/3/1) that sit between the patient
	// name and the date in the analyzer's layout.
	sb.WriteString(";")
	sb.WriteString(strings.Repeat(" ", 12))
	sb.WriteString(";")
	sb.WriteString(strings.Repeat(" ", 3))
	sb.WriteString("; ;")
	sb.WriteString(date)
	sb.WriteString(";")
	sb.WriteString(tm)
	sb.WriteString(";")
	for i, c := range rec.TestCodes {
		if i > 0 {
			sb.WriteString(";")
		}
		sb.WriteString(padRight(strings.TrimSpace(c), 6))
	}
	return sb.String()
}

// OrderFileName returns the file name for an order: `<order> <patient>.ANA`,
// or `<order>.ANA` when no usable patient name is present.
func OrderFileName(cfg Config, rec OrderRecord) string {
	stem := strings.TrimSpace(rec.OrderNumber)
	if pn := sanitizeFilePart(rec.PatientName); pn != "" {
		stem = stem + " " + pn
	}
	return stem + cfg.normExt()
}

// WriteOrder writes a single-order `.ANA` file into cfg.Directory using the
// confirmed CM250 import grammar, returning the path written. It overwrites any
// existing file for the same name (the analyzer releases its lock after import,
// so a re-pushed order can be rewritten).
func WriteOrder(cfg Config, rec OrderRecord) (string, error) {
	if strings.TrimSpace(rec.OrderNumber) == "" {
		return "", fmt.Errorf("order number is required")
	}
	if strings.TrimSpace(cfg.Directory) == "" {
		return "", fmt.Errorf("orders directory not configured")
	}
	if err := os.MkdirAll(cfg.Directory, 0o755); err != nil {
		return "", err
	}
	path := filepath.Join(cfg.Directory, OrderFileName(cfg, rec))
	// ASCII, CRLF, no BOM — matches what the analyzer accepts.
	if err := os.WriteFile(path, []byte(formatOrderLine(rec)+"\r\n"), 0o644); err != nil {
		return "", err
	}
	return path, nil
}
