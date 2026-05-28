package api

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"instrument-connectivity/internal/capture"
	"instrument-connectivity/internal/learning"
	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/profile"
	"instrument-connectivity/internal/transport"
)

type Service interface {
	ListProfiles() ([]profile.Profile, error)
	SaveProfile(profile.Profile) error
	ExportMigrationBundle(models.RedactionOptions, string) (profile.MigrationBundle, error)
	PreviewMigrationBundle(bundle profile.MigrationBundle) (profile.MigrationBundlePreview, error)
	ImportMigrationBundle(bundle profile.MigrationBundle, actor string, merges []models.NetworkLinkMergeDecision) error
	ScanPorts(req models.NetworkScanRequest) ([]models.DeviceFingerprint, []transport.SerialCandidate, []models.NetworkDevice, error)
	ProcessPayload(raw []byte, transport models.TransportType, profileID string, deviceID string) (models.ParseResult, capture.CaptureRecord, error)
	ListCaptures(filter capture.CaptureFilter) ([]capture.CaptureRecord, error)
	ReplayCapture(id, overrideProfileID string) (models.ParseResult, error)
	SaveNetworkLink(link models.NetworkDeviceLink, override bool, actor string) error
	DeleteNetworkLink(networkDeviceID, profileID, runtimeDeviceID string) error
	DeleteNetworkLinkWithActor(networkDeviceID, profileID, runtimeDeviceID, actor string) error
	ExportNetworkLinks() ([]models.NetworkDeviceLink, error)
	PreviewNetworkLinkImport(links []models.NetworkDeviceLink) (models.NetworkLinkImportPreview, error)
	ImportNetworkLinks(links []models.NetworkDeviceLink, replace bool, merges []models.NetworkLinkMergeDecision, actor string) error
	ListNetworkLinkAudit(filter models.NetworkLinkAuditFilter) ([]models.NetworkLinkAuditEntry, error)
	StartCapture(profileID string) (string, error)
	StopCapture(sessionID string) error
	SuggestLearning(rawText, profileID, captureID string) (learning.Suggestion, error)
	BuildSupportBundle() (string, []byte, error)
	BundleSecretStatus() (models.BundleSecretStatus, error)
	RuntimeSnapshot(limit int) (capture.RuntimeSnapshot, error)
	RuntimeErrors(limit int) ([]capture.RuntimeError, error)
	SessionHistory(filter capture.SessionEventFilter) ([]capture.SessionEvent, error)
	RunRetention() (capture.CleanupReport, error)
}

type Options struct {
	APIAuthToken string
	UIAssetsDir  string
}

type Server struct {
	svc         Service
	apiToken    string
	uiAssetsDir string
}

func New(svc Service, opts Options) *Server {
	uiDir := opts.UIAssetsDir
	if strings.TrimSpace(uiDir) == "" {
		uiDir = "web"
	}
	return &Server{svc: svc, apiToken: strings.TrimSpace(opts.APIAuthToken), uiAssetsDir: uiDir}
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.health)
	mux.HandleFunc("/api/v1/health", s.health)
	register := func(pattern string, handler http.HandlerFunc) { mux.Handle(pattern, s.withAPIAuth(handler)) }
	register("/api/ports/scan", s.scanPorts)
	register("/api/capture/start", s.startCapture)
	register("/api/capture/stop", s.stopCapture)
	register("/api/captures", s.captures)
	register("/api/classify", s.classify)
	register("/api/parse", s.parse)
	register("/api/map", s.parse)
	register("/api/replay", s.replay)
	register("/api/network-links", s.networkLinks)
	register("/api/network-links/export", s.exportNetworkLinks)
	register("/api/network-links/audit", s.networkLinkAudit)
	register("/api/network-links/audit/export", s.exportNetworkLinkAudit)
	register("/api/network-links/preview-import", s.previewImportNetworkLinks)
	register("/api/network-links/import", s.importNetworkLinks)
	register("/api/migration-bundle/export", s.exportMigrationBundle)
	register("/api/migration-bundle/preview", s.previewMigrationBundle)
	register("/api/migration-bundle/import", s.importMigrationBundle)
	register("/api/profiles", s.profiles)
	register("/api/learning/suggest", s.learningSuggest)
	register("/api/support-bundle", s.supportBundle)
	register("/api/runtime/cleanup", s.runtimeCleanup)
	register("/api/v1/ports/scan", s.scanPorts)
	register("/api/v1/capture/start", s.startCapture)
	register("/api/v1/capture/stop", s.stopCapture)
	register("/api/v1/captures", s.captures)
	register("/api/v1/classify", s.classify)
	register("/api/v1/parse", s.parse)
	register("/api/v1/map", s.parse)
	register("/api/v1/replay", s.replay)
	register("/api/v1/network-links", s.networkLinks)
	register("/api/v1/network-links/export", s.exportNetworkLinks)
	register("/api/v1/network-links/audit", s.networkLinkAudit)
	register("/api/v1/network-links/audit/export", s.exportNetworkLinkAudit)
	register("/api/v1/network-links/preview-import", s.previewImportNetworkLinks)
	register("/api/v1/network-links/import", s.importNetworkLinks)
	register("/api/v1/migration-bundle/export", s.exportMigrationBundle)
	register("/api/v1/migration-bundle/preview", s.previewMigrationBundle)
	register("/api/v1/migration-bundle/import", s.importMigrationBundle)
	register("/api/v1/profiles", s.profiles)
	register("/api/v1/learning/suggest", s.learningSuggest)
	register("/api/v1/support-bundle", s.supportBundle)
	register("/api/runtime/secret-status", s.runtimeSecretStatus)
	register("/api/v1/results/ingest", s.parse)
	register("/api/v1/runtime/secret-status", s.runtimeSecretStatus)
	register("/api/v1/runtime/status", s.runtimeStatus)
	register("/api/v1/runtime/errors", s.runtimeErrors)
	register("/api/v1/runtime/history", s.runtimeHistory)
	register("/api/v1/runtime/cleanup", s.runtimeCleanup)
	mux.Handle("/", http.FileServer(http.Dir(s.uiAssetsDir)))
	return mux
}

func (s *Server) withAPIAuth(next http.HandlerFunc) http.Handler {
	if s.apiToken == "" {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := strings.TrimSpace(r.Header.Get("X-API-Key"))
		if token == "" {
			token = bearerToken(r.Header.Get("Authorization"))
		}
		if token != s.apiToken {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized", "code": "api_auth_required"})
			return
		}
		next(w, r)
	})
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "time": time.Now().UTC(), "api_version": "v1", "auth_configured": s.apiToken != ""})
}

func (s *Server) scanPorts(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	ports, candidates, networkDevices, err := s.svc.ScanPorts(models.NetworkScanRequest{CIDRs: queryCSV(r, "cidrs"), Ports: queryPorts(r, "ports")})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ports": ports, "serial_candidates": candidates, "network_devices": networkDevices})
}

func (s *Server) startCapture(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		ProfileID string `json:"profile_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, err)
		return
	}
	id, err := s.svc.StartCapture(req.ProfileID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"session_id": id})
}

func (s *Server) stopCapture(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		SessionID string `json:"session_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, err)
		return
	}
	if err := s.svc.StopCapture(req.SessionID); err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "stopped"})
}

func (s *Server) captures(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	caps, err := s.svc.ListCaptures(capture.CaptureFilter{ProfileID: strings.TrimSpace(r.URL.Query().Get("profile_id")), DeviceID: strings.TrimSpace(r.URL.Query().Get("device_id")), DeviceIDs: queryCSV(r, "device_ids"), Limit: queryLimit(r, 100)})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, caps)
}

func (s *Server) classify(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	raw, profileID, deviceID, err := decodeBody(r)
	if err != nil {
		writeError(w, err)
		return
	}
	result, captureRec, err := s.svc.ProcessPayload(raw, models.TransportReplay, profileID, deviceID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"capture": captureRec, "classification": result.Classification})
}

func (s *Server) parse(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	raw, profileID, deviceID, err := decodeBody(r)
	if err != nil {
		writeError(w, err)
		return
	}
	result, captureRec, err := s.svc.ProcessPayload(raw, models.TransportReplay, profileID, deviceID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"capture": captureRec, "result": result})
}

func (s *Server) profiles(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		profiles, err := s.svc.ListProfiles()
		if err != nil {
			writeError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"profiles": profiles, "discovery_hint_catalog": defaultDiscoveryHintCatalog()})
	case http.MethodPost, http.MethodPut:
		var p profile.Profile
		if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
			writeError(w, err)
			return
		}
		if err := s.svc.SaveProfile(p); err != nil {
			writeError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, p)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Server) replay(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		CaptureID string `json:"capture_id"`
		ProfileID string `json:"profile_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, err)
		return
	}
	result, err := s.svc.ReplayCapture(req.CaptureID, req.ProfileID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func (s *Server) networkLinks(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodPost:
		var req struct {
			NetworkDeviceID string  `json:"network_device_id"`
			ProfileID       string  `json:"profile_id"`
			RuntimeDeviceID string  `json:"runtime_device_id"`
			Override        bool    `json:"override"`
			Confidence      float64 `json:"confidence"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, err)
			return
		}
		source := "manual_confirm"
		if req.Override {
			source = "manual_override"
		}
		err := s.svc.SaveNetworkLink(models.NetworkDeviceLink{
			NetworkDeviceID: strings.TrimSpace(req.NetworkDeviceID),
			ProfileID:       strings.TrimSpace(req.ProfileID),
			RuntimeDeviceID: strings.TrimSpace(req.RuntimeDeviceID),
			Source:          source,
			Confidence:      req.Confidence,
		}, req.Override, strings.TrimSpace(r.Header.Get("X-Operator-Name")))
		if err != nil {
			writeError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"status": "saved"})
	case http.MethodDelete:
		networkDeviceID := strings.TrimSpace(r.URL.Query().Get("network_device_id"))
		profileID := strings.TrimSpace(r.URL.Query().Get("profile_id"))
		runtimeDeviceID := strings.TrimSpace(r.URL.Query().Get("runtime_device_id"))
		actor := strings.TrimSpace(r.URL.Query().Get("actor"))
		if err := s.svc.DeleteNetworkLinkWithActor(networkDeviceID, profileID, runtimeDeviceID, actor); err != nil {
			writeError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"status": "deleted"})
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *Server) exportNetworkLinks(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	links, err := s.svc.ExportNetworkLinks()
	if err != nil {
		writeError(w, err)
		return
	}
	preview, err := s.svc.PreviewNetworkLinkImport(nil)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"links": links, "diagnostics": preview.Diagnostics})
}

func (s *Server) previewImportNetworkLinks(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Links []models.NetworkDeviceLink `json:"links"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, err)
		return
	}
	preview, err := s.svc.PreviewNetworkLinkImport(req.Links)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, preview)
}

func (s *Server) importNetworkLinks(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Links   []models.NetworkDeviceLink        `json:"links"`
		Replace bool                              `json:"replace"`
		Merges  []models.NetworkLinkMergeDecision `json:"merges"`
		Actor   string                            `json:"actor"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, err)
		return
	}
	if err := s.svc.ImportNetworkLinks(req.Links, req.Replace, req.Merges, req.Actor); err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "imported", "count": len(req.Links), "merge_count": len(req.Merges)})
}

func (s *Server) networkLinkAudit(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	entries, err := s.svc.ListNetworkLinkAudit(models.NetworkLinkAuditFilter{
		Actor:           strings.TrimSpace(r.URL.Query().Get("actor")),
		ProfileID:       strings.TrimSpace(r.URL.Query().Get("profile_id")),
		NetworkDeviceID: strings.TrimSpace(r.URL.Query().Get("network_device_id")),
		Action:          strings.TrimSpace(r.URL.Query().Get("action")),
		Limit:           queryLimit(r, 100),
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, entries)
}

func (s *Server) exportNetworkLinkAudit(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	filter := models.NetworkLinkAuditFilter{
		Actor:           strings.TrimSpace(r.URL.Query().Get("actor")),
		ProfileID:       strings.TrimSpace(r.URL.Query().Get("profile_id")),
		NetworkDeviceID: strings.TrimSpace(r.URL.Query().Get("network_device_id")),
		Action:          strings.TrimSpace(r.URL.Query().Get("action")),
		Limit:           queryLimit(r, 500),
	}
	entries, err := s.svc.ListNetworkLinkAudit(filter)
	if err != nil {
		writeError(w, err)
		return
	}
	redaction := parseRedactionOptions(r)
	if hasRedaction(redaction) {
		entries = redactAuditEntries(entries, redaction)
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", "network-link-audit.json"))
	_ = json.NewEncoder(w).Encode(map[string]any{"filter": filter, "redaction": redaction, "entries": entries})
}

func (s *Server) exportMigrationBundle(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	bundle, err := s.svc.ExportMigrationBundle(parseRedactionOptions(r), strings.TrimSpace(r.Header.Get("X-Operator-Name")))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, bundle)
}

func (s *Server) previewMigrationBundle(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Bundle profile.MigrationBundle `json:"bundle"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, err)
		return
	}
	preview, err := s.svc.PreviewMigrationBundle(req.Bundle)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, preview)
}

func (s *Server) importMigrationBundle(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		Bundle profile.MigrationBundle           `json:"bundle"`
		Actor  string                            `json:"actor"`
		Merges []models.NetworkLinkMergeDecision `json:"merges"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, err)
		return
	}
	if err := s.svc.ImportMigrationBundle(req.Bundle, req.Actor, req.Merges); err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "imported", "profiles": len(req.Bundle.Profiles), "links": len(req.Bundle.NetworkLinks)})
}

func (s *Server) learningSuggest(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req struct {
		RawText   string `json:"raw_text"`
		ProfileID string `json:"profile_id"`
		CaptureID string `json:"capture_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, err)
		return
	}
	suggestion, err := s.svc.SuggestLearning(req.RawText, req.ProfileID, req.CaptureID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, suggestion)
}

func (s *Server) supportBundle(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	name, blob, err := s.svc.BuildSupportBundle()
	if err != nil {
		writeError(w, err)
		return
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", name))
	_, _ = w.Write(blob)
}

func (s *Server) runtimeStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	snapshot, err := s.svc.RuntimeSnapshot(queryLimit(r, 50))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, snapshot)
}

func (s *Server) runtimeSecretStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	status, err := s.svc.BundleSecretStatus()
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, status)
}

func (s *Server) runtimeErrors(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	errorsOut, err := s.svc.RuntimeErrors(queryLimit(r, 100))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, errorsOut)
}

func (s *Server) runtimeHistory(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	events, err := s.svc.SessionHistory(capture.SessionEventFilter{SessionID: strings.TrimSpace(r.URL.Query().Get("session_id")), ProfileID: strings.TrimSpace(r.URL.Query().Get("profile_id")), DeviceID: strings.TrimSpace(r.URL.Query().Get("device_id")), Limit: queryLimit(r, 100)})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, events)
}

func (s *Server) runtimeCleanup(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	report, err := s.svc.RunRetention()
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, report)
}

func decodeBody(r *http.Request) ([]byte, string, string, error) {
	var req struct {
		PayloadBase64 string `json:"payload_base64"`
		PayloadText   string `json:"payload_text"`
		ProfileID     string `json:"profile_id"`
		DeviceID      string `json:"device_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		return nil, "", "", err
	}
	if req.PayloadBase64 != "" {
		raw, err := base64.StdEncoding.DecodeString(req.PayloadBase64)
		return raw, req.ProfileID, firstDeviceID(req.DeviceID), err
	}
	return []byte(req.PayloadText), req.ProfileID, firstDeviceID(req.DeviceID), nil
}

func bearerToken(header string) string {
	header = strings.TrimSpace(header)
	if !strings.HasPrefix(strings.ToLower(header), "bearer ") {
		return ""
	}
	return strings.TrimSpace(header[len("Bearer "):])
}
func firstDeviceID(v string) string {
	if strings.TrimSpace(v) == "" {
		return "manual-input"
	}
	return v
}
func queryLimit(r *http.Request, fallback int) int {
	raw := strings.TrimSpace(r.URL.Query().Get("limit"))
	if raw == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(raw)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
func queryCSV(r *http.Request, key string) []string {
	raw := strings.TrimSpace(r.URL.Query().Get(key))
	if raw == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}
func queryPorts(r *http.Request, key string) []int {
	values := queryCSV(r, key)
	ports := make([]int, 0, len(values))
	for _, value := range values {
		port, err := strconv.Atoi(value)
		if err == nil && port > 0 && port <= 65535 {
			ports = append(ports, port)
		}
	}
	return ports
}
func queryBool(r *http.Request, key string) bool {
	raw := strings.TrimSpace(strings.ToLower(r.URL.Query().Get(key)))
	return raw == "1" || raw == "true" || raw == "yes"
}
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func writeError(w http.ResponseWriter, err error) {
	writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
}

func parseRedactionOptions(r *http.Request) models.RedactionOptions {
	options := models.RedactionOptions{
		Preset:                  strings.TrimSpace(r.URL.Query().Get("redaction_preset")),
		RedactActors:            queryBool(r, "redact_actors"),
		RedactNetworkEndpoints:  queryBool(r, "redact_network_endpoints"),
		RedactRuntimeDeviceIDs:  queryBool(r, "redact_runtime_device_ids"),
		RedactProfileTransports: queryBool(r, "redact_profile_transports"),
		RedactDeviceMetadata:    queryBool(r, "redact_device_metadata"),
	}
	switch strings.ToLower(options.Preset) {
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

func hasRedaction(options models.RedactionOptions) bool {
	return options.Preset != "" || options.RedactActors || options.RedactNetworkEndpoints || options.RedactRuntimeDeviceIDs || options.RedactProfileTransports || options.RedactDeviceMetadata
}

func redactAuditEntries(entries []models.NetworkLinkAuditEntry, options models.RedactionOptions) []models.NetworkLinkAuditEntry {
	out := make([]models.NetworkLinkAuditEntry, 0, len(entries))
	for _, entry := range entries {
		clone := entry
		if options.RedactActors {
			clone.Actor = redactValue(clone.Actor, "actor")
		}
		if options.RedactNetworkEndpoints {
			clone.NetworkDeviceID = redactValue(clone.NetworkDeviceID, "network-device")
		}
		if options.RedactRuntimeDeviceIDs {
			clone.RuntimeDeviceID = redactValue(clone.RuntimeDeviceID, "runtime-device")
		}
		if len(clone.Detail) > 0 {
			clone.Detail = redactAnyMap(clone.Detail, options)
		}
		out = append(out, clone)
	}
	return out
}

func redactAnyMap(value map[string]any, options models.RedactionOptions) map[string]any {
	out := make(map[string]any, len(value))
	for key, item := range value {
		lower := strings.ToLower(key)
		switch {
		case options.RedactActors && strings.Contains(lower, "actor"):
			out[key] = redactValue(fmt.Sprint(item), key)
		case options.RedactNetworkEndpoints && (strings.Contains(lower, "network") || strings.Contains(lower, "endpoint")):
			out[key] = redactValue(fmt.Sprint(item), key)
		case options.RedactRuntimeDeviceIDs && strings.Contains(lower, "runtime"):
			out[key] = redactValue(fmt.Sprint(item), key)
		default:
			out[key] = item
		}
	}
	return out
}

func redactValue(value, label string) string {
	if strings.TrimSpace(value) == "" {
		return ""
	}
	return fmt.Sprintf("[redacted:%s]", label)
}

func defaultDiscoveryHintCatalog() []map[string]any {
	return []map[string]any{
		{"id": "hl7_listener", "label": "HL7 Listener", "ports": []int{2575, 3001, 4000, 5000}, "description": "Common HL7/MLLP listener ports."},
		{"id": "http_admin", "label": "HTTP Admin", "ports": []int{80, 8000, 8080, 8081, 8888}, "description": "Common embedded HTTP admin ports."},
		{"id": "raw_socket", "label": "Raw Socket", "ports": []int{9100}, "description": "Simple raw socket listener ports."},
		{"id": "line_admin", "label": "Line Admin", "ports": []int{21, 23}, "description": "Classic line-oriented admin ports used by narrow greeting probes."},
		{"id": "astm_serial", "label": "ASTM Serial", "ports": []int{}, "description": "Serial-only hint; does not expand network ports."},
		{"id": "file_drop", "label": "File Drop", "ports": []int{}, "description": "File-drop hint; does not expand network ports."},
	}
}
