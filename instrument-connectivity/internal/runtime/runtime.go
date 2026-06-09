package runtime

import (
	"archive/zip"
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"instrument-connectivity/internal/api"
	"instrument-connectivity/internal/capture"
	"instrument-connectivity/internal/config"
	"instrument-connectivity/internal/discovery"
	"instrument-connectivity/internal/learning"
	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/orders"
	"instrument-connectivity/internal/pipeline"
	"instrument-connectivity/internal/profile"
	"instrument-connectivity/internal/transport"
)

type App struct {
	cfg              config.Config
	profiles         *profile.Store
	captures         *capture.Store
	processor        *pipeline.Processor
	discovery        *discovery.Service
	learning         *learning.Engine
	pendingOrders    *orders.Store
	server           *http.Server
	wg               sync.WaitGroup
	bundleHMACSecret []byte
	bundleSecretMode string

	workersMu  sync.Mutex
	workers    map[string]transport.Worker
	tcpServers map[string]*sharedTCPServer

	closeOnce sync.Once
	stopCh    chan struct{}
}

func New(cfg config.Config) (*App, error) {
	for _, dir := range []string{cfg.DataDir, cfg.ProfileDir, cfg.CaptureDir, cfg.BundleDir} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, err
		}
	}
	profiles := profile.NewStore(cfg.ProfileDir)
	if err := profiles.Ensure(); err != nil {
		return nil, err
	}
	captureStore, err := capture.Open(cfg.DBPath, cfg.CaptureDir)
	if err != nil {
		return nil, err
	}
	bundleSecret, bundleSecretMode, err := loadOrCreateBundleHMACSecret(cfg.DataDir, cfg.BundleHMACSecret)
	if err != nil {
		return nil, err
	}
	app := &App{cfg: cfg, profiles: profiles, captures: captureStore, processor: pipeline.New(), discovery: discovery.New(), learning: learning.New(), pendingOrders: orders.NewStore(), workers: map[string]transport.Worker{}, tcpServers: map[string]*sharedTCPServer{}, stopCh: make(chan struct{}), bundleHMACSecret: bundleSecret, bundleSecretMode: bundleSecretMode}
	if err := app.seedProfiles(); err != nil {
		return nil, err
	}
	if _, err := app.RunRetention(); err != nil {
		return nil, err
	}
	app.server = &http.Server{Addr: cfg.ListenAddr, Handler: api.New(app, api.Options{APIAuthToken: cfg.APIAuthToken, UIAssetsDir: cfg.UIAssetsDir}).Routes()}
	return app, nil
}

func (a *App) Start() error {
	a.wg.Add(1)
	go func() { defer a.wg.Done(); _ = a.server.ListenAndServe() }()
	if a.cfg.CleanupInterval > 0 {
		a.wg.Add(1)
		go a.runScheduledCleanup()
	}
	if a.cfg.AutoResume {
		a.Resume()
	}
	return nil
}

// Resume restarts capture sessions for any profile that was active before the
// engine last stopped. It is called automatically on Start when AutoResume is
// enabled and can also be triggered on demand.
func (a *App) Resume() []string {
	profileIDs, err := a.captures.ListResumableProfiles()
	if err != nil || len(profileIDs) == 0 {
		return nil
	}
	var resumed []string
	for _, id := range profileIDs {
		if _, err := a.StartCapture(id); err == nil {
			resumed = append(resumed, id)
		}
	}
	return resumed
}
func (a *App) Wait() error { a.wg.Wait(); return nil }
func (a *App) Close() error {
	a.closeOnce.Do(func() { close(a.stopCh); a.stopAllWorkers(); _ = a.server.Close() })
	return a.captures.Close()
}

func (a *App) runScheduledCleanup() {
	defer a.wg.Done()
	ticker := time.NewTicker(a.cfg.CleanupInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			report, err := a.RunRetention()
			if err != nil {
				a.recordError("runtime", "maintenance", models.TransportReplay, err, map[string]any{"stage": "scheduled_cleanup"}, map[string]any{"interval": a.cfg.CleanupInterval.String()})
				continue
			}
			if report.DeletedCaptures == 0 && report.DeletedCaptureFiles == 0 && report.DeletedRuntimeErrors == 0 && report.DeletedSessionEvents == 0 && report.DeletedUnmapped == 0 {
				continue
			}
			_ = a.captures.AppendSessionEvent("maintenance", "runtime", "maintenance", models.TransportReplay, "cleanup_completed", map[string]any{"deleted_captures": report.DeletedCaptures, "deleted_capture_files": report.DeletedCaptureFiles, "deleted_runtime_errors": report.DeletedRuntimeErrors, "deleted_session_events": report.DeletedSessionEvents, "deleted_unmapped_observations": report.DeletedUnmapped, "interval": a.cfg.CleanupInterval.String()})
		case <-a.stopCh:
			return
		}
	}
}

func (a *App) ListProfiles() ([]profile.Profile, error) { return a.profiles.List() }
func (a *App) SaveProfile(p profile.Profile) error      { return a.profiles.Save(p) }
func (a *App) ExportMigrationBundle(redaction models.RedactionOptions, actor string) (profile.MigrationBundle, error) {
	profiles, err := a.profiles.List()
	if err != nil {
		return profile.MigrationBundle{}, err
	}
	links, err := a.captures.ListAllNetworkDeviceLinks()
	if err != nil {
		return profile.MigrationBundle{}, err
	}
	preview, err := a.captures.PreviewNetworkLinkImport(nil)
	if err != nil {
		return profile.MigrationBundle{}, err
	}
	bundle := profile.MigrationBundle{
		Version:      "v1",
		ExportedAt:   time.Now().UTC(),
		Profiles:     profiles,
		NetworkLinks: links,
		Diagnostics:  preview.Diagnostics,
	}
	bundle = redactMigrationBundle(bundle, normalizeRedactionOptions(redaction))
	finalized, err := finalizeMigrationBundle(bundle, a.bundleHMACSecret)
	if err != nil {
		return profile.MigrationBundle{}, err
	}
	_ = a.captures.RecordNetworkLinkAudit(models.NetworkLinkAuditEntry{
		Action:    "migration_bundle_export",
		Actor:     strings.TrimSpace(actor),
		Detail:    map[string]any{"profile_count": len(finalized.Profiles), "link_count": len(finalized.NetworkLinks), "redaction": redaction, "redacted": hasRedaction(redaction)},
		CreatedAt: time.Now().UTC(),
	})
	return finalized, nil
}

func (a *App) BundleSecretStatus() (models.BundleSecretStatus, error) {
	mode := strings.TrimSpace(a.bundleSecretMode)
	if mode == "" {
		mode = "generated"
	}
	status := models.BundleSecretStatus{
		Algorithm:        "hmac-sha256",
		Mode:             mode,
		SharedConfigured: mode == "configured",
	}
	if status.SharedConfigured {
		status.Summary = "Using a shared configured HMAC secret for bundle signing."
	} else {
		status.Summary = "Using a locally generated HMAC secret stored under the data directory."
	}
	return status, nil
}

func (a *App) PreviewMigrationBundle(bundle profile.MigrationBundle) (profile.MigrationBundlePreview, error) {
	preview := profile.MigrationBundlePreview{}
	if err := verifyMigrationBundle(bundle, a.bundleHMACSecret); err != nil {
		preview.IntegrityError = err.Error()
	} else {
		preview.IntegrityValid = true
	}
	existing, err := a.profiles.List()
	if err != nil {
		return profile.MigrationBundlePreview{}, err
	}
	currentByID := map[string]profile.Profile{}
	for _, prof := range existing {
		currentByID[prof.ID] = prof
	}
	for _, incoming := range bundle.Profiles {
		current, ok := currentByID[incoming.ID]
		if !ok {
			preview.ProfileDiffs = append(preview.ProfileDiffs, profile.MigrationProfileDiff{ProfileID: incoming.ID, Status: "new"})
			continue
		}
		changedSections, changedFields, fieldChanges := diffProfile(current, incoming)
		status := "unchanged"
		if len(changedSections) > 0 {
			status = "changed"
		}
		preview.ProfileDiffs = append(preview.ProfileDiffs, profile.MigrationProfileDiff{ProfileID: incoming.ID, Status: status, ChangedSections: changedSections, ChangedFields: changedFields, FieldChanges: fieldChanges})
	}
	linkPreview, err := a.captures.PreviewNetworkLinkImport(bundle.NetworkLinks)
	if err != nil {
		return profile.MigrationBundlePreview{}, err
	}
	preview.LinkPreview = linkPreview
	return preview, nil
}
func (a *App) ImportMigrationBundle(bundle profile.MigrationBundle, actor string, merges []models.NetworkLinkMergeDecision) error {
	if err := verifyMigrationBundle(bundle, a.bundleHMACSecret); err != nil {
		return err
	}
	for _, prof := range bundle.Profiles {
		if strings.TrimSpace(prof.ID) == "" {
			continue
		}
		if err := a.profiles.Save(prof); err != nil {
			return err
		}
	}
	_ = a.captures.RecordNetworkLinkAudit(models.NetworkLinkAuditEntry{
		Action:    "migration_bundle_import_previewed",
		Actor:     strings.TrimSpace(actor),
		Detail:    map[string]any{"integrity_algorithm": bundle.Integrity.Algorithm, "profile_count": len(bundle.Profiles), "link_count": len(bundle.NetworkLinks)},
		CreatedAt: time.Now().UTC(),
	})
	if err := a.ImportNetworkLinks(bundle.NetworkLinks, false, merges, actor); err != nil {
		return err
	}
	return a.captures.RecordNetworkLinkAudit(models.NetworkLinkAuditEntry{
		Action:    "migration_bundle_import",
		Actor:     strings.TrimSpace(actor),
		Detail:    map[string]any{"profile_count": len(bundle.Profiles), "link_count": len(bundle.NetworkLinks), "merge_count": len(merges), "redacted": bundleLikelyRedacted(bundle)},
		CreatedAt: time.Now().UTC(),
	})
}
func (a *App) ScanPorts(req models.NetworkScanRequest) ([]models.DeviceFingerprint, []transport.SerialCandidate, []models.NetworkDevice, models.NetworkScanDiagnostics, error) {
	started := time.Now()
	ports, err := a.discovery.ScanSerialPorts()
	if err != nil {
		return nil, nil, nil, models.NetworkScanDiagnostics{}, err
	}
	networkDevices := []models.NetworkDevice{}
	diagnostics := models.NetworkScanDiagnostics{Mode: scanMode(req.Mode), SerialDevices: len(ports)}
	if a.cfg.NetworkDiscoveryEnabled {
		cidrs := a.discoveryCIDRs(req.CIDRs)
		probePorts, profilePortCount := a.discoveryPorts(req.Ports)
		hostLimit := a.discoveryHostLimit(req)
		scanned, err := a.discovery.ScanNetwork(discovery.NetworkScanOptions{CIDRs: cidrs, Ports: probePorts, Timeout: a.cfg.NetworkProbeTimeout, Concurrency: a.cfg.NetworkScanConcurrency, HostLimit: hostLimit})
		if err != nil {
			return nil, nil, nil, diagnostics, err
		}
		networkDevices, err = a.captures.UpsertNetworkDevices(scanned.Devices)
		if err != nil {
			return nil, nil, nil, diagnostics, err
		}
		diagnostics.CIDRs = scanned.CIDRs
		diagnostics.Ports = scanned.Ports
		diagnostics.HostLimit = scanned.HostLimit
		diagnostics.CandidateHosts = scanned.CandidateHosts
		diagnostics.DurationMS = scanned.Duration.Milliseconds()
		diagnostics.NetworkDevices = len(networkDevices)
		diagnostics.ProfilePortCount = profilePortCount
		diagnostics.Warnings, diagnostics.Recommendations = discoveryGuidance(diagnostics, len(req.CIDRs) > 0, len(req.Ports) > 0)
	} else {
		diagnostics.Warnings = []string{"Network discovery is disabled in configuration."}
	}
	if diagnostics.DurationMS == 0 {
		diagnostics.DurationMS = time.Since(started).Milliseconds()
	}
	return ports, transport.CommonSerialCandidates(), networkDevices, diagnostics, nil
}
func (a *App) RuntimeSnapshot(limit int) (capture.RuntimeSnapshot, error) {
	return a.captures.RuntimeSnapshot(limit, limit)
}
func (a *App) RuntimeErrors(limit int) ([]capture.RuntimeError, error) {
	return a.captures.ListRuntimeErrors(limit)
}
func (a *App) SessionHistory(filter capture.SessionEventFilter) ([]capture.SessionEvent, error) {
	return a.captures.ListSessionEvents(filter)
}

func (a *App) RunRetention() (capture.CleanupReport, error) {
	report, err := a.captures.ApplyRetention(capture.RetentionPolicy{RetentionDays: a.cfg.RetentionDays, SessionEventMax: a.cfg.SessionEventMax, RuntimeErrorMax: a.cfg.RuntimeErrorMax, CaptureMax: a.cfg.CaptureMax})
	if err != nil {
		return capture.CleanupReport{}, err
	}
	_ = a.captures.UpdateMaintenanceStatus(&report, a.nextCleanupTime(), a.cleanupIntervalString())
	return report, nil
}

func (a *App) ProcessPayload(raw []byte, transportType models.TransportType, profileID string, deviceID string) (models.ParseResult, capture.CaptureRecord, error) {
	resolvedProfileID := profileID
	if resolvedProfileID == "" {
		resolvedProfileID = "generic-hl7"
	}
	prof, err := a.profiles.Get(resolvedProfileID)
	if err != nil {
		a.recordError(resolvedProfileID, deviceID, transportType, err, map[string]any{"stage": "load_profile"}, nil)
		return models.ParseResult{}, capture.CaptureRecord{}, err
	}
	result, err := a.processor.Process(raw, transportType, deviceID, prof, "")
	if err != nil {
		a.recordError(prof.ID, deviceID, transportType, err, map[string]any{"stage": "process_payload"}, prof.Transport)
		return models.ParseResult{}, capture.CaptureRecord{}, err
	}
	rec, err := a.captures.SaveRaw(prof.ID, deviceID, transportType, raw, result.Payload.DecodedText, result.Payload.NormalizedText, result.Classification)
	if err != nil {
		a.recordError(prof.ID, deviceID, transportType, err, map[string]any{"stage": "save_raw"}, prof.Transport)
		return models.ParseResult{}, capture.CaptureRecord{}, err
	}
	_ = a.linkRuntimeDevice(prof.ID, deviceID, prof.Transport, "payload")
	result.Message.RawPayloadRef = rec.RawPath
	if err := a.captures.SaveParsed(rec.ID, result); err != nil {
		a.recordError(prof.ID, deviceID, transportType, err, map[string]any{"stage": "save_parsed", "capture_id": rec.ID}, prof.Transport)
		return models.ParseResult{}, capture.CaptureRecord{}, err
	}
	if err := a.captures.RecordProcessingSuccess(prof.ID, deviceID, transportType, result.Classification.Selected, rec.ID, prof.Transport, result.Message.Observations, rec.ReceivedAt); err != nil {
		a.recordError(prof.ID, deviceID, transportType, err, map[string]any{"stage": "record_processing_success", "capture_id": rec.ID}, prof.Transport)
	}
	if err := a.captures.UpsertResult(result.Message, rec.ID, rec.ReceivedAt); err != nil {
		a.recordError(prof.ID, deviceID, transportType, err, map[string]any{"stage": "upsert_result", "capture_id": rec.ID}, prof.Transport)
	}
	return result, rec, nil
}

func (a *App) ListCaptures(filter capture.CaptureFilter) ([]capture.CaptureRecord, error) {
	return a.captures.ListCaptures(filter)
}
func (a *App) SaveNetworkLink(link models.NetworkDeviceLink, override bool, actor string) error {
	now := time.Now().UTC()
	link.FirstSeen = now
	link.LastSeen = now
	if link.SeenCount < 1 {
		link.SeenCount = 1
	}
	if link.Confidence <= 0 {
		switch strings.ToLower(strings.TrimSpace(link.Source)) {
		case "manual_override", "manual_import":
			link.Confidence = 0.98
		case "payload":
			link.Confidence = 0.84
		case "profile_transport":
			link.Confidence = 0.62
		default:
			link.Confidence = 0.5
		}
	}
	if override {
		if err := a.captures.ReplaceNetworkDeviceLinks(link.NetworkDeviceID, link.ProfileID, []models.NetworkDeviceLink{link}); err != nil {
			return err
		}
		return a.auditNetworkLink("manual_override", actor, link, map[string]any{"override": true})
	}
	if err := a.captures.UpsertNetworkDeviceLinks([]models.NetworkDeviceLink{link}); err != nil {
		return err
	}
	return a.auditNetworkLink("manual_confirm", actor, link, map[string]any{"override": false})
}
func (a *App) DeleteNetworkLink(networkDeviceID, profileID, runtimeDeviceID string) error {
	return a.captures.DeleteNetworkDeviceLink(networkDeviceID, profileID, runtimeDeviceID)
}
func (a *App) DeleteNetworkLinkWithActor(networkDeviceID, profileID, runtimeDeviceID, actor string) error {
	if err := a.captures.DeleteNetworkDeviceLink(networkDeviceID, profileID, runtimeDeviceID); err != nil {
		return err
	}
	return a.captures.RecordNetworkLinkAudit(models.NetworkLinkAuditEntry{
		Action:          "manual_delete",
		Actor:           actor,
		NetworkDeviceID: networkDeviceID,
		ProfileID:       profileID,
		RuntimeDeviceID: runtimeDeviceID,
		CreatedAt:       time.Now().UTC(),
	})
}
func (a *App) ExportNetworkLinks() ([]models.NetworkDeviceLink, error) {
	return a.captures.ListAllNetworkDeviceLinks()
}
func (a *App) PreviewNetworkLinkImport(links []models.NetworkDeviceLink) (models.NetworkLinkImportPreview, error) {
	return a.captures.PreviewNetworkLinkImport(links)
}
func (a *App) ListNetworkLinkAudit(filter models.NetworkLinkAuditFilter) ([]models.NetworkLinkAuditEntry, error) {
	return a.captures.ListNetworkLinkAudit(filter)
}
func (a *App) ImportNetworkLinks(links []models.NetworkDeviceLink, replace bool, merges []models.NetworkLinkMergeDecision, actor string) error {
	normalized := make([]models.NetworkDeviceLink, 0, len(links))
	now := time.Now().UTC()
	for _, link := range links {
		if strings.TrimSpace(link.NetworkDeviceID) == "" || strings.TrimSpace(link.ProfileID) == "" || strings.TrimSpace(link.RuntimeDeviceID) == "" {
			continue
		}
		link.Source = "manual_import"
		if link.FirstSeen.IsZero() {
			link.FirstSeen = now
		}
		if link.LastSeen.IsZero() {
			link.LastSeen = now
		}
		if link.SeenCount < 1 {
			link.SeenCount = 1
		}
		if link.Confidence <= 0 {
			link.Confidence = 0.98
		}
		normalized = append(normalized, link)
	}
	if len(normalized) == 0 {
		return nil
	}
	if !replace && len(merges) == 0 {
		preview, err := a.captures.PreviewNetworkLinkImport(normalized)
		if err != nil {
			return err
		}
		if len(preview.Conflicts) > 0 {
			return fmt.Errorf("import contains %d conflicts; preview and choose merge decisions before importing", len(preview.Conflicts))
		}
	}
	if len(merges) > 0 {
		preview, err := a.captures.PreviewNetworkLinkImport(normalized)
		if err != nil {
			return err
		}
		decisions := map[string]string{}
		for _, merge := range merges {
			decisions[strings.TrimSpace(merge.ConflictID)] = strings.ToLower(strings.TrimSpace(merge.Resolution))
		}
		mergeTargets := map[string]models.NetworkDeviceLink{}
		for _, conflict := range preview.Conflicts {
			switch decisions[conflict.ConflictID] {
			case "", "keep_existing", "skip":
				continue
			case "use_imported", "replace_existing":
				key := conflict.Incoming.NetworkDeviceID + "|" + conflict.Incoming.ProfileID + "|" + conflict.Incoming.RuntimeDeviceID
				mergeTargets[key] = conflict.Incoming
			}
		}
		for _, link := range preview.SafeLinks {
			key := link.NetworkDeviceID + "|" + link.ProfileID + "|" + link.RuntimeDeviceID
			mergeTargets[key] = link
		}
		for _, link := range mergeTargets {
			if err := a.captures.ApplyNetworkLinkMerge(link); err != nil {
				return err
			}
			_ = a.auditNetworkLink("merge_import", actor, link, map[string]any{"merge_resolution": "use_imported"})
		}
		return nil
	}
	if replace {
		grouped := map[string][]models.NetworkDeviceLink{}
		for _, link := range normalized {
			key := link.NetworkDeviceID + "|" + link.ProfileID
			grouped[key] = append(grouped[key], link)
		}
		for key, group := range grouped {
			parts := strings.SplitN(key, "|", 2)
			if err := a.captures.ReplaceNetworkDeviceLinks(parts[0], parts[1], group); err != nil {
				return err
			}
			for _, link := range group {
				_ = a.auditNetworkLink("replace_import", actor, link, map[string]any{"replace": true})
			}
		}
		return nil
	}
	if err := a.captures.UpsertNetworkDeviceLinks(normalized); err != nil {
		return err
	}
	for _, link := range normalized {
		_ = a.auditNetworkLink("manual_import", actor, link, map[string]any{"replace": false})
	}
	return nil
}
func (a *App) ReplayCapture(id, overrideProfileID string) (models.ParseResult, error) {
	rec, raw, err := a.captures.GetCapture(id)
	if err != nil {
		return models.ParseResult{}, err
	}
	profileID := rec.ProfileID
	if overrideProfileID != "" {
		profileID = overrideProfileID
	}
	result, _, err := a.ProcessPayload(raw, models.TransportReplay, profileID, rec.DeviceID)
	networkDeviceID := resolveNetworkDeviceID(rec.DeviceID, nil)
	if networkDeviceID == "" {
		linkedID, lookupErr := a.captures.FindNetworkDeviceID(profileID, rec.DeviceID)
		if lookupErr == nil {
			networkDeviceID = linkedID
		}
	}
	if err != nil {
		_ = a.captures.RecordReplayEvent(networkDeviceID, rec.ID, profileID, rec.DeviceID, "error", err.Error())
		return result, err
	}
	_ = a.captures.SaveParsed(rec.ID, result)
	_ = a.captures.RecordReplayEvent(networkDeviceID, rec.ID, profileID, rec.DeviceID, "success", string(result.Classification.Selected))
	return result, nil
}
func (a *App) ReplayFile(path, profileID string) (ReplayOutput, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return ReplayOutput{}, err
	}
	result, _, err := a.ProcessPayload(raw, models.TransportReplay, profileID, filepath.Base(path))
	if err != nil {
		return ReplayOutput{}, err
	}
	return ReplayOutput{Result: result}, nil
}

func (a *App) StartCapture(profileID string) (string, error) {
	prof, err := a.loadProfile(profileID)
	if err != nil {
		return "", err
	}
	transportType := models.TransportType(prof.Transport.Type)
	if transportType == models.TransportTCPServer {
		return a.startSharedTCPServerCapture(prof)
	}
	deviceID := transportDeviceID(prof)
	sessionID, err := a.captures.StartSession(prof.ID, transportType)
	if err != nil {
		return "", err
	}
	_ = a.linkRuntimeDevice(prof.ID, deviceID, prof.Transport, "profile_transport")
	_ = a.captures.UpdateRuntimeState(prof.ID, deviceID, transportType, sessionID, "starting", prof.Transport)
	_ = a.captures.AppendSessionEvent(sessionID, prof.ID, deviceID, transportType, "starting", map[string]any{"source": "runtime"})
	worker, err := transport.StartProfileWorker(prof, func(raw []byte, observedDeviceID string, observedTransport models.TransportType) error {
		_, _, err := a.ProcessPayload(raw, observedTransport, prof.ID, observedDeviceID)
		return err
	}, func(workerErr error, detail map[string]any) {
		a.recordError(prof.ID, deviceID, transportType, workerErr, detail, prof.Transport)
	}, func(state string, meta map[string]any) {
		_ = a.captures.UpdateSessionState(sessionID, state)
		_ = a.captures.UpdateRuntimeState(prof.ID, deviceID, transportType, sessionID, state, prof.Transport)
		_ = a.captures.AppendSessionEvent(sessionID, prof.ID, deviceID, transportType, state, meta)
	}, a.makeQueryHandler(prof))
	if err != nil {
		_ = a.captures.StopSession(sessionID)
		_ = a.captures.UpdateRuntimeState(prof.ID, deviceID, transportType, sessionID, "error", prof.Transport)
		_ = a.captures.AppendSessionEvent(sessionID, prof.ID, deviceID, transportType, "error", map[string]any{"stage": "start_worker", "message": err.Error()})
		a.recordError(prof.ID, deviceID, transportType, err, map[string]any{"stage": "start_worker"}, prof.Transport)
		return "", err
	}
	a.workersMu.Lock()
	a.workers[sessionID] = worker
	a.workersMu.Unlock()
	return sessionID, nil
}

func (a *App) StopCapture(sessionID string) error {
	a.stopWorker(sessionID)
	_ = a.captures.UpdateSessionState(sessionID, "stopped")
	return a.captures.StopSession(sessionID)
}
func (a *App) SuggestLearning(rawText, profileID, captureID string) (learning.Suggestion, error) {
	suggestion := a.learning.Suggest(rawText)
	if captureID != "" {
		_ = a.captures.SaveLearningSuggestions(profileID, captureID, suggestion)
	}
	return suggestion, nil
}

func (a *App) BuildSupportBundle() (string, []byte, error) {
	captures, err := a.captures.ListCaptures(capture.CaptureFilter{Limit: 25})
	if err != nil {
		return "", nil, err
	}
	profiles, err := a.profiles.List()
	if err != nil {
		return "", nil, err
	}
	runtimeSnapshot, err := a.captures.RuntimeSnapshot(50, 50)
	if err != nil {
		return "", nil, err
	}
	networkLinks, err := a.captures.ListAllNetworkDeviceLinks()
	if err != nil {
		return "", nil, err
	}
	networkLinkSummary, err := a.captures.PreviewNetworkLinkImport(nil)
	if err != nil {
		return "", nil, err
	}
	runtimeErrors, err := a.captures.ListRuntimeErrors(100)
	if err != nil {
		return "", nil, err
	}
	sessionEvents, err := a.captures.ListSessionEvents(capture.SessionEventFilter{Limit: 200})
	if err != nil {
		return "", nil, err
	}
	networkLinkAudit, err := a.captures.ListNetworkLinkAudit(models.NetworkLinkAuditFilter{Limit: 200})
	if err != nil {
		return "", nil, err
	}
	secretStatus, err := a.BundleSecretStatus()
	if err != nil {
		return "", nil, err
	}
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	writeBundleJSON(zw, "captures.json", captures)
	writeBundleJSON(zw, "profiles.json", profiles)
	writeBundleJSON(zw, "runtime-status.json", runtimeSnapshot)
	writeBundleJSON(zw, "network-links.json", networkLinks)
	writeBundleJSON(zw, "network-link-summary.json", networkLinkSummary.Diagnostics)
	writeBundleJSON(zw, "network-link-audit.json", networkLinkAudit)
	writeBundleJSON(zw, "bundle-secret-status.json", secretStatus)
	writeBundleJSON(zw, "runtime-errors.json", runtimeErrors)
	writeBundleJSON(zw, "session-history.json", sessionEvents)
	_ = zw.Close()
	return fmt.Sprintf("instrument-support-%s.zip", time.Now().UTC().Format("20060102-150405")), buf.Bytes(), nil
}

func (a *App) nextCleanupTime() *time.Time {
	if a.cfg.CleanupInterval <= 0 {
		return nil
	}
	next := time.Now().UTC().Add(a.cfg.CleanupInterval)
	return &next
}
func (a *App) cleanupIntervalString() string {
	if a.cfg.CleanupInterval <= 0 {
		return "disabled"
	}
	return a.cfg.CleanupInterval.String()
}
func writeBundleJSON(zw *zip.Writer, name string, value any) {
	w, err := zw.Create(name)
	if err != nil {
		return
	}
	raw, _ := json.MarshalIndent(value, "", "  ")
	_, _ = w.Write(raw)
}

func (a *App) seedProfiles() error {
	existing, err := a.profiles.List()
	if err != nil {
		return err
	}
	if len(existing) > 0 {
		return nil
	}
	seeds := []profile.Profile{
		{ID: "generic-hl7", Name: "Generic HL7 Instrument", ProtocolHint: "hl7_v2", Transport: profile.TransportSettings{Type: "tcp_client", RemoteAddress: "127.0.0.1:5000", DiscoveryPorts: []int{5000, 2575}, DiscoveryHints: []string{"hl7_listener"}}, Parsing: profile.ParsingSettings{Strategy: "hl7_oru"}, Mapping: profile.MappingSettings{UnitNormalization: map[string]string{"10^3/uL": "10^3/uL", "g/dL": "g/dL"}}, LearningSettings: profile.LearningSettings{Enabled: true}},
		{ID: "generic-astm", Name: "Generic ASTM Instrument", ProtocolHint: "astm", Transport: profile.TransportSettings{Type: "serial", SessionMode: "astm", BaudRate: 9600, DataBits: 8, Parity: "N", StopBits: 1, DiscoveryHints: []string{"astm_serial"}}, Parsing: profile.ParsingSettings{Strategy: "astm"}, Mapping: profile.MappingSettings{UnitNormalization: map[string]string{"mg/dl": "mg/dL", "mmol/l": "mmol/L"}}, LearningSettings: profile.LearningSettings{Enabled: true}},
		{ID: "generic-csv-filedrop", Name: "Generic CSV File Drop", ProtocolHint: "csv", Transport: profile.TransportSettings{Type: "file_drop", WatchDirectories: []string{"incoming"}, DiscoveryHints: []string{"file_drop"}}, Parsing: profile.ParsingSettings{Strategy: "csv", Delimiter: ","}, Mapping: profile.MappingSettings{UnitNormalization: map[string]string{"mg/dl": "mg/dL"}}, LearningSettings: profile.LearningSettings{Enabled: true}},
	}
	for _, seed := range seeds {
		if err := a.profiles.Save(seed); err != nil {
			return err
		}
	}
	return nil
}
func (a *App) loadProfile(profileID string) (profile.Profile, error) {
	if profileID == "" {
		profileID = "generic-hl7"
	}
	return a.profiles.Get(profileID)
}

// PushPendingOrder stores an order in the pending orders store so the engine can
// respond to ASTM host queries (Q records) from bidirectional analyzers.
func (a *App) PushPendingOrder(req models.PendingOrderRequest) error {
	if strings.TrimSpace(req.SampleID) == "" {
		return fmt.Errorf("sample_id is required")
	}
	tests := make([]orders.PendingTest, 0, len(req.Tests))
	for _, t := range req.Tests {
		tests = append(tests, orders.PendingTest{TestCode: t.TestCode, TestName: t.TestName})
	}
	a.pendingOrders.Put(orders.PendingOrder{
		SampleID:    strings.TrimSpace(req.SampleID),
		PatientID:   req.PatientID,
		PatientName: req.PatientName,
		DOB:         req.DOB,
		Sex:         req.Sex,
		DoctorName:  req.DoctorName,
		Tests:       tests,
		ProfileID:   req.ProfileID,
	})
	return nil
}

// ListPendingOrders returns all non-expired pending orders as PendingOrderRequests.
func (a *App) ListPendingOrders() []models.PendingOrderRequest {
	all := a.pendingOrders.List()
	out := make([]models.PendingOrderRequest, 0, len(all))
	for _, o := range all {
		tests := make([]models.PendingTestRequest, 0, len(o.Tests))
		for _, t := range o.Tests {
			tests = append(tests, models.PendingTestRequest{TestCode: t.TestCode, TestName: t.TestName})
		}
		out = append(out, models.PendingOrderRequest{
			SampleID:    o.SampleID,
			PatientID:   o.PatientID,
			PatientName: o.PatientName,
			DOB:         o.DOB,
			Sex:         o.Sex,
			DoctorName:  o.DoctorName,
			Tests:       tests,
			ProfileID:   o.ProfileID,
		})
	}
	return out
}

// DeletePendingOrder removes the order for sampleID from the store.
func (a *App) DeletePendingOrder(sampleID string) {
	a.pendingOrders.Delete(strings.TrimSpace(sampleID))
}

// makeQueryHandler returns an ASTM QueryHandler for profiles that use ASTM framing.
// For non-ASTM profiles it returns nil so the worker skips Q-record handling.
func (a *App) makeQueryHandler(prof profile.Profile) transport.QueryHandler {
	if transport.SelectSessionMode(prof) != "astm" {
		return nil
	}
	return func(sampleID string, rw io.ReadWriter) {
		order, found := a.pendingOrders.Get(sampleID)
		records := buildASTMOrderResponseRecords(sampleID, found, order)
		if err := transport.SendASTMResponse(rw, records); err != nil {
			a.recordError(prof.ID, "astm_query", models.TransportTCPServer, err,
				map[string]any{"stage": "astm_query_response", "sample_id": sampleID}, prof.Transport)
		} else if found {
			a.pendingOrders.Delete(sampleID)
		}
	}
}

// buildASTMOrderResponseRecords builds the ASTM H+[P+O...]+L record bodies
// for a query response. If no order is found it returns an empty H+L (no work list).
func buildASTMOrderResponseRecords(sampleID string, found bool, order orders.PendingOrder) []string {
	now := time.Now().Format("20060102150405")
	seq := 1
	records := []string{fmt.Sprintf("%dH|\\^&|||SPDXLIMS|||||||P|LIS2-A2|%s", seq, now)}
	seq++

	if found {
		// Format patient name as "LASTNAME^FIRSTNAME"
		name := strings.ReplaceAll(strings.TrimSpace(order.PatientName), " ", "^")
		dob := strings.ReplaceAll(order.DOB, "-", "")
		sex := strings.ToUpper(strings.TrimSpace(order.Sex))
		if len(sex) > 1 {
			sex = sex[:1]
		}
		if order.PatientID != "" || name != "" {
			records = append(records, fmt.Sprintf("%dP|1||%s|||%s||%s|%s",
				seq, order.PatientID, name, dob, sex))
			seq++
		}
		for i, t := range order.Tests {
			records = append(records, fmt.Sprintf("%dO|%d|%s||^^^%s|R|||||||N|||||",
				seq, i+1, sampleID, t.TestCode))
			seq++
		}
	}

	records = append(records, fmt.Sprintf("%dL|1|N", seq))
	return records
}
func (a *App) recordError(profileID, deviceID string, transportType models.TransportType, err error, detail map[string]any, selectedSettings any) {
	if deviceID == "" {
		deviceID = "manual-input"
	}
	_ = a.captures.RecordProcessingError(profileID, deviceID, transportType, err.Error(), selectedSettings, detail)
}
func (a *App) stopWorker(sessionID string) {
	a.workersMu.Lock()
	worker := a.workers[sessionID]
	delete(a.workers, sessionID)
	a.workersMu.Unlock()
	if worker != nil {
		_ = worker.Stop()
	}
}
func (a *App) stopAllWorkers() {
	a.workersMu.Lock()
	workers := make([]transport.Worker, 0, len(a.workers))
	for _, worker := range a.workers {
		workers = append(workers, worker)
	}
	a.workers = map[string]transport.Worker{}
	a.workersMu.Unlock()
	for _, worker := range workers {
		_ = worker.Stop()
	}
}

func transportDeviceID(prof profile.Profile) string {
	switch models.TransportType(prof.Transport.Type) {
	case models.TransportTCPClient:
		if prof.Transport.RemoteAddress != "" {
			return prof.Transport.RemoteAddress
		}
	case models.TransportTCPServer:
		if prof.Transport.ListenAddress != "" {
			return prof.Transport.ListenAddress
		}
	case models.TransportFileDrop:
		if len(prof.Transport.WatchDirectories) > 0 {
			return prof.Transport.WatchDirectories[0]
		}
	case models.TransportSerial:
		if prof.Transport.SerialPort != "" {
			return prof.Transport.SerialPort
		}
	}
	return prof.ID
}

func scanMode(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "full":
		return "full"
	case "custom":
		return "custom"
	default:
		return "quick"
	}
}

func (a *App) discoveryHostLimit(req models.NetworkScanRequest) int {
	if req.HostLimit > 0 {
		return req.HostLimit
	}
	switch scanMode(req.Mode) {
	case "full":
		return 254
	default:
		return a.cfg.NetworkScanHostLimit
	}
}

func (a *App) discoveryPorts(extra []int) ([]int, int) {
	portSet := map[int]struct{}{}
	profilePortSet := map[int]struct{}{}
	for _, port := range a.cfg.NetworkProbePorts {
		if port > 0 && port <= 65535 {
			portSet[port] = struct{}{}
		}
	}
	for _, port := range extra {
		if port > 0 && port <= 65535 {
			portSet[port] = struct{}{}
		}
	}
	profiles, err := a.profiles.List()
	if err == nil {
		for _, prof := range profiles {
			for _, port := range prof.Transport.DiscoveryPorts {
				if port > 0 && port <= 65535 {
					portSet[port] = struct{}{}
					profilePortSet[port] = struct{}{}
				}
			}
			for _, port := range discoveryHintPorts(prof.Transport.DiscoveryHints) {
				portSet[port] = struct{}{}
				profilePortSet[port] = struct{}{}
			}
			for _, rawAddress := range []string{prof.Transport.RemoteAddress, prof.Transport.ListenAddress} {
				if port, ok := addressPort(rawAddress); ok {
					portSet[port] = struct{}{}
					profilePortSet[port] = struct{}{}
				}
			}
		}
	}
	ports := make([]int, 0, len(portSet))
	for port := range portSet {
		ports = append(ports, port)
	}
	sort.Ints(ports)
	return ports, len(profilePortSet)
}

func discoveryGuidance(d models.NetworkScanDiagnostics, explicitCIDRs, explicitPorts bool) ([]string, []string) {
	warnings := []string{}
	recommendations := []string{}
	if len(d.CIDRs) == 0 {
		warnings = append(warnings, "No private IPv4 subnet was available for automatic scanning.")
		recommendations = append(recommendations, "Enter the analyzer subnet manually, such as 10.0.0.0/24.")
	}
	if d.Mode == "quick" && d.CandidateHosts > 0 && d.HostLimit < 254 {
		recommendations = append(recommendations, fmt.Sprintf("Quick scan checked up to %d hosts per subnet. Use Full subnet scan if the analyzer may have a higher address.", d.HostLimit))
	}
	if !explicitPorts && d.ProfilePortCount == 0 {
		recommendations = append(recommendations, "Add discovery hints or profile ports for the analyzer family so scans include its LIS port.")
	}
	if d.NetworkDevices == 0 && d.CandidateHosts > 0 {
		warnings = append(warnings, "No TCP endpoints responded on the scanned ports.")
		recommendations = append(recommendations, "Confirm the analyzer IP, LIS port, cable/VLAN, and Windows firewall rules, then try a targeted scan.")
	}
	if explicitCIDRs || explicitPorts {
		recommendations = append(recommendations, "Save successful CIDRs and ports into the matching profile so future quick scans include them.")
	}
	return warnings, recommendations
}

func discoveryHintPorts(hints []string) []int {
	portSet := map[int]struct{}{}
	for _, hint := range hints {
		switch strings.ToLower(strings.TrimSpace(hint)) {
		case "hl7_listener":
			for _, port := range []int{2575, 3001, 4000, 5000} {
				portSet[port] = struct{}{}
			}
		case "http_admin":
			for _, port := range []int{80, 8000, 8080, 8081, 8888} {
				portSet[port] = struct{}{}
			}
		case "raw_socket":
			portSet[9100] = struct{}{}
		case "line_admin":
			portSet[21] = struct{}{}
			portSet[23] = struct{}{}
		}
	}
	ports := make([]int, 0, len(portSet))
	for port := range portSet {
		ports = append(ports, port)
	}
	sort.Ints(ports)
	return ports
}

func discoveryHintCatalog() []map[string]any {
	return []map[string]any{
		{"id": "hl7_listener", "label": "HL7 Listener", "ports": []int{2575, 3001, 4000, 5000}, "description": "Common HL7/MLLP listener ports."},
		{"id": "http_admin", "label": "HTTP Admin", "ports": []int{80, 8000, 8080, 8081, 8888}, "description": "Common embedded HTTP admin ports."},
		{"id": "raw_socket", "label": "Raw Socket", "ports": []int{9100}, "description": "Simple raw socket listener ports."},
		{"id": "line_admin", "label": "Line Admin", "ports": []int{21, 23}, "description": "Classic line-oriented admin ports used by narrow greeting probes."},
		{"id": "astm_serial", "label": "ASTM Serial", "ports": []int{}, "description": "Serial-only hint; does not expand network ports."},
		{"id": "file_drop", "label": "File Drop", "ports": []int{}, "description": "File-drop hint; does not expand network ports."},
	}
}

func (a *App) auditNetworkLink(action, actor string, link models.NetworkDeviceLink, detail map[string]any) error {
	return a.captures.RecordNetworkLinkAudit(models.NetworkLinkAuditEntry{
		Action:          action,
		Actor:           strings.TrimSpace(actor),
		NetworkDeviceID: link.NetworkDeviceID,
		ProfileID:       link.ProfileID,
		RuntimeDeviceID: link.RuntimeDeviceID,
		Source:          link.Source,
		Confidence:      link.Confidence,
		Detail:          detail,
		CreatedAt:       time.Now().UTC(),
	})
}

func finalizeMigrationBundle(bundle profile.MigrationBundle, secret []byte) (profile.MigrationBundle, error) {
	bundle.Integrity = profile.MigrationBundleIntegrity{}
	raw, err := json.Marshal(bundle)
	if err != nil {
		return profile.MigrationBundle{}, err
	}
	sum := sha256.Sum256(raw)
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write(raw)
	bundle.Integrity = profile.MigrationBundleIntegrity{
		Algorithm:     "hmac-sha256",
		PayloadSHA256: fmt.Sprintf("%x", sum[:]),
		Signature:     fmt.Sprintf("%x", mac.Sum(nil)),
	}
	return bundle, nil
}

func verifyMigrationBundle(bundle profile.MigrationBundle, secret []byte) error {
	expected := strings.TrimSpace(bundle.Integrity.PayloadSHA256)
	if expected == "" {
		return fmt.Errorf("migration bundle is missing payload_sha256")
	}
	algorithm := strings.ToLower(strings.TrimSpace(bundle.Integrity.Algorithm))
	if algorithm != "hmac-sha256" {
		return fmt.Errorf("unsupported migration bundle integrity algorithm %q", bundle.Integrity.Algorithm)
	}
	candidate := bundle
	candidate.Integrity = profile.MigrationBundleIntegrity{}
	raw, err := json.Marshal(candidate)
	if err != nil {
		return err
	}
	sum := sha256.Sum256(raw)
	actual := fmt.Sprintf("%x", sum[:])
	if actual != expected {
		return fmt.Errorf("migration bundle checksum mismatch")
	}
	signature := strings.TrimSpace(bundle.Integrity.Signature)
	if signature == "" {
		return fmt.Errorf("migration bundle is missing signature")
	}
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write(raw)
	actualSig := fmt.Sprintf("%x", mac.Sum(nil))
	if !hmac.Equal([]byte(actualSig), []byte(signature)) {
		return fmt.Errorf("migration bundle HMAC signature mismatch")
	}
	return nil
}

func normalizeRedactionOptions(options models.RedactionOptions) models.RedactionOptions {
	switch strings.ToLower(strings.TrimSpace(options.Preset)) {
	case "external_share":
		options.RedactActors = true
		options.RedactNetworkEndpoints = true
		options.RedactRuntimeDeviceIDs = true
		options.RedactProfileTransports = true
		options.RedactDeviceMetadata = true
	case "transport_only":
		options.RedactProfileTransports = true
	case "metadata_only":
		options.RedactDeviceMetadata = true
	case "identifiers_only":
		options.RedactNetworkEndpoints = true
		options.RedactRuntimeDeviceIDs = true
	}
	return options
}

func redactMigrationBundle(bundle profile.MigrationBundle, options models.RedactionOptions) profile.MigrationBundle {
	if !hasRedaction(options) {
		return bundle
	}
	profilesOut := make([]profile.Profile, 0, len(bundle.Profiles))
	for _, prof := range bundle.Profiles {
		profilesOut = append(profilesOut, redactProfile(prof, options))
	}
	linksOut := make([]models.NetworkDeviceLink, 0, len(bundle.NetworkLinks))
	for _, link := range bundle.NetworkLinks {
		linksOut = append(linksOut, redactNetworkLink(link, options))
	}
	bundle.Profiles = profilesOut
	bundle.NetworkLinks = linksOut
	return bundle
}

func bundleLikelyRedacted(bundle profile.MigrationBundle) bool {
	for _, prof := range bundle.Profiles {
		if strings.Contains(prof.Transport.SerialPort, "[redacted:") || strings.Contains(prof.Transport.ListenAddress, "[redacted:") || strings.Contains(prof.Transport.RemoteAddress, "[redacted:") {
			return true
		}
		for _, dir := range prof.Transport.WatchDirectories {
			if strings.Contains(dir, "[redacted:") {
				return true
			}
		}
		for _, cidr := range prof.Transport.DiscoveryCIDRs {
			if strings.Contains(cidr, "[redacted:") {
				return true
			}
		}
		for _, value := range prof.DeviceMetadata {
			if strings.Contains(value, "[redacted:") {
				return true
			}
		}
	}
	for _, link := range bundle.NetworkLinks {
		if strings.Contains(link.NetworkDeviceID, "[redacted:") || strings.Contains(link.RuntimeDeviceID, "[redacted:") {
			return true
		}
	}
	return false
}

func hasRedaction(options models.RedactionOptions) bool {
	return options.RedactActors || options.RedactNetworkEndpoints || options.RedactRuntimeDeviceIDs || options.RedactProfileTransports || options.RedactDeviceMetadata
}

func redactProfile(prof profile.Profile, options models.RedactionOptions) profile.Profile {
	if options.RedactProfileTransports {
		prof.Transport.SerialPort = redactString(prof.Transport.SerialPort, "serial-port")
		prof.Transport.ListenAddress = redactEndpoint(prof.Transport.ListenAddress)
		prof.Transport.RemoteAddress = redactEndpoint(prof.Transport.RemoteAddress)
		for i, dir := range prof.Transport.WatchDirectories {
			prof.Transport.WatchDirectories[i] = redactString(dir, "watch-dir")
		}
		for i, cidr := range prof.Transport.DiscoveryCIDRs {
			prof.Transport.DiscoveryCIDRs[i] = redactString(cidr, "cidr")
		}
	}
	if options.RedactDeviceMetadata && len(prof.DeviceMetadata) > 0 {
		redacted := map[string]string{}
		for key, value := range prof.DeviceMetadata {
			redacted[key] = redactString(value, key)
		}
		prof.DeviceMetadata = redacted
	}
	return prof
}

func redactNetworkLink(link models.NetworkDeviceLink, options models.RedactionOptions) models.NetworkDeviceLink {
	if options.RedactNetworkEndpoints {
		link.NetworkDeviceID = redactString(link.NetworkDeviceID, "network-device")
	}
	if options.RedactRuntimeDeviceIDs {
		link.RuntimeDeviceID = redactString(link.RuntimeDeviceID, "runtime-device")
	}
	return link
}

func redactString(value, label string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	return "[redacted:" + label + "]"
}

func redactEndpoint(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	return "[redacted:endpoint]"
}

func diffProfile(current, incoming profile.Profile) ([]string, []string, []profile.MigrationFieldChange) {
	changed := []string{}
	fields := []string{}
	changes := []profile.MigrationFieldChange{}
	if sectionFields, fieldChanges := diffAny("transport", current.Transport, incoming.Transport); len(sectionFields) > 0 {
		changed = append(changed, "transport")
		fields = append(fields, sectionFields...)
		changes = append(changes, fieldChanges...)
	}
	if sectionFields, fieldChanges := diffAny("parsing", current.Parsing, incoming.Parsing); len(sectionFields) > 0 {
		changed = append(changed, "parsing")
		fields = append(fields, sectionFields...)
		changes = append(changes, fieldChanges...)
	}
	if sectionFields, fieldChanges := diffAny("mapping", current.Mapping, incoming.Mapping); len(sectionFields) > 0 {
		changed = append(changed, "mapping")
		fields = append(fields, sectionFields...)
		changes = append(changes, fieldChanges...)
	}
	if sectionFields, fieldChanges := diffAny("device_metadata", current.DeviceMetadata, incoming.DeviceMetadata); len(sectionFields) > 0 {
		changed = append(changed, "device_metadata")
		fields = append(fields, sectionFields...)
		changes = append(changes, fieldChanges...)
	}
	generalFields := []string{}
	generalChanges := []profile.MigrationFieldChange{}
	if !profilesEqual(current.ProtocolHint, incoming.ProtocolHint) {
		generalFields = append(generalFields, "general.protocol_hint")
		generalChanges = append(generalChanges, profile.MigrationFieldChange{Path: "general.protocol_hint", OldValue: current.ProtocolHint, NewValue: incoming.ProtocolHint})
	}
	if !profilesEqual(current.Name, incoming.Name) {
		generalFields = append(generalFields, "general.name")
		generalChanges = append(generalChanges, profile.MigrationFieldChange{Path: "general.name", OldValue: current.Name, NewValue: incoming.Name})
	}
	if sectionFields, fieldChanges := diffAny("general.learning_mode", current.LearningSettings, incoming.LearningSettings); len(sectionFields) > 0 {
		generalFields = append(generalFields, sectionFields...)
		generalChanges = append(generalChanges, fieldChanges...)
	}
	if len(generalFields) > 0 {
		changed = append(changed, "general")
		fields = append(fields, generalFields...)
		changes = append(changes, generalChanges...)
	}
	return changed, fields, changes
}

func profilesEqual(a, b any) bool {
	left, _ := json.Marshal(a)
	right, _ := json.Marshal(b)
	return bytes.Equal(left, right)
}

func diffAny(prefix string, current, incoming any) ([]string, []profile.MigrationFieldChange) {
	left, _ := json.Marshal(current)
	right, _ := json.Marshal(incoming)
	var leftAny any
	var rightAny any
	_ = json.Unmarshal(left, &leftAny)
	_ = json.Unmarshal(right, &rightAny)
	out := []profile.MigrationFieldChange{}
	walkDiff(prefix, leftAny, rightAny, &out)
	sort.Slice(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	fields := make([]string, 0, len(out))
	for _, change := range out {
		fields = append(fields, change.Path)
	}
	return fields, out
}

func walkDiff(prefix string, left, right any, out *[]profile.MigrationFieldChange) {
	switch leftTyped := left.(type) {
	case map[string]any:
		rightTyped, ok := right.(map[string]any)
		if !ok {
			*out = append(*out, profile.MigrationFieldChange{Path: prefix, OldValue: left, NewValue: right})
			return
		}
		keys := map[string]struct{}{}
		for k := range leftTyped {
			keys[k] = struct{}{}
		}
		for k := range rightTyped {
			keys[k] = struct{}{}
		}
		merged := make([]string, 0, len(keys))
		for k := range keys {
			merged = append(merged, k)
		}
		sort.Strings(merged)
		for _, k := range merged {
			next := prefix + "." + k
			l, lok := leftTyped[k]
			r, rok := rightTyped[k]
			if !lok || !rok {
				*out = append(*out, profile.MigrationFieldChange{Path: next, OldValue: l, NewValue: r})
				continue
			}
			walkDiff(next, l, r, out)
		}
	case []any:
		rightTyped, ok := right.([]any)
		if !ok || !profilesEqual(leftTyped, rightTyped) {
			*out = append(*out, profile.MigrationFieldChange{Path: prefix, OldValue: left, NewValue: right})
		}
	default:
		if !profilesEqual(left, right) {
			*out = append(*out, profile.MigrationFieldChange{Path: prefix, OldValue: left, NewValue: right})
		}
	}
}

func loadOrCreateBundleHMACSecret(dataDir, configured string) ([]byte, string, error) {
	if strings.TrimSpace(configured) != "" {
		return []byte(strings.TrimSpace(configured)), "configured", nil
	}
	path := filepath.Join(dataDir, "bundle-hmac.key")
	if raw, err := os.ReadFile(path); err == nil && len(bytes.TrimSpace(raw)) > 0 {
		return bytes.TrimSpace(raw), "generated", nil
	}
	secret := make([]byte, 32)
	if _, err := rand.Read(secret); err != nil {
		return nil, "", err
	}
	encoded := []byte(fmt.Sprintf("%x", secret))
	if err := os.WriteFile(path, encoded, 0o600); err != nil {
		return nil, "", err
	}
	return encoded, "generated", nil
}

func (a *App) discoveryCIDRs(extra []string) []string {
	cidrSet := map[string]struct{}{}
	for _, raw := range extra {
		cidr := strings.TrimSpace(raw)
		if cidr != "" {
			cidrSet[cidr] = struct{}{}
		}
	}
	profiles, err := a.profiles.List()
	if err != nil {
		if len(cidrSet) == 0 {
			return nil
		}
	} else {
		for _, prof := range profiles {
			for _, raw := range prof.Transport.DiscoveryCIDRs {
				cidr := strings.TrimSpace(raw)
				if cidr != "" {
					cidrSet[cidr] = struct{}{}
				}
			}
		}
	}
	cidrs := make([]string, 0, len(cidrSet))
	for cidr := range cidrSet {
		cidrs = append(cidrs, cidr)
	}
	sort.Strings(cidrs)
	return cidrs
}

func addressPort(raw string) (int, bool) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0, false
	}
	_, portText, err := net.SplitHostPort(raw)
	if err != nil {
		return 0, false
	}
	port, err := strconv.Atoi(portText)
	if err != nil || port <= 0 || port > 65535 {
		return 0, false
	}
	return port, true
}

func (a *App) linkRuntimeDevice(profileID, runtimeDeviceID string, transportSettings profile.TransportSettings, source string) error {
	networkDeviceID := resolveNetworkDeviceID(runtimeDeviceID, transportSettings)
	if networkDeviceID == "" {
		return nil
	}
	now := time.Now().UTC()
	return a.captures.UpsertNetworkDeviceLinks([]models.NetworkDeviceLink{{
		NetworkDeviceID: networkDeviceID,
		ProfileID:       profileID,
		RuntimeDeviceID: runtimeDeviceID,
		Source:          source,
		SeenCount:       1,
		FirstSeen:       now,
		LastSeen:        now,
	}})
}

func resolveNetworkDeviceID(runtimeDeviceID string, transportSettings any) string {
	if host := endpointHost(runtimeDeviceID); host != "" {
		return "net:" + host
	}
	switch value := transportSettings.(type) {
	case profile.TransportSettings:
		for _, address := range []string{value.RemoteAddress, value.ListenAddress} {
			if host := endpointHost(address); host != "" {
				return "net:" + host
			}
		}
	case map[string]any:
		for _, key := range []string{"remote_address", "listen_address"} {
			if raw, ok := value[key].(string); ok {
				if host := endpointHost(raw); host != "" {
					return "net:" + host
				}
			}
		}
	}
	return ""
}

func endpointHost(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	if host, _, err := net.SplitHostPort(raw); err == nil {
		host = strings.Trim(host, "[]")
		if ip := net.ParseIP(host); ip != nil && ip.To4() != nil {
			return ip.String()
		}
		return ""
	}
	host := strings.Trim(raw, "[]")
	if ip := net.ParseIP(host); ip != nil && ip.To4() != nil {
		return ip.String()
	}
	return ""
}

type ReplayOutput struct {
	Result models.ParseResult `json:"result"`
}

func (r ReplayOutput) JSON() string { raw, _ := json.MarshalIndent(r, "", "  "); return string(raw) }
