package orderfile

import (
	"os"
	"path/filepath"
	"testing"
)

func writeOrderFile(t *testing.T, dir, name string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte("order data\r\n"), 0o644); err != nil {
		t.Fatalf("write %s: %v", p, err)
	}
	return p
}

func TestArchiveResultMovesFile(t *testing.T) {
	dir := t.TempDir()
	src := writeOrderFile(t, dir, "2006171.ANA")

	cfg := Config{Directory: dir, FileExtension: ".ANA", ArchiveOnResult: true}
	dst, err := ArchiveResult(cfg, "2006171")
	if err != nil {
		t.Fatalf("ArchiveResult: %v", err)
	}
	if dst == "" {
		t.Fatal("expected an archive path, got empty")
	}
	if _, err := os.Stat(src); !os.IsNotExist(err) {
		t.Fatalf("source file should be gone, stat err=%v", err)
	}
	if _, err := os.Stat(dst); err != nil {
		t.Fatalf("archived file missing: %v", err)
	}
	if filepath.Dir(dst) != filepath.Join(dir, "archive") {
		t.Fatalf("expected default archive subdir, got %s", filepath.Dir(dst))
	}
}

func TestArchiveResultExtensionOptionalDot(t *testing.T) {
	dir := t.TempDir()
	writeOrderFile(t, dir, "555.ANA")
	// Extension configured without a leading dot must still match.
	dst, err := ArchiveResult(Config{Directory: dir, FileExtension: "ANA", ArchiveOnResult: true}, "555")
	if err != nil {
		t.Fatalf("ArchiveResult: %v", err)
	}
	if dst == "" {
		t.Fatal("expected file to be archived when extension lacks leading dot")
	}
}

func TestArchiveResultNoopCases(t *testing.T) {
	dir := t.TempDir()
	writeOrderFile(t, dir, "2006171.ANA")

	cases := []struct {
		name string
		cfg  Config
		sid  string
	}{
		{"disabled", Config{Directory: dir, FileExtension: ".ANA", ArchiveOnResult: false}, "2006171"},
		{"no directory", Config{FileExtension: ".ANA", ArchiveOnResult: true}, "2006171"},
		{"empty sample", Config{Directory: dir, FileExtension: ".ANA", ArchiveOnResult: true}, "  "},
		{"missing file", Config{Directory: dir, FileExtension: ".ANA", ArchiveOnResult: true}, "9999999"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dst, err := ArchiveResult(tc.cfg, tc.sid)
			if err != nil {
				t.Fatalf("expected no error, got %v", err)
			}
			if dst != "" {
				t.Fatalf("expected no-op (empty dst), got %s", dst)
			}
		})
	}
}
