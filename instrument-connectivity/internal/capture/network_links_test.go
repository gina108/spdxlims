package capture

import (
	"path/filepath"
	"testing"
	"time"

	"instrument-connectivity/internal/models"
)

func TestPreviewAndMergeNetworkLinks(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(filepath.Join(dir, "runtime.db"), filepath.Join(dir, "captures"))
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	defer store.Close()

	now := time.Now().UTC()
	if err := store.UpsertNetworkDeviceLinks([]models.NetworkDeviceLink{{
		NetworkDeviceID: "net:10.0.0.10",
		ProfileID:       "generic-hl7",
		RuntimeDeviceID: "analyzer-a",
		Source:          "manual_override",
		Confidence:      0.98,
		SeenCount:       1,
		FirstSeen:       now,
		LastSeen:        now,
	}}); err != nil {
		t.Fatalf("UpsertNetworkDeviceLinks() error = %v", err)
	}

	preview, err := store.PreviewNetworkLinkImport([]models.NetworkDeviceLink{{
		NetworkDeviceID: "net:10.0.0.20",
		ProfileID:       "generic-hl7",
		RuntimeDeviceID: "analyzer-a",
		Source:          "manual_import",
		Confidence:      0.99,
		SeenCount:       1,
		FirstSeen:       now,
		LastSeen:        now,
	}})
	if err != nil {
		t.Fatalf("PreviewNetworkLinkImport() error = %v", err)
	}
	if len(preview.Conflicts) != 1 {
		t.Fatalf("len(Conflicts) = %d, want 1", len(preview.Conflicts))
	}
	if preview.Conflicts[0].Type != "runtime_claimed_elsewhere" {
		t.Fatalf("conflict type = %q", preview.Conflicts[0].Type)
	}
	if preview.Diagnostics.TotalLinks != 1 || preview.Diagnostics.ManualLinks != 1 {
		t.Fatalf("diagnostics = %#v", preview.Diagnostics)
	}

	if err := store.ApplyNetworkLinkMerge(models.NetworkDeviceLink{
		NetworkDeviceID: "net:10.0.0.20",
		ProfileID:       "generic-hl7",
		RuntimeDeviceID: "analyzer-a",
		Source:          "manual_import",
		Confidence:      0.99,
		SeenCount:       1,
		FirstSeen:       now,
		LastSeen:        now,
	}); err != nil {
		t.Fatalf("ApplyNetworkLinkMerge() error = %v", err)
	}

	links, err := store.ListAllNetworkDeviceLinks()
	if err != nil {
		t.Fatalf("ListAllNetworkDeviceLinks() error = %v", err)
	}
	if len(links) != 1 {
		t.Fatalf("len(links) = %d, want 1", len(links))
	}
	if links[0].NetworkDeviceID != "net:10.0.0.20" {
		t.Fatalf("merged link device = %q, want %q", links[0].NetworkDeviceID, "net:10.0.0.20")
	}
}
