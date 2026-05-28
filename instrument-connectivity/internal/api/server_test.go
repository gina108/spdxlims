package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"instrument-connectivity/internal/capture"
	"instrument-connectivity/internal/learning"
	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/profile"
	"instrument-connectivity/internal/transport"
)

type fakeService struct {
	runtimeSnapshot         capture.RuntimeSnapshot
	cleanupReport           capture.CleanupReport
	runRetentionHit         bool
	lastScanRequest         models.NetworkScanRequest
	lastCaptureFilter       capture.CaptureFilter
	savedOperator           string
	savedNetworkLink        models.NetworkDeviceLink
	saveNetworkLinkOverride bool
	deletedNetworkLink      [3]string
	deletedNetworkLinkActor string
	exportedNetworkLinks    []models.NetworkDeviceLink
	previewNetworkLinks     models.NetworkLinkImportPreview
	importedNetworkLinks    []models.NetworkDeviceLink
	importReplace           bool
	importMerges            []models.NetworkLinkMergeDecision
	importActor             string
	migrationBundle         profile.MigrationBundle
	migrationPreview        profile.MigrationBundlePreview
	importedBundle          profile.MigrationBundle
	auditEntries            []models.NetworkLinkAuditEntry
	auditFilter             models.NetworkLinkAuditFilter
	exportRedaction         models.RedactionOptions
	exportActor             string
	secretStatus            models.BundleSecretStatus
}

func (f *fakeService) ListProfiles() ([]profile.Profile, error) { return nil, nil }
func (f *fakeService) SaveProfile(profile.Profile) error        { return nil }
func (f *fakeService) ExportMigrationBundle(redaction models.RedactionOptions, actor string) (profile.MigrationBundle, error) {
	f.exportRedaction = redaction
	f.exportActor = actor
	return f.migrationBundle, nil
}
func (f *fakeService) PreviewMigrationBundle(bundle profile.MigrationBundle) (profile.MigrationBundlePreview, error) {
	return f.migrationPreview, nil
}
func (f *fakeService) ImportMigrationBundle(bundle profile.MigrationBundle, actor string, merges []models.NetworkLinkMergeDecision) error {
	f.importedBundle = bundle
	f.importActor = actor
	f.importMerges = merges
	return nil
}
func (f *fakeService) ScanPorts(req models.NetworkScanRequest) ([]models.DeviceFingerprint, []transport.SerialCandidate, []models.NetworkDevice, error) {
	f.lastScanRequest = req
	return nil, nil, nil, nil
}
func (f *fakeService) ProcessPayload(raw []byte, transport models.TransportType, profileID string, deviceID string) (models.ParseResult, capture.CaptureRecord, error) {
	return models.ParseResult{}, capture.CaptureRecord{}, nil
}
func (f *fakeService) ListCaptures(filter capture.CaptureFilter) ([]capture.CaptureRecord, error) {
	f.lastCaptureFilter = filter
	return nil, nil
}
func (f *fakeService) ReplayCapture(id, overrideProfileID string) (models.ParseResult, error) {
	return models.ParseResult{}, nil
}
func (f *fakeService) SaveNetworkLink(link models.NetworkDeviceLink, override bool, actor string) error {
	f.savedNetworkLink = link
	f.saveNetworkLinkOverride = override
	f.savedOperator = actor
	return nil
}
func (f *fakeService) DeleteNetworkLink(networkDeviceID, profileID, runtimeDeviceID string) error {
	f.deletedNetworkLink = [3]string{networkDeviceID, profileID, runtimeDeviceID}
	return nil
}
func (f *fakeService) DeleteNetworkLinkWithActor(networkDeviceID, profileID, runtimeDeviceID, actor string) error {
	f.deletedNetworkLink = [3]string{networkDeviceID, profileID, runtimeDeviceID}
	f.deletedNetworkLinkActor = actor
	return nil
}
func (f *fakeService) ExportNetworkLinks() ([]models.NetworkDeviceLink, error) {
	return f.exportedNetworkLinks, nil
}
func (f *fakeService) PreviewNetworkLinkImport(links []models.NetworkDeviceLink) (models.NetworkLinkImportPreview, error) {
	if len(links) > 0 {
		f.previewNetworkLinks.Links = links
	}
	return f.previewNetworkLinks, nil
}
func (f *fakeService) ImportNetworkLinks(links []models.NetworkDeviceLink, replace bool, merges []models.NetworkLinkMergeDecision, actor string) error {
	f.importedNetworkLinks = links
	f.importReplace = replace
	f.importMerges = merges
	f.importActor = actor
	return nil
}
func (f *fakeService) ListNetworkLinkAudit(filter models.NetworkLinkAuditFilter) ([]models.NetworkLinkAuditEntry, error) {
	f.auditFilter = filter
	return f.auditEntries, nil
}
func (f *fakeService) StartCapture(profileID string) (string, error) { return "", nil }
func (f *fakeService) StopCapture(sessionID string) error            { return nil }
func (f *fakeService) SuggestLearning(rawText, profileID, captureID string) (learning.Suggestion, error) {
	return learning.Suggestion{}, nil
}
func (f *fakeService) BuildSupportBundle() (string, []byte, error) { return "", nil, nil }
func (f *fakeService) BundleSecretStatus() (models.BundleSecretStatus, error) {
	return f.secretStatus, nil
}
func (f *fakeService) RuntimeSnapshot(limit int) (capture.RuntimeSnapshot, error) {
	return f.runtimeSnapshot, nil
}
func (f *fakeService) RuntimeErrors(limit int) ([]capture.RuntimeError, error) { return nil, nil }
func (f *fakeService) SessionHistory(filter capture.SessionEventFilter) ([]capture.SessionEvent, error) {
	return nil, nil
}
func (f *fakeService) RunRetention() (capture.CleanupReport, error) {
	f.runRetentionHit = true
	return f.cleanupReport, nil
}

func TestRuntimeStatusIncludesMaintenance(t *testing.T) {
	executedAt := time.Date(2026, 3, 22, 18, 0, 0, 0, time.UTC)
	nextCleanupAt := executedAt.Add(6 * time.Hour)
	svc := &fakeService{
		runtimeSnapshot: capture.RuntimeSnapshot{
			Devices:     []capture.RuntimeStatus{{ProfileID: "profile-a", DeviceID: "device-a", TransportType: "serial", SessionState: "connected"}},
			Maintenance: capture.MaintenanceStatus{LastCleanup: &capture.CleanupReport{Policy: capture.RetentionPolicy{RetentionDays: 30, SessionEventMax: 5000, RuntimeErrorMax: 2000, CaptureMax: 2000}, DeletedCaptures: 2, DeletedCaptureFiles: 1, DeletedRuntimeErrors: 3, DeletedSessionEvents: 4, DeletedUnmapped: 5, ExecutedAt: executedAt}, NextCleanupAt: &nextCleanupAt, CleanupInterval: "6h0m0s", UpdatedAt: &executedAt},
		},
	}

	handler := New(svc, Options{}).Routes()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/runtime/status?limit=5", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d", rr.Code, http.StatusOK)
	}

	var got capture.RuntimeSnapshot
	if err := json.Unmarshal(rr.Body.Bytes(), &got); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if len(got.Devices) != 1 {
		t.Fatalf("len(Devices) = %d, want 1", len(got.Devices))
	}
	if got.Maintenance.LastCleanup == nil {
		t.Fatal("expected maintenance.last_cleanup")
	}
	if got.Maintenance.LastCleanup.DeletedRuntimeErrors != 3 {
		t.Fatalf("DeletedRuntimeErrors = %d, want 3", got.Maintenance.LastCleanup.DeletedRuntimeErrors)
	}
	if got.Maintenance.CleanupInterval != "6h0m0s" {
		t.Fatalf("CleanupInterval = %q, want %q", got.Maintenance.CleanupInterval, "6h0m0s")
	}
	if got.Maintenance.NextCleanupAt == nil || !got.Maintenance.NextCleanupAt.Equal(nextCleanupAt) {
		t.Fatalf("NextCleanupAt = %v, want %v", got.Maintenance.NextCleanupAt, nextCleanupAt)
	}
}

func TestRuntimeCleanupReturnsReport(t *testing.T) {
	executedAt := time.Date(2026, 3, 22, 19, 30, 0, 0, time.UTC)
	svc := &fakeService{cleanupReport: capture.CleanupReport{Policy: capture.RetentionPolicy{RetentionDays: 30, SessionEventMax: 5000, RuntimeErrorMax: 2000, CaptureMax: 2000}, DeletedCaptures: 4, DeletedCaptureFiles: 4, DeletedRuntimeErrors: 2, DeletedSessionEvents: 1, DeletedUnmapped: 3, ExecutedAt: executedAt}}

	handler := New(svc, Options{}).Routes()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/runtime/cleanup", bytes.NewBufferString(`{}`))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d body=%s", rr.Code, http.StatusOK, rr.Body.String())
	}
	if !svc.runRetentionHit {
		t.Fatal("expected RunRetention to be called")
	}

	var got capture.CleanupReport
	if err := json.Unmarshal(rr.Body.Bytes(), &got); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if got.DeletedCaptures != 4 {
		t.Fatalf("DeletedCaptures = %d, want 4", got.DeletedCaptures)
	}
	if got.DeletedCaptureFiles != 4 {
		t.Fatalf("DeletedCaptureFiles = %d, want 4", got.DeletedCaptureFiles)
	}
	if !got.ExecutedAt.Equal(executedAt) {
		t.Fatalf("ExecutedAt = %s, want %s", got.ExecutedAt.Format(time.RFC3339Nano), executedAt.Format(time.RFC3339Nano))
	}
}

func TestRuntimeCleanupRequiresAuthWhenConfigured(t *testing.T) {
	svc := &fakeService{}
	handler := New(svc, Options{APIAuthToken: "secret-token"}).Routes()

	req := httptest.NewRequest(http.MethodPost, "/api/v1/runtime/cleanup", bytes.NewBufferString(`{}`))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("status code = %d, want %d", rr.Code, http.StatusUnauthorized)
	}
	if svc.runRetentionHit {
		t.Fatal("did not expect RunRetention to be called without auth")
	}

	var got map[string]string
	if err := json.Unmarshal(rr.Body.Bytes(), &got); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if got["code"] != "api_auth_required" {
		t.Fatalf("error code = %q, want %q", got["code"], "api_auth_required")
	}
}

func TestRuntimeCleanupAcceptsBearerAuth(t *testing.T) {
	svc := &fakeService{cleanupReport: capture.CleanupReport{DeletedCaptures: 1, ExecutedAt: time.Now().UTC()}}
	handler := New(svc, Options{APIAuthToken: "secret-token"}).Routes()

	req := httptest.NewRequest(http.MethodPost, "/api/v1/runtime/cleanup", bytes.NewBufferString(`{}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", "secret-token"))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d body=%s", rr.Code, http.StatusOK, rr.Body.String())
	}
	if !svc.runRetentionHit {
		t.Fatal("expected RunRetention to be called with bearer auth")
	}
}

func TestScanPortsAcceptsCIDRAndPortQueries(t *testing.T) {
	svc := &fakeService{}
	handler := New(svc, Options{}).Routes()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/ports/scan?cidrs=192.168.1.0/24,10.10.20.0/24&ports=5000,8080,bad", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d body=%s", rr.Code, http.StatusOK, rr.Body.String())
	}
	if len(svc.lastScanRequest.CIDRs) != 2 {
		t.Fatalf("cidrs = %#v", svc.lastScanRequest.CIDRs)
	}
	if len(svc.lastScanRequest.Ports) != 2 || svc.lastScanRequest.Ports[0] != 5000 || svc.lastScanRequest.Ports[1] != 8080 {
		t.Fatalf("ports = %#v", svc.lastScanRequest.Ports)
	}
}

func TestCapturesAcceptsDeviceAndProfileFilters(t *testing.T) {
	svc := &fakeService{}
	handler := New(svc, Options{}).Routes()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/captures?device_id=net:192.168.1.10&profile_id=generic-hl7&limit=7", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d body=%s", rr.Code, http.StatusOK, rr.Body.String())
	}
	if svc.lastCaptureFilter.DeviceID != "net:192.168.1.10" {
		t.Fatalf("device filter = %q", svc.lastCaptureFilter.DeviceID)
	}
	if svc.lastCaptureFilter.ProfileID != "generic-hl7" {
		t.Fatalf("profile filter = %q", svc.lastCaptureFilter.ProfileID)
	}
	if svc.lastCaptureFilter.Limit != 7 {
		t.Fatalf("limit = %d", svc.lastCaptureFilter.Limit)
	}
}

func TestCapturesAcceptsMultipleDeviceIDs(t *testing.T) {
	svc := &fakeService{}
	handler := New(svc, Options{}).Routes()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/captures?device_ids=analyzer-a,analyzer-b&limit=4", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d body=%s", rr.Code, http.StatusOK, rr.Body.String())
	}
	if len(svc.lastCaptureFilter.DeviceIDs) != 2 {
		t.Fatalf("device_ids = %#v", svc.lastCaptureFilter.DeviceIDs)
	}
	if svc.lastCaptureFilter.DeviceIDs[0] != "analyzer-a" || svc.lastCaptureFilter.DeviceIDs[1] != "analyzer-b" {
		t.Fatalf("device_ids = %#v", svc.lastCaptureFilter.DeviceIDs)
	}
}

func TestNetworkLinksSaveAndDelete(t *testing.T) {
	svc := &fakeService{}
	handler := New(svc, Options{}).Routes()

	postReq := httptest.NewRequest(http.MethodPost, "/api/v1/network-links", bytes.NewBufferString(`{"network_device_id":"net:192.168.1.44","profile_id":"generic-hl7","runtime_device_id":"analyzer-44","override":true}`))
	postReq.Header.Set("Content-Type", "application/json")
	postReq.Header.Set("X-Operator-Name", "Support A")
	postRR := httptest.NewRecorder()
	handler.ServeHTTP(postRR, postReq)
	if postRR.Code != http.StatusOK {
		t.Fatalf("post status = %d body=%s", postRR.Code, postRR.Body.String())
	}
	if svc.savedNetworkLink.NetworkDeviceID != "net:192.168.1.44" || svc.savedNetworkLink.ProfileID != "generic-hl7" || svc.savedNetworkLink.RuntimeDeviceID != "analyzer-44" {
		t.Fatalf("saved link = %#v", svc.savedNetworkLink)
	}
	if !svc.saveNetworkLinkOverride {
		t.Fatal("expected override=true")
	}
	if svc.savedOperator != "Support A" {
		t.Fatalf("saved operator = %q", svc.savedOperator)
	}

	delReq := httptest.NewRequest(http.MethodDelete, "/api/v1/network-links?network_device_id=net:192.168.1.44&profile_id=generic-hl7&runtime_device_id=analyzer-44&actor=Support%20B", nil)
	delRR := httptest.NewRecorder()
	handler.ServeHTTP(delRR, delReq)
	if delRR.Code != http.StatusOK {
		t.Fatalf("delete status = %d body=%s", delRR.Code, delRR.Body.String())
	}
	if svc.deletedNetworkLink != [3]string{"net:192.168.1.44", "generic-hl7", "analyzer-44"} {
		t.Fatalf("deleted link = %#v", svc.deletedNetworkLink)
	}
	if svc.deletedNetworkLinkActor != "Support B" {
		t.Fatalf("delete actor = %q", svc.deletedNetworkLinkActor)
	}
}

func TestNetworkLinkExportPreviewAndImport(t *testing.T) {
	svc := &fakeService{
		exportedNetworkLinks: []models.NetworkDeviceLink{{NetworkDeviceID: "net:1.2.3.4", ProfileID: "generic-hl7", RuntimeDeviceID: "analyzer-1", Source: "manual_override", Confidence: 0.98}},
		previewNetworkLinks: models.NetworkLinkImportPreview{
			Diagnostics: models.NetworkLinkDiagnostics{TotalLinks: 1, BySource: map[string]int{"manual_override": 1}},
			Conflicts: []models.NetworkLinkImportConflict{{
				ConflictID: "runtime:generic-hl7|analyzer-2|net:5.6.7.8",
				Type:       "runtime_claimed_elsewhere",
				Message:    "conflict",
			}},
		},
	}
	handler := New(svc, Options{}).Routes()

	getReq := httptest.NewRequest(http.MethodGet, "/api/v1/network-links/export", nil)
	getRR := httptest.NewRecorder()
	handler.ServeHTTP(getRR, getReq)
	if getRR.Code != http.StatusOK {
		t.Fatalf("export status = %d body=%s", getRR.Code, getRR.Body.String())
	}

	previewReq := httptest.NewRequest(http.MethodPost, "/api/v1/network-links/preview-import", bytes.NewBufferString(`{"links":[{"network_device_id":"net:5.6.7.8","profile_id":"generic-hl7","runtime_device_id":"analyzer-2","source":"manual_import","confidence":0.99}]}`))
	previewReq.Header.Set("Content-Type", "application/json")
	previewRR := httptest.NewRecorder()
	handler.ServeHTTP(previewRR, previewReq)
	if previewRR.Code != http.StatusOK {
		t.Fatalf("preview status = %d body=%s", previewRR.Code, previewRR.Body.String())
	}

	postReq := httptest.NewRequest(http.MethodPost, "/api/v1/network-links/import", bytes.NewBufferString(`{"replace":false,"actor":"Support C","merges":[{"conflict_id":"runtime:generic-hl7|analyzer-2|net:5.6.7.8","resolution":"use_imported"}],"links":[{"network_device_id":"net:5.6.7.8","profile_id":"generic-hl7","runtime_device_id":"analyzer-2","source":"manual_import","confidence":0.99}]}`))
	postReq.Header.Set("Content-Type", "application/json")
	postRR := httptest.NewRecorder()
	handler.ServeHTTP(postRR, postReq)
	if postRR.Code != http.StatusOK {
		t.Fatalf("import status = %d body=%s", postRR.Code, postRR.Body.String())
	}
	if svc.importReplace {
		t.Fatal("expected replace=false on import")
	}
	if len(svc.importedNetworkLinks) != 1 || svc.importedNetworkLinks[0].RuntimeDeviceID != "analyzer-2" {
		t.Fatalf("imported links = %#v", svc.importedNetworkLinks)
	}
	if len(svc.importMerges) != 1 || svc.importMerges[0].Resolution != "use_imported" {
		t.Fatalf("import merges = %#v", svc.importMerges)
	}
	if svc.importActor != "Support C" {
		t.Fatalf("import actor = %q", svc.importActor)
	}
}

func TestProfilesIncludesDiscoveryHintCatalog(t *testing.T) {
	svc := &fakeService{}
	handler := New(svc, Options{}).Routes()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/profiles", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("status code = %d body=%s", rr.Code, rr.Body.String())
	}
	var got map[string]json.RawMessage
	if err := json.Unmarshal(rr.Body.Bytes(), &got); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if len(got["discovery_hint_catalog"]) == 0 {
		t.Fatal("expected discovery_hint_catalog")
	}
}

func TestMigrationBundleExportImportAndAudit(t *testing.T) {
	svc := &fakeService{
		migrationBundle: profile.MigrationBundle{
			Version:      "v1",
			Profiles:     []profile.Profile{{ID: "generic-hl7", Name: "Generic HL7"}},
			NetworkLinks: []models.NetworkDeviceLink{{NetworkDeviceID: "net:1.2.3.4", ProfileID: "generic-hl7", RuntimeDeviceID: "analyzer-1"}},
		},
		migrationPreview: profile.MigrationBundlePreview{
			IntegrityValid: true,
			ProfileDiffs:   []profile.MigrationProfileDiff{{ProfileID: "generic-hl7", Status: "changed", ChangedSections: []string{"transport", "mapping"}}},
		},
		auditEntries: []models.NetworkLinkAuditEntry{{ID: "audit-1", Action: "manual_override", Actor: "Support A", CreatedAt: time.Now().UTC()}},
		secretStatus: models.BundleSecretStatus{Algorithm: "hmac-sha256", Mode: "configured", SharedConfigured: true, Summary: "Using a shared configured HMAC secret for bundle signing."},
	}
	handler := New(svc, Options{}).Routes()

	exportReq := httptest.NewRequest(http.MethodGet, "/api/v1/migration-bundle/export?redaction_preset=external_share", nil)
	exportReq.Header.Set("X-Operator-Name", "Support Export")
	exportRR := httptest.NewRecorder()
	handler.ServeHTTP(exportRR, exportReq)
	if exportRR.Code != http.StatusOK {
		t.Fatalf("export status = %d body=%s", exportRR.Code, exportRR.Body.String())
	}
	if !svc.exportRedaction.RedactActors || !svc.exportRedaction.RedactNetworkEndpoints || !svc.exportRedaction.RedactRuntimeDeviceIDs {
		t.Fatalf("export redaction = %#v", svc.exportRedaction)
	}
	if svc.exportActor != "Support Export" {
		t.Fatalf("export actor = %q", svc.exportActor)
	}

	auditReq := httptest.NewRequest(http.MethodGet, "/api/v1/network-links/audit?limit=5&actor=Support%20A&profile_id=generic-hl7&network_device_id=net:1.2.3.4&action=manual_override", nil)
	auditRR := httptest.NewRecorder()
	handler.ServeHTTP(auditRR, auditReq)
	if auditRR.Code != http.StatusOK {
		t.Fatalf("audit status = %d body=%s", auditRR.Code, auditRR.Body.String())
	}
	if svc.auditFilter.Actor != "Support A" || svc.auditFilter.ProfileID != "generic-hl7" || svc.auditFilter.NetworkDeviceID != "net:1.2.3.4" || svc.auditFilter.Action != "manual_override" {
		t.Fatalf("audit filter = %#v", svc.auditFilter)
	}

	previewReq := httptest.NewRequest(http.MethodPost, "/api/v1/migration-bundle/preview", bytes.NewBufferString(`{"bundle":{"version":"v1","profiles":[{"id":"generic-hl7","name":"Generic HL7"}],"network_links":[{"network_device_id":"net:1.2.3.4","profile_id":"generic-hl7","runtime_device_id":"analyzer-1"}]}}`))
	previewReq.Header.Set("Content-Type", "application/json")
	previewRR := httptest.NewRecorder()
	handler.ServeHTTP(previewRR, previewReq)
	if previewRR.Code != http.StatusOK {
		t.Fatalf("preview status = %d body=%s", previewRR.Code, previewRR.Body.String())
	}

	importReq := httptest.NewRequest(http.MethodPost, "/api/v1/migration-bundle/import", bytes.NewBufferString(`{"actor":"Support D","bundle":{"version":"v1","profiles":[{"id":"generic-hl7","name":"Generic HL7"}],"network_links":[{"network_device_id":"net:1.2.3.4","profile_id":"generic-hl7","runtime_device_id":"analyzer-1"}]}}`))
	importReq.Header.Set("Content-Type", "application/json")
	importRR := httptest.NewRecorder()
	handler.ServeHTTP(importRR, importReq)
	if importRR.Code != http.StatusOK {
		t.Fatalf("import status = %d body=%s", importRR.Code, importRR.Body.String())
	}
	if svc.importedBundle.Version != "v1" || svc.importActor != "Support D" {
		t.Fatalf("imported bundle/actor = %#v / %q", svc.importedBundle, svc.importActor)
	}

	secretReq := httptest.NewRequest(http.MethodGet, "/api/v1/runtime/secret-status", nil)
	secretRR := httptest.NewRecorder()
	handler.ServeHTTP(secretRR, secretReq)
	if secretRR.Code != http.StatusOK {
		t.Fatalf("secret status = %d body=%s", secretRR.Code, secretRR.Body.String())
	}
}

func TestExportNetworkLinkAuditSupportsRedaction(t *testing.T) {
	svc := &fakeService{
		auditEntries: []models.NetworkLinkAuditEntry{{
			ID: "audit-1", Action: "manual_override", Actor: "Support A", NetworkDeviceID: "net:1.2.3.4", RuntimeDeviceID: "analyzer-1",
			Detail: map[string]any{"endpoint": "net:1.2.3.4", "runtime_device_id": "analyzer-1"}, CreatedAt: time.Now().UTC(),
		}},
	}
	handler := New(svc, Options{}).Routes()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/network-links/audit/export?redaction_preset=external_share", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("status code = %d body=%s", rr.Code, rr.Body.String())
	}

	var payload map[string]json.RawMessage
	if err := json.Unmarshal(rr.Body.Bytes(), &payload); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	var entries []models.NetworkLinkAuditEntry
	if err := json.Unmarshal(payload["entries"], &entries); err != nil {
		t.Fatalf("entries unmarshal error = %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("len(entries) = %d, want 1", len(entries))
	}
	if entries[0].Actor == "Support A" || entries[0].NetworkDeviceID == "net:1.2.3.4" || entries[0].RuntimeDeviceID == "analyzer-1" {
		t.Fatalf("redacted entry = %#v", entries[0])
	}
}
