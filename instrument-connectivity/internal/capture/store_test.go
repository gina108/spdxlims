package capture

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"instrument-connectivity/internal/models"
)

func TestMaintenanceStatusRoundTrip(t *testing.T) {
	store := openTestStore(t)
	defer store.Close()

	executedAt := time.Date(2026, 3, 22, 18, 0, 0, 0, time.UTC)
	nextCleanupAt := executedAt.Add(6 * time.Hour)
	report := CleanupReport{
		Policy: RetentionPolicy{
			RetentionDays:   30,
			SessionEventMax: 5000,
			RuntimeErrorMax: 2000,
			CaptureMax:      2000,
		},
		DeletedCaptures:      3,
		DeletedCaptureFiles:  2,
		DeletedRuntimeErrors: 5,
		DeletedSessionEvents: 7,
		DeletedUnmapped:      11,
		ExecutedAt:           executedAt,
	}

	if err := store.UpdateMaintenanceStatus(&report, &nextCleanupAt, "6h0m0s"); err != nil {
		t.Fatalf("UpdateMaintenanceStatus() error = %v", err)
	}

	status, err := store.GetMaintenanceStatus()
	if err != nil {
		t.Fatalf("GetMaintenanceStatus() error = %v", err)
	}
	if status.LastCleanup == nil {
		t.Fatal("expected last cleanup report")
	}
	if status.LastCleanup.DeletedCaptures != report.DeletedCaptures {
		t.Fatalf("DeletedCaptures = %d, want %d", status.LastCleanup.DeletedCaptures, report.DeletedCaptures)
	}
	if status.LastCleanup.DeletedUnmapped != report.DeletedUnmapped {
		t.Fatalf("DeletedUnmapped = %d, want %d", status.LastCleanup.DeletedUnmapped, report.DeletedUnmapped)
	}
	if status.NextCleanupAt == nil || !status.NextCleanupAt.Equal(nextCleanupAt) {
		t.Fatalf("NextCleanupAt = %v, want %v", status.NextCleanupAt, nextCleanupAt)
	}
	if status.CleanupInterval != "6h0m0s" {
		t.Fatalf("CleanupInterval = %q, want %q", status.CleanupInterval, "6h0m0s")
	}
	if status.UpdatedAt == nil {
		t.Fatal("expected UpdatedAt to be set")
	}
}

func TestApplyRetentionDeletesOldRowsAndFiles(t *testing.T) {
	store := openTestStore(t)
	defer store.Close()

	oldCapture := writeCaptureFixture(t, store, "cap-old.bin", "old")
	newCapture := writeCaptureFixture(t, store, "cap-new.bin", "new")
	oldTime := time.Now().UTC().AddDate(0, 0, -45).Format(time.RFC3339Nano)
	newTime := time.Now().UTC().Format(time.RFC3339Nano)

	mustExec(t, store, `INSERT INTO captures (id, profile_id, device_id, transport_type, raw_path, decoded_text, normalized_text, classification_json, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, "cap-old", "profile-a", "device-a", string(models.TransportSerial), oldCapture, "old", "old", `{}`, oldTime)
	mustExec(t, store, `INSERT INTO captures (id, profile_id, device_id, transport_type, raw_path, decoded_text, normalized_text, classification_json, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, "cap-new", "profile-a", "device-a", string(models.TransportSerial), newCapture, "new", "new", `{}`, newTime)
	mustExec(t, store, `INSERT INTO runtime_errors (id, profile_id, device_id, transport_type, message, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`, "err-old", "profile-a", "device-a", string(models.TransportSerial), "old error", `{}`, oldTime)
	mustExec(t, store, `INSERT INTO runtime_errors (id, profile_id, device_id, transport_type, message, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`, "err-new", "profile-a", "device-a", string(models.TransportSerial), "new error", `{}`, newTime)
	mustExec(t, store, `INSERT INTO session_events (id, session_id, profile_id, device_id, transport_type, state, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, "evt-old", "sess-1", "profile-a", "device-a", string(models.TransportSerial), "old", `{}`, oldTime)
	mustExec(t, store, `INSERT INTO session_events (id, session_id, profile_id, device_id, transport_type, state, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, "evt-new", "sess-1", "profile-a", "device-a", string(models.TransportSerial), "new", `{}`, newTime)
	mustExec(t, store, `INSERT INTO unmapped_observations (id, capture_id, profile_id, device_id, instrument_test_code, instrument_test_name, value_raw, units_raw, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, "unmapped-old", "cap-old", "profile-a", "device-a", "GLU", "Glucose", "101", "mg/dL", oldTime)
	mustExec(t, store, `INSERT INTO unmapped_observations (id, capture_id, profile_id, device_id, instrument_test_code, instrument_test_name, value_raw, units_raw, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, "unmapped-new", "cap-new", "profile-a", "device-a", "GLU", "Glucose", "102", "mg/dL", newTime)

	report, err := store.ApplyRetention(RetentionPolicy{
		RetentionDays:   30,
		SessionEventMax: 50,
		RuntimeErrorMax: 50,
		CaptureMax:      50,
	})
	if err != nil {
		t.Fatalf("ApplyRetention() error = %v", err)
	}
	if report.DeletedCaptures != 1 {
		t.Fatalf("DeletedCaptures = %d, want 1", report.DeletedCaptures)
	}
	if report.DeletedCaptureFiles != 1 {
		t.Fatalf("DeletedCaptureFiles = %d, want 1", report.DeletedCaptureFiles)
	}
	if report.DeletedRuntimeErrors != 1 {
		t.Fatalf("DeletedRuntimeErrors = %d, want 1", report.DeletedRuntimeErrors)
	}
	if report.DeletedSessionEvents != 1 {
		t.Fatalf("DeletedSessionEvents = %d, want 1", report.DeletedSessionEvents)
	}
	if report.DeletedUnmapped != 1 {
		t.Fatalf("DeletedUnmapped = %d, want 1", report.DeletedUnmapped)
	}
	if _, err := os.Stat(oldCapture); !os.IsNotExist(err) {
		t.Fatalf("expected old capture file to be removed, stat err = %v", err)
	}
	if _, err := os.Stat(newCapture); err != nil {
		t.Fatalf("expected new capture file to remain, stat err = %v", err)
	}
	assertCount(t, store, `SELECT COUNT(*) FROM captures`, 1)
	assertCount(t, store, `SELECT COUNT(*) FROM runtime_errors`, 1)
	assertCount(t, store, `SELECT COUNT(*) FROM session_events`, 1)
	assertCount(t, store, `SELECT COUNT(*) FROM unmapped_observations`, 1)
}

func TestApplyRetentionTrimsNewestRows(t *testing.T) {
	store := openTestStore(t)
	defer store.Close()

	for i := 0; i < 3; i++ {
		timestamp := time.Now().UTC().Add(time.Duration(i) * time.Minute).Format(time.RFC3339Nano)
		mustExec(t, store, `INSERT INTO runtime_errors (id, profile_id, device_id, transport_type, message, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
			"err-"+time.Now().UTC().Add(time.Duration(i)*time.Minute).Format("150405")+string(rune('a'+i)), "profile-a", "device-a", string(models.TransportSerial), "error", `{}`, timestamp)
	}

	report, err := store.ApplyRetention(RetentionPolicy{
		RetentionDays:   365,
		SessionEventMax: 50,
		RuntimeErrorMax: 2,
		CaptureMax:      50,
	})
	if err != nil {
		t.Fatalf("ApplyRetention() error = %v", err)
	}
	if report.DeletedRuntimeErrors != 1 {
		t.Fatalf("DeletedRuntimeErrors = %d, want 1", report.DeletedRuntimeErrors)
	}
	assertCount(t, store, `SELECT COUNT(*) FROM runtime_errors`, 2)
}

func openTestStore(t *testing.T) *Store {
	t.Helper()
	root := t.TempDir()
	store, err := Open(filepath.Join(root, "engine.db"), filepath.Join(root, "captures"))
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	return store
}

func writeCaptureFixture(t *testing.T, store *Store, name, contents string) string {
	t.Helper()
	path := filepath.Join(store.CaptureDir, name)
	if err := os.WriteFile(path, []byte(contents), 0o644); err != nil {
		t.Fatalf("WriteFile() error = %v", err)
	}
	return path
}

func mustExec(t *testing.T, store *Store, query string, args ...any) {
	t.Helper()
	if _, err := store.DB.Exec(query, args...); err != nil {
		t.Fatalf("Exec(%q) error = %v", query, err)
	}
}

func assertCount(t *testing.T, store *Store, query string, want int) {
	t.Helper()
	var got int
	if err := store.DB.QueryRow(query).Scan(&got); err != nil {
		t.Fatalf("QueryRow(%q) error = %v", query, err)
	}
	if got != want {
		t.Fatalf("count for %q = %d, want %d", query, got, want)
	}
}

func TestUpsertNetworkDevicesPersistsHistory(t *testing.T) {
	store := openTestStore(t)
	defer store.Close()

	device := models.NetworkDevice{DeviceID: "net:192.168.1.10", IP: "192.168.1.10", CIDR: "192.168.1.0/24", InterfaceName: "Ethernet0", OpenPorts: []int{5000}, Reachability: "tcp_open", Banner: "SSH-2.0-test", BannerProtocol: "ssh", LikelyProtocols: []string{"hl7_mllp_candidate", "ssh"}, FirstSeen: time.Now().UTC(), LastSeen: time.Now().UTC(), SeenCount: 1, StabilityScore: 0.6}
	merged, err := store.UpsertNetworkDevices([]models.NetworkDevice{device})
	if err != nil { t.Fatalf("UpsertNetworkDevices() error = %v", err) }
	if len(merged) != 1 { t.Fatalf("len(merged) = %d, want 1", len(merged)) }
	if merged[0].SeenCount != 1 { t.Fatalf("SeenCount = %d, want 1", merged[0].SeenCount) }
	if merged[0].LastSeenStatus != "online" { t.Fatalf("LastSeenStatus = %q, want online", merged[0].LastSeenStatus) }

	device.LastSeen = time.Now().UTC().Add(time.Minute)
	merged, err = store.UpsertNetworkDevices([]models.NetworkDevice{device})
	if err != nil { t.Fatalf("UpsertNetworkDevices() second call error = %v", err) }
	if merged[0].SeenCount < 2 { t.Fatalf("SeenCount = %d, want >= 2", merged[0].SeenCount) }
	if len(merged[0].CIDRHistory) != 1 || merged[0].CIDRHistory[0].Count < 2 { t.Fatalf("CIDRHistory = %#v, want repeated subnet history", merged[0].CIDRHistory) }
	if len(merged[0].InterfaceHistory) != 1 || merged[0].InterfaceHistory[0].Value != "Ethernet0" { t.Fatalf("InterfaceHistory = %#v", merged[0].InterfaceHistory) }
	if len(merged[0].LikelyProtocols) == 0 { t.Fatal("expected likely protocols to round-trip") }
	if merged[0].StabilityScore <= 0.6 { t.Fatalf("StabilityScore = %f, want > 0.6", merged[0].StabilityScore) }

	listed, err := store.ListNetworkDevices(10)
	if err != nil { t.Fatalf("ListNetworkDevices() error = %v", err) }
	if len(listed) != 1 { t.Fatalf("len(listed) = %d, want 1", len(listed)) }
	if listed[0].BannerProtocol != "ssh" { t.Fatalf("BannerProtocol = %q, want ssh", listed[0].BannerProtocol) }
}

func TestNetworkDeviceLinksAndReplaySummary(t *testing.T) {
	store := openTestStore(t)
	defer store.Close()

	now := time.Now().UTC()
	_, err := store.UpsertNetworkDevices([]models.NetworkDevice{{
		DeviceID: "net:192.168.1.20",
		IP: "192.168.1.20",
		CIDR: "192.168.1.0/24",
		OpenPorts: []int{5000},
		Reachability: "tcp_open",
		FirstSeen: now,
		LastSeen: now,
	}})
	if err != nil { t.Fatalf("UpsertNetworkDevices() error = %v", err) }

	if err := store.UpsertNetworkDeviceLinks([]models.NetworkDeviceLink{{
		NetworkDeviceID: "net:192.168.1.20",
		ProfileID: "generic-hl7",
		RuntimeDeviceID: "analyzer-runtime-1",
		Source: "payload",
		SeenCount: 1,
		FirstSeen: now,
		LastSeen: now,
	}}); err != nil {
		t.Fatalf("UpsertNetworkDeviceLinks() error = %v", err)
	}

	mustExec(t, store, `INSERT INTO captures (id, profile_id, device_id, transport_type, raw_path, decoded_text, normalized_text, classification_json, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		"cap-linked", "generic-hl7", "analyzer-runtime-1", string(models.TransportTCPClient), writeCaptureFixture(t, store, "cap-linked.bin", "payload"), "payload", "payload", `{}`, now.Format(time.RFC3339Nano))
	mustExec(t, store, `INSERT INTO runtime_errors (id, profile_id, device_id, transport_type, message, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		"err-linked", "generic-hl7", "analyzer-runtime-1", string(models.TransportTCPClient), "parse failed", `{}`, now.Format(time.RFC3339Nano))
	if err := store.RecordReplayEvent("net:192.168.1.20", "cap-linked", "generic-hl7", "analyzer-runtime-1", "success", "hl7_v2"); err != nil {
		t.Fatalf("RecordReplayEvent() error = %v", err)
	}

	listed, err := store.ListNetworkDevices(10)
	if err != nil { t.Fatalf("ListNetworkDevices() error = %v", err) }
	if len(listed) != 1 { t.Fatalf("len(listed) = %d, want 1", len(listed)) }
	if listed[0].RecentCaptureCount != 1 { t.Fatalf("RecentCaptureCount = %d, want 1", listed[0].RecentCaptureCount) }
	if listed[0].RecentParseFailures != 1 { t.Fatalf("RecentParseFailures = %d, want 1", listed[0].RecentParseFailures) }
	if listed[0].LastReplayStatus != "success" { t.Fatalf("LastReplayStatus = %q, want success", listed[0].LastReplayStatus) }
	if len(listed[0].RecentReplayEvents) != 1 { t.Fatalf("RecentReplayEvents = %#v", listed[0].RecentReplayEvents) }
	if len(listed[0].RecentErrorExcerpts) != 1 { t.Fatalf("RecentErrorExcerpts = %#v", listed[0].RecentErrorExcerpts) }
	if len(listed[0].CorrelatedRuntimeIDs) != 1 || listed[0].CorrelatedRuntimeIDs[0] != "analyzer-runtime-1" {
		t.Fatalf("CorrelatedRuntimeIDs = %#v", listed[0].CorrelatedRuntimeIDs)
	}
	networkDeviceID, err := store.FindNetworkDeviceID("generic-hl7", "analyzer-runtime-1")
	if err != nil { t.Fatalf("FindNetworkDeviceID() error = %v", err) }
	if networkDeviceID != "net:192.168.1.20" { t.Fatalf("networkDeviceID = %q, want net:192.168.1.20", networkDeviceID) }
	allLinks, err := store.ListAllNetworkDeviceLinks()
	if err != nil { t.Fatalf("ListAllNetworkDeviceLinks() error = %v", err) }
	if len(allLinks) != 1 || allLinks[0].Confidence == 0 {
		t.Fatalf("allLinks = %#v", allLinks)
	}
}
