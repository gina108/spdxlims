package capture

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	_ "modernc.org/sqlite"

	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/util"
)

type Store struct {
	DB         *sql.DB
	CaptureDir string
}

type RetentionPolicy struct {
	RetentionDays   int
	SessionEventMax int
	RuntimeErrorMax int
	CaptureMax      int
}

type CleanupReport struct {
	Policy               RetentionPolicy `json:"policy"`
	DeletedCaptures      int             `json:"deleted_captures"`
	DeletedCaptureFiles  int             `json:"deleted_capture_files"`
	DeletedRuntimeErrors int             `json:"deleted_runtime_errors"`
	DeletedSessionEvents int             `json:"deleted_session_events"`
	DeletedUnmapped      int             `json:"deleted_unmapped_observations"`
	ExecutedAt           time.Time       `json:"executed_at"`
}

type MaintenanceStatus struct {
	LastCleanup     *CleanupReport `json:"last_cleanup,omitempty"`
	NextCleanupAt   *time.Time     `json:"next_cleanup_at,omitempty"`
	CleanupInterval string         `json:"cleanup_interval,omitempty"`
	UpdatedAt       *time.Time     `json:"updated_at,omitempty"`
}

type CaptureRecord struct {
	ID             string                      `json:"id"`
	ProfileID      string                      `json:"profile_id"`
	DeviceID       string                      `json:"device_id"`
	TransportType  string                      `json:"transport_type"`
	RawPath        string                      `json:"raw_path"`
	DecodedText    string                      `json:"decoded_text"`
	NormalizedText string                      `json:"normalized_text"`
	Classification models.ClassificationResult `json:"classification"`
	ParsedJSON     string                      `json:"parsed_json,omitempty"`
	ReceivedAt     time.Time                   `json:"received_at"`
}

type CaptureFilter struct {
	ProfileID string
	DeviceID  string
	DeviceIDs []string
	Limit     int
}

type RuntimeStatus struct {
	ProfileID        string         `json:"profile_id"`
	DeviceID         string         `json:"device_id"`
	TransportType    string         `json:"transport_type"`
	ProtocolType     string         `json:"protocol_type,omitempty"`
	SessionID        string         `json:"session_id,omitempty"`
	SessionState     string         `json:"session_state,omitempty"`
	LastCaptureID    string         `json:"last_capture_id,omitempty"`
	LastSuccessAt    *time.Time     `json:"last_success_at,omitempty"`
	LastErrorAt      *time.Time     `json:"last_error_at,omitempty"`
	LastErrorMessage string         `json:"last_error_message,omitempty"`
	SelectedSettings map[string]any `json:"selected_settings,omitempty"`
	UnmappedCount    int            `json:"unmapped_count"`
	UpdatedAt        time.Time      `json:"updated_at"`
}

type RuntimeError struct {
	ID            string         `json:"id"`
	ProfileID     string         `json:"profile_id"`
	DeviceID      string         `json:"device_id"`
	TransportType string         `json:"transport_type"`
	Message       string         `json:"message"`
	Detail        map[string]any `json:"detail,omitempty"`
	CreatedAt     time.Time      `json:"created_at"`
}

type SessionEvent struct {
	ID            string         `json:"id"`
	SessionID     string         `json:"session_id"`
	ProfileID     string         `json:"profile_id"`
	DeviceID      string         `json:"device_id"`
	TransportType string         `json:"transport_type"`
	State         string         `json:"state"`
	Meta          map[string]any `json:"meta,omitempty"`
	CreatedAt     time.Time      `json:"created_at"`
}

type SessionEventFilter struct {
	SessionID string
	ProfileID string
	DeviceID  string
	Limit     int
}

type UnmappedObservation struct {
	ID                 string    `json:"id"`
	CaptureID          string    `json:"capture_id"`
	ProfileID          string    `json:"profile_id"`
	DeviceID           string    `json:"device_id"`
	InstrumentTestCode string    `json:"instrument_test_code"`
	InstrumentTestName string    `json:"instrument_test_name,omitempty"`
	ValueRaw           string    `json:"value_raw"`
	UnitsRaw           string    `json:"units_raw,omitempty"`
	CreatedAt          time.Time `json:"created_at"`
}

type RuntimeSnapshot struct {
	Devices        []RuntimeStatus        `json:"devices"`
	NetworkDevices []models.NetworkDevice `json:"network_devices"`
	Unmapped       []UnmappedObservation  `json:"unmapped"`
	Maintenance    MaintenanceStatus      `json:"maintenance"`
}

func Open(path, captureDir string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(captureDir, 0o755); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	if _, err := db.Exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`); err != nil {
		db.Close()
		return nil, err
	}
	store := &Store{DB: db, CaptureDir: captureDir}
	if err := store.migrate(); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

func (s *Store) Close() error { return s.DB.Close() }

func (s *Store) migrate() error {
	schema := `
CREATE TABLE IF NOT EXISTS captures (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, device_id TEXT NOT NULL, transport_type TEXT NOT NULL, raw_path TEXT NOT NULL, decoded_text TEXT NOT NULL, normalized_text TEXT NOT NULL, classification_json TEXT NOT NULL, parsed_json TEXT, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, transport_type TEXT NOT NULL, state TEXT NOT NULL, started_at TEXT NOT NULL, stopped_at TEXT);
CREATE TABLE IF NOT EXISTS session_events (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, profile_id TEXT NOT NULL, device_id TEXT NOT NULL, transport_type TEXT NOT NULL, state TEXT NOT NULL, meta_json TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_runs (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, capture_id TEXT NOT NULL, suggestions_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runtime_status (profile_id TEXT NOT NULL, device_id TEXT NOT NULL, transport_type TEXT NOT NULL, protocol_type TEXT, session_id TEXT, session_state TEXT, last_capture_id TEXT, last_success_at TEXT, last_error_at TEXT, last_error_message TEXT, selected_settings_json TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (profile_id, device_id));
CREATE TABLE IF NOT EXISTS runtime_errors (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, device_id TEXT NOT NULL, transport_type TEXT NOT NULL, message TEXT NOT NULL, detail_json TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS unmapped_observations (id TEXT PRIMARY KEY, capture_id TEXT NOT NULL, profile_id TEXT NOT NULL, device_id TEXT NOT NULL, instrument_test_code TEXT NOT NULL, instrument_test_name TEXT, value_raw TEXT NOT NULL, units_raw TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS maintenance_status (id INTEGER PRIMARY KEY CHECK (id = 1), last_cleanup_json TEXT, next_cleanup_at TEXT, cleanup_interval TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS network_devices (device_id TEXT PRIMARY KEY, host TEXT, ip TEXT NOT NULL, cidr TEXT, interface_name TEXT, mac TEXT, open_ports_json TEXT, reachability TEXT NOT NULL, probe_latency_ms INTEGER, banner TEXT, banner_protocol TEXT, likely_protocols_json TEXT, seen_count INTEGER NOT NULL DEFAULT 1, stability_score REAL NOT NULL DEFAULT 0, metadata_json TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS network_device_sightings (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, cidr TEXT, interface_name TEXT, probe_latency_ms INTEGER, open_ports_json TEXT, banner_protocol TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS network_device_links (network_device_id TEXT NOT NULL, profile_id TEXT NOT NULL, runtime_device_id TEXT NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.5, seen_count INTEGER NOT NULL DEFAULT 1, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, PRIMARY KEY (network_device_id, profile_id, runtime_device_id));
CREATE TABLE IF NOT EXISTS replay_events (id TEXT PRIMARY KEY, network_device_id TEXT, capture_id TEXT NOT NULL, profile_id TEXT NOT NULL, runtime_device_id TEXT NOT NULL, status TEXT NOT NULL, message TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS network_link_audit (id TEXT PRIMARY KEY, action TEXT NOT NULL, actor TEXT, network_device_id TEXT, profile_id TEXT, runtime_device_id TEXT, source TEXT, confidence REAL, detail_json TEXT, created_at TEXT NOT NULL);`
	if _, err := s.DB.Exec(schema); err != nil {
		return err
	}
	for _, stmt := range []string{
		`ALTER TABLE runtime_status ADD COLUMN session_id TEXT`,
		`ALTER TABLE runtime_status ADD COLUMN session_state TEXT`,
		`ALTER TABLE network_devices ADD COLUMN banner TEXT`,
		`ALTER TABLE network_devices ADD COLUMN banner_protocol TEXT`,
		`ALTER TABLE network_devices ADD COLUMN likely_protocols_json TEXT`,
		`ALTER TABLE network_devices ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 1`,
		`ALTER TABLE network_device_links ADD COLUMN confidence REAL NOT NULL DEFAULT 0.5`,
	} {
		_, _ = s.DB.Exec(stmt)
	}
	return nil
}

func (s *Store) ApplyRetention(policy RetentionPolicy) (CleanupReport, error) {
	if policy.RetentionDays <= 0 {
		policy.RetentionDays = 30
	}
	if policy.SessionEventMax <= 0 {
		policy.SessionEventMax = 5000
	}
	if policy.RuntimeErrorMax <= 0 {
		policy.RuntimeErrorMax = 2000
	}
	if policy.CaptureMax <= 0 {
		policy.CaptureMax = 2000
	}

	report := CleanupReport{Policy: policy, ExecutedAt: time.Now().UTC()}
	cutoff := report.ExecutedAt.AddDate(0, 0, -policy.RetentionDays).Format(time.RFC3339Nano)
	tx, err := s.DB.Begin()
	if err != nil {
		return CleanupReport{}, err
	}
	defer func() { _ = tx.Rollback() }()

	deletedCaptureFiles, err := deleteCaptureFiles(tx, s.CaptureDir, policy.CaptureMax, cutoff)
	if err != nil {
		return CleanupReport{}, err
	}
	report.DeletedCaptureFiles = deletedCaptureFiles

	if report.DeletedCaptures, err = deleteOlderThan(tx, `captures`, `received_at`, cutoff); err != nil {
		return CleanupReport{}, err
	}
	if report.DeletedRuntimeErrors, err = deleteOlderThan(tx, `runtime_errors`, `created_at`, cutoff); err != nil {
		return CleanupReport{}, err
	}
	if report.DeletedSessionEvents, err = deleteOlderThan(tx, `session_events`, `created_at`, cutoff); err != nil {
		return CleanupReport{}, err
	}
	if report.DeletedUnmapped, err = deleteOlderThan(tx, `unmapped_observations`, `created_at`, cutoff); err != nil {
		return CleanupReport{}, err
	}
	if _, err = deleteOlderThan(tx, `network_device_sightings`, `created_at`, cutoff); err != nil {
		return CleanupReport{}, err
	}
	if _, err = deleteOlderThan(tx, `replay_events`, `created_at`, cutoff); err != nil {
		return CleanupReport{}, err
	}

	trimmedRuntimeErrors, err := trimTable(tx, `runtime_errors`, `created_at`, policy.RuntimeErrorMax)
	if err != nil {
		return CleanupReport{}, err
	}
	report.DeletedRuntimeErrors += trimmedRuntimeErrors

	trimmedSessionEvents, err := trimTable(tx, `session_events`, `created_at`, policy.SessionEventMax)
	if err != nil {
		return CleanupReport{}, err
	}
	report.DeletedSessionEvents += trimmedSessionEvents

	trimmedCaptures, err := trimTable(tx, `captures`, `received_at`, policy.CaptureMax)
	if err != nil {
		return CleanupReport{}, err
	}
	report.DeletedCaptures += trimmedCaptures

	if err := tx.Commit(); err != nil {
		return CleanupReport{}, err
	}
	return report, nil
}

func (s *Store) UpdateMaintenanceStatus(report *CleanupReport, nextCleanupAt *time.Time, interval string) error {
	lastCleanupJSON := ""
	if report != nil {
		raw, _ := json.Marshal(report)
		lastCleanupJSON = string(raw)
	}
	nextCleanup := ""
	if nextCleanupAt != nil {
		nextCleanup = nextCleanupAt.UTC().Format(time.RFC3339Nano)
	}
	updatedAt := time.Now().UTC().Format(time.RFC3339Nano)
	_, err := s.DB.Exec(`INSERT INTO maintenance_status (id, last_cleanup_json, next_cleanup_at, cleanup_interval, updated_at) VALUES (1, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET last_cleanup_json = excluded.last_cleanup_json, next_cleanup_at = excluded.next_cleanup_at, cleanup_interval = excluded.cleanup_interval, updated_at = excluded.updated_at`, lastCleanupJSON, nextCleanup, interval, updatedAt)
	return err
}

func (s *Store) GetMaintenanceStatus() (MaintenanceStatus, error) {
	row := s.DB.QueryRow(`SELECT COALESCE(last_cleanup_json, ''), COALESCE(next_cleanup_at, ''), COALESCE(cleanup_interval, ''), COALESCE(updated_at, '') FROM maintenance_status WHERE id = 1`)
	var lastCleanupJSON, nextCleanupAt, cleanupInterval, updatedAt string
	if err := row.Scan(&lastCleanupJSON, &nextCleanupAt, &cleanupInterval, &updatedAt); err != nil {
		if err == sql.ErrNoRows {
			return MaintenanceStatus{}, nil
		}
		return MaintenanceStatus{}, err
	}
	status := MaintenanceStatus{CleanupInterval: cleanupInterval}
	if lastCleanupJSON != "" {
		var report CleanupReport
		if err := json.Unmarshal([]byte(lastCleanupJSON), &report); err == nil {
			status.LastCleanup = &report
		}
	}
	status.NextCleanupAt = parseOptionalTime(nextCleanupAt)
	status.UpdatedAt = parseOptionalTime(updatedAt)
	return status, nil
}

func deleteCaptureFiles(tx *sql.Tx, captureDir string, captureMax int, cutoff string) (int, error) {
	rows, err := tx.Query(`SELECT raw_path FROM captures WHERE received_at < ? UNION SELECT raw_path FROM captures WHERE id NOT IN (SELECT id FROM captures ORDER BY received_at DESC LIMIT ?)`, cutoff, captureMax)
	if err != nil {
		return 0, err
	}
	defer rows.Close()

	deleted := 0
	cleanedRoot := filepath.Clean(captureDir)
	for rows.Next() {
		var rawPath string
		if err := rows.Scan(&rawPath); err != nil {
			return deleted, err
		}
		cleanedPath := filepath.Clean(strings.TrimSpace(rawPath))
		if cleanedPath == "" || !strings.HasPrefix(cleanedPath, cleanedRoot) {
			continue
		}
		if err := os.Remove(cleanedPath); err == nil || os.IsNotExist(err) {
			deleted++
		}
	}
	return deleted, rows.Err()
}

func deleteOlderThan(tx *sql.Tx, table, column, cutoff string) (int, error) {
	query := fmt.Sprintf(`DELETE FROM %s WHERE %s < ?`, table, column)
	result, err := tx.Exec(query, cutoff)
	if err != nil {
		return 0, err
	}
	count, err := result.RowsAffected()
	return int(count), err
}

func trimTable(tx *sql.Tx, table, column string, maxRows int) (int, error) {
	query := fmt.Sprintf(`DELETE FROM %s WHERE id NOT IN (SELECT id FROM %s ORDER BY %s DESC LIMIT ?)`, table, table, column)
	result, err := tx.Exec(query, maxRows)
	if err != nil {
		return 0, err
	}
	count, err := result.RowsAffected()
	return int(count), err
}

func (s *Store) SaveRaw(profileID, deviceID string, transport models.TransportType, payload []byte, decoded, normalized string, cls models.ClassificationResult) (CaptureRecord, error) {
	id := util.NewID("cap")
	rawPath := filepath.Join(s.CaptureDir, id+".bin")
	if err := os.WriteFile(rawPath, payload, 0o644); err != nil {
		return CaptureRecord{}, err
	}
	clsJSON, _ := json.Marshal(cls)
	rec := CaptureRecord{
		ID:             id,
		ProfileID:      profileID,
		DeviceID:       deviceID,
		TransportType:  string(transport),
		RawPath:        rawPath,
		DecodedText:    decoded,
		NormalizedText: normalized,
		Classification: cls,
		ReceivedAt:     time.Now().UTC(),
	}
	_, err := s.DB.Exec(`INSERT INTO captures (id, profile_id, device_id, transport_type, raw_path, decoded_text, normalized_text, classification_json, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, rec.ID, rec.ProfileID, rec.DeviceID, rec.TransportType, rec.RawPath, rec.DecodedText, rec.NormalizedText, string(clsJSON), rec.ReceivedAt.Format(time.RFC3339Nano))
	return rec, err
}

func (s *Store) SaveParsed(captureID string, result any) error {
	raw, _ := json.MarshalIndent(result, "", "  ")
	_, err := s.DB.Exec(`UPDATE captures SET parsed_json = ? WHERE id = ?`, string(raw), captureID)
	return err
}

func (s *Store) UpdateRuntimeState(profileID, deviceID string, transport models.TransportType, sessionID, state string, selectedSettings any) error {
	settingsJSON, _ := json.Marshal(selectedSettings)
	now := time.Now().UTC().Format(time.RFC3339Nano)
	_, err := s.DB.Exec(`INSERT INTO runtime_status (profile_id, device_id, transport_type, session_id, session_state, selected_settings_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(profile_id, device_id) DO UPDATE SET transport_type = excluded.transport_type, session_id = excluded.session_id, session_state = excluded.session_state, selected_settings_json = COALESCE(NULLIF(excluded.selected_settings_json, ''), runtime_status.selected_settings_json), updated_at = excluded.updated_at`, profileID, deviceID, string(transport), sessionID, state, string(settingsJSON), now)
	return err
}

func (s *Store) AppendSessionEvent(sessionID, profileID, deviceID string, transport models.TransportType, state string, meta map[string]any) error {
	metaJSON, _ := json.Marshal(meta)
	_, err := s.DB.Exec(`INSERT INTO session_events (id, session_id, profile_id, device_id, transport_type, state, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, util.NewID("evt"), sessionID, profileID, deviceID, string(transport), state, string(metaJSON), time.Now().UTC().Format(time.RFC3339Nano))
	return err
}

func (s *Store) UpsertNetworkDevices(devices []models.NetworkDevice) ([]models.NetworkDevice, error) {
	if len(devices) == 0 {
		return []models.NetworkDevice{}, nil
	}
	tx, err := s.DB.Begin()
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	for _, device := range devices {
		portsJSON, _ := json.Marshal(device.OpenPorts)
		likelyProtocolsJSON, _ := json.Marshal(device.LikelyProtocols)
		metadataJSON, _ := json.Marshal(device.Metadata)
		firstSeen := device.FirstSeen.UTC().Format(time.RFC3339Nano)
		lastSeen := device.LastSeen.UTC().Format(time.RFC3339Nano)
		_, err := tx.Exec(`INSERT INTO network_devices (device_id, host, ip, cidr, interface_name, mac, open_ports_json, reachability, probe_latency_ms, banner, banner_protocol, likely_protocols_json, seen_count, stability_score, metadata_json, first_seen, last_seen, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET host = excluded.host, ip = excluded.ip, cidr = excluded.cidr, interface_name = excluded.interface_name, mac = excluded.mac, open_ports_json = excluded.open_ports_json, reachability = excluded.reachability, probe_latency_ms = excluded.probe_latency_ms, banner = CASE WHEN excluded.banner = '' THEN network_devices.banner ELSE excluded.banner END, banner_protocol = CASE WHEN excluded.banner_protocol = '' THEN network_devices.banner_protocol ELSE excluded.banner_protocol END, likely_protocols_json = CASE WHEN excluded.likely_protocols_json = '' THEN network_devices.likely_protocols_json ELSE excluded.likely_protocols_json END, seen_count = network_devices.seen_count + 1, stability_score = CASE WHEN excluded.stability_score > network_devices.stability_score THEN excluded.stability_score ELSE network_devices.stability_score END, metadata_json = excluded.metadata_json, last_seen = excluded.last_seen, updated_at = excluded.updated_at`, device.DeviceID, device.Host, device.IP, device.CIDR, device.InterfaceName, device.MAC, string(portsJSON), device.Reachability, device.ProbeLatencyMS, device.Banner, device.BannerProtocol, string(likelyProtocolsJSON), maxInt(1, device.SeenCount), device.StabilityScore, string(metadataJSON), firstSeen, lastSeen, lastSeen)
		if err != nil {
			return nil, err
		}
		_, err = tx.Exec(`INSERT INTO network_device_sightings (device_id, cidr, interface_name, probe_latency_ms, open_ports_json, banner_protocol, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`, device.DeviceID, device.CIDR, device.InterfaceName, device.ProbeLatencyMS, string(portsJSON), device.BannerProtocol, lastSeen)
		if err != nil {
			return nil, err
		}
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(devices))
	for _, device := range devices {
		ids = append(ids, device.DeviceID)
	}
	return s.GetNetworkDevicesByID(ids)
}

func (s *Store) UpsertNetworkDeviceLinks(links []models.NetworkDeviceLink) error {
	if len(links) == 0 {
		return nil
	}
	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	for _, link := range links {
		firstSeen := link.FirstSeen.UTC().Format(time.RFC3339Nano)
		lastSeen := link.LastSeen.UTC().Format(time.RFC3339Nano)
		_, err := tx.Exec(`INSERT INTO network_device_links (network_device_id, profile_id, runtime_device_id, source, confidence, seen_count, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(network_device_id, profile_id, runtime_device_id) DO UPDATE SET source = excluded.source, confidence = excluded.confidence, seen_count = network_device_links.seen_count + 1, last_seen = excluded.last_seen`, link.NetworkDeviceID, link.ProfileID, link.RuntimeDeviceID, link.Source, defaultLinkConfidence(link.Source, link.Confidence), maxInt(1, link.SeenCount), firstSeen, lastSeen)
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) ReplaceNetworkDeviceLinks(networkDeviceID, profileID string, links []models.NetworkDeviceLink) error {
	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.Exec(`DELETE FROM network_device_links WHERE network_device_id = ? AND profile_id = ?`, networkDeviceID, profileID); err != nil {
		return err
	}
	for _, link := range links {
		firstSeen := link.FirstSeen.UTC().Format(time.RFC3339Nano)
		lastSeen := link.LastSeen.UTC().Format(time.RFC3339Nano)
		_, err := tx.Exec(`INSERT INTO network_device_links (network_device_id, profile_id, runtime_device_id, source, confidence, seen_count, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, link.NetworkDeviceID, link.ProfileID, link.RuntimeDeviceID, link.Source, defaultLinkConfidence(link.Source, link.Confidence), maxInt(1, link.SeenCount), firstSeen, lastSeen)
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) DeleteNetworkDeviceLink(networkDeviceID, profileID, runtimeDeviceID string) error {
	_, err := s.DB.Exec(`DELETE FROM network_device_links WHERE network_device_id = ? AND profile_id = ? AND runtime_device_id = ?`, networkDeviceID, profileID, runtimeDeviceID)
	return err
}

func (s *Store) RecordNetworkLinkAudit(entry models.NetworkLinkAuditEntry) error {
	if entry.ID == "" {
		entry.ID = util.NewID("audit")
	}
	if entry.CreatedAt.IsZero() {
		entry.CreatedAt = time.Now().UTC()
	}
	detailJSON, _ := json.Marshal(entry.Detail)
	_, err := s.DB.Exec(`INSERT INTO network_link_audit (id, action, actor, network_device_id, profile_id, runtime_device_id, source, confidence, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		entry.ID, entry.Action, entry.Actor, entry.NetworkDeviceID, entry.ProfileID, entry.RuntimeDeviceID, entry.Source, entry.Confidence, string(detailJSON), entry.CreatedAt.Format(time.RFC3339Nano))
	return err
}

func (s *Store) ListNetworkLinkAudit(filter models.NetworkLinkAuditFilter) ([]models.NetworkLinkAuditEntry, error) {
	limit := filter.Limit
	if limit <= 0 {
		limit = 100
	}
	clauses := []string{}
	args := []any{}
	if strings.TrimSpace(filter.Actor) != "" {
		clauses = append(clauses, "actor = ?")
		args = append(args, strings.TrimSpace(filter.Actor))
	}
	if strings.TrimSpace(filter.ProfileID) != "" {
		clauses = append(clauses, "profile_id = ?")
		args = append(args, strings.TrimSpace(filter.ProfileID))
	}
	if strings.TrimSpace(filter.NetworkDeviceID) != "" {
		clauses = append(clauses, "network_device_id = ?")
		args = append(args, strings.TrimSpace(filter.NetworkDeviceID))
	}
	if strings.TrimSpace(filter.Action) != "" {
		clauses = append(clauses, "action = ?")
		args = append(args, strings.TrimSpace(filter.Action))
	}
	query := `SELECT id, action, COALESCE(actor, ''), COALESCE(network_device_id, ''), COALESCE(profile_id, ''), COALESCE(runtime_device_id, ''), COALESCE(source, ''), COALESCE(confidence, 0), COALESCE(detail_json, '{}'), created_at FROM network_link_audit`
	if len(clauses) > 0 {
		query += ` WHERE ` + strings.Join(clauses, ` AND `)
	}
	query += ` ORDER BY created_at DESC LIMIT ?`
	args = append(args, limit)
	rows, err := s.DB.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []models.NetworkLinkAuditEntry{}
	for rows.Next() {
		var entry models.NetworkLinkAuditEntry
		var detailJSON, createdAt string
		if err := rows.Scan(&entry.ID, &entry.Action, &entry.Actor, &entry.NetworkDeviceID, &entry.ProfileID, &entry.RuntimeDeviceID, &entry.Source, &entry.Confidence, &detailJSON, &createdAt); err != nil {
			return nil, err
		}
		entry.CreatedAt, _ = time.Parse(time.RFC3339Nano, createdAt)
		_ = json.Unmarshal([]byte(detailJSON), &entry.Detail)
		out = append(out, entry)
	}
	return out, rows.Err()
}

func (s *Store) RecordReplayEvent(networkDeviceID, captureID, profileID, runtimeDeviceID, status, message string) error {
	_, err := s.DB.Exec(`INSERT INTO replay_events (id, network_device_id, capture_id, profile_id, runtime_device_id, status, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, util.NewID("replay"), strings.TrimSpace(networkDeviceID), captureID, profileID, runtimeDeviceID, status, message, time.Now().UTC().Format(time.RFC3339Nano))
	return err
}

func (s *Store) GetNetworkDevicesByID(ids []string) ([]models.NetworkDevice, error) {
	if len(ids) == 0 {
		return []models.NetworkDevice{}, nil
	}
	placeholders := strings.TrimRight(strings.Repeat("?,", len(ids)), ",")
	args := make([]any, 0, len(ids))
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := s.DB.Query(`SELECT device_id, COALESCE(host, ''), ip, COALESCE(cidr, ''), COALESCE(interface_name, ''), COALESCE(mac, ''), COALESCE(open_ports_json, '[]'), COALESCE(reachability, ''), COALESCE(probe_latency_ms, 0), COALESCE(banner, ''), COALESCE(banner_protocol, ''), COALESCE(likely_protocols_json, '[]'), COALESCE(seen_count, 1), COALESCE(stability_score, 0), COALESCE(metadata_json, '{}'), first_seen, last_seen FROM network_devices WHERE device_id IN (`+placeholders+`)`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	devices, err := scanNetworkDevices(rows)
	if err != nil {
		return nil, err
	}
	return s.enrichNetworkDevices(devices)
}

func (s *Store) ListNetworkDevices(limit int) ([]models.NetworkDevice, error) {
	if limit <= 0 {
		limit = 100
	}
	rows, err := s.DB.Query(`SELECT device_id, COALESCE(host, ''), ip, COALESCE(cidr, ''), COALESCE(interface_name, ''), COALESCE(mac, ''), COALESCE(open_ports_json, '[]'), COALESCE(reachability, ''), COALESCE(probe_latency_ms, 0), COALESCE(banner, ''), COALESCE(banner_protocol, ''), COALESCE(likely_protocols_json, '[]'), COALESCE(seen_count, 1), COALESCE(stability_score, 0), COALESCE(metadata_json, '{}'), first_seen, last_seen FROM network_devices ORDER BY last_seen DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	devices, err := scanNetworkDevices(rows)
	if err != nil {
		return nil, err
	}
	return s.enrichNetworkDevices(devices)
}

func scanNetworkDevices(rows *sql.Rows) ([]models.NetworkDevice, error) {
	out := []models.NetworkDevice{}
	for rows.Next() {
		var device models.NetworkDevice
		var openPortsJSON, metadataJSON, likelyProtocolsJSON, firstSeen, lastSeen string
		if err := rows.Scan(&device.DeviceID, &device.Host, &device.IP, &device.CIDR, &device.InterfaceName, &device.MAC, &openPortsJSON, &device.Reachability, &device.ProbeLatencyMS, &device.Banner, &device.BannerProtocol, &likelyProtocolsJSON, &device.SeenCount, &device.StabilityScore, &metadataJSON, &firstSeen, &lastSeen); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(openPortsJSON), &device.OpenPorts)
		_ = json.Unmarshal([]byte(likelyProtocolsJSON), &device.LikelyProtocols)
		_ = json.Unmarshal([]byte(metadataJSON), &device.Metadata)
		device.FirstSeen, _ = time.Parse(time.RFC3339Nano, firstSeen)
		device.LastSeen, _ = time.Parse(time.RFC3339Nano, lastSeen)
		out = append(out, device)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].LastSeen.After(out[j].LastSeen) })
	return out, rows.Err()
}

func (s *Store) enrichNetworkDevices(devices []models.NetworkDevice) ([]models.NetworkDevice, error) {
	for i := range devices {
		cidrHistory, err := s.networkHistory(devices[i].DeviceID, "cidr")
		if err != nil {
			return nil, err
		}
		interfaceHistory, err := s.networkHistory(devices[i].DeviceID, "interface_name")
		if err != nil {
			return nil, err
		}
		devices[i].CIDRHistory = cidrHistory
		devices[i].InterfaceHistory = interfaceHistory
		devices[i].LastSeenStatus = lastSeenStatus(devices[i].LastSeen)
		if err := s.enrichNetworkDeviceRuntime(&devices[i]); err != nil {
			return nil, err
		}
		devices[i].StabilityScore = calculateNetworkStability(devices[i])
	}
	return devices, nil
}

func (s *Store) enrichNetworkDeviceRuntime(device *models.NetworkDevice) error {
	links, err := s.listNetworkDeviceLinks(device.DeviceID)
	if err != nil {
		return err
	}
	device.RuntimeLinks = links
	runtimeIDs := make([]string, 0, len(links))
	profileIDs := make([]string, 0, len(links))
	seenRuntime := map[string]struct{}{}
	seenProfiles := map[string]struct{}{}
	for _, link := range links {
		if _, ok := seenRuntime[link.RuntimeDeviceID]; !ok {
			seenRuntime[link.RuntimeDeviceID] = struct{}{}
			runtimeIDs = append(runtimeIDs, link.RuntimeDeviceID)
		}
		if _, ok := seenProfiles[link.ProfileID]; !ok {
			seenProfiles[link.ProfileID] = struct{}{}
			profileIDs = append(profileIDs, link.ProfileID)
		}
	}
	sort.Strings(runtimeIDs)
	sort.Strings(profileIDs)
	device.CorrelatedRuntimeIDs = runtimeIDs
	device.CorrelatedProfileIDs = profileIDs
	captureCount, err := s.countCapturesForRuntimeLinks(links)
	if err != nil {
		return err
	}
	device.RecentCaptureCount = captureCount
	parseFailures, err := s.countRuntimeErrorsForRuntimeLinks(links, 7*24*time.Hour)
	if err != nil {
		return err
	}
	device.RecentParseFailures = parseFailures
	lastReplayAt, lastReplayStatus, lastReplayCaptureID, lastReplayMessage, err := s.lastReplayForNetworkDevice(device.DeviceID)
	if err != nil {
		return err
	}
	device.LastReplayAt = lastReplayAt
	device.LastReplayStatus = lastReplayStatus
	device.LastReplayCaptureID = lastReplayCaptureID
	device.LastReplayMessage = lastReplayMessage
	replayHistory, err := s.recentReplayHistory(device.DeviceID, 3)
	if err != nil {
		return err
	}
	device.RecentReplayEvents = replayHistory
	recentErrors, err := s.recentRuntimeErrorExcerpts(links, 3)
	if err != nil {
		return err
	}
	device.RecentErrorExcerpts = recentErrors
	return nil
}

func (s *Store) listNetworkDeviceLinks(networkDeviceID string) ([]models.NetworkDeviceLink, error) {
	rows, err := s.DB.Query(`SELECT network_device_id, profile_id, runtime_device_id, source, confidence, seen_count, first_seen, last_seen FROM network_device_links WHERE network_device_id = ? ORDER BY last_seen DESC`, networkDeviceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []models.NetworkDeviceLink{}
	for rows.Next() {
		var link models.NetworkDeviceLink
		var firstSeen, lastSeen string
		if err := rows.Scan(&link.NetworkDeviceID, &link.ProfileID, &link.RuntimeDeviceID, &link.Source, &link.Confidence, &link.SeenCount, &firstSeen, &lastSeen); err != nil {
			return nil, err
		}
		link.FirstSeen, _ = time.Parse(time.RFC3339Nano, firstSeen)
		link.LastSeen, _ = time.Parse(time.RFC3339Nano, lastSeen)
		out = append(out, link)
	}
	return out, rows.Err()
}

func (s *Store) FindNetworkDeviceID(profileID, runtimeDeviceID string) (string, error) {
	row := s.DB.QueryRow(`SELECT network_device_id FROM network_device_links WHERE profile_id = ? AND runtime_device_id = ? ORDER BY last_seen DESC LIMIT 1`, profileID, runtimeDeviceID)
	var networkDeviceID string
	if err := row.Scan(&networkDeviceID); err != nil {
		if err == sql.ErrNoRows {
			return "", nil
		}
		return "", err
	}
	return networkDeviceID, nil
}

func (s *Store) ListAllNetworkDeviceLinks() ([]models.NetworkDeviceLink, error) {
	rows, err := s.DB.Query(`SELECT network_device_id, profile_id, runtime_device_id, source, confidence, seen_count, first_seen, last_seen FROM network_device_links ORDER BY network_device_id, profile_id, runtime_device_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []models.NetworkDeviceLink{}
	for rows.Next() {
		var link models.NetworkDeviceLink
		var firstSeen, lastSeen string
		if err := rows.Scan(&link.NetworkDeviceID, &link.ProfileID, &link.RuntimeDeviceID, &link.Source, &link.Confidence, &link.SeenCount, &firstSeen, &lastSeen); err != nil {
			return nil, err
		}
		link.FirstSeen, _ = time.Parse(time.RFC3339Nano, firstSeen)
		link.LastSeen, _ = time.Parse(time.RFC3339Nano, lastSeen)
		out = append(out, link)
	}
	return out, rows.Err()
}

func (s *Store) PreviewNetworkLinkImport(links []models.NetworkDeviceLink) (models.NetworkLinkImportPreview, error) {
	normalized := make([]models.NetworkDeviceLink, 0, len(links))
	for _, link := range links {
		link.NetworkDeviceID = strings.TrimSpace(link.NetworkDeviceID)
		link.ProfileID = strings.TrimSpace(link.ProfileID)
		link.RuntimeDeviceID = strings.TrimSpace(link.RuntimeDeviceID)
		link.Source = strings.TrimSpace(link.Source)
		if link.NetworkDeviceID == "" || link.ProfileID == "" || link.RuntimeDeviceID == "" {
			continue
		}
		link.Confidence = defaultLinkConfidence(link.Source, link.Confidence)
		normalized = append(normalized, link)
	}
	preview := models.NetworkLinkImportPreview{
		Links: normalized,
	}
	existing, err := s.ListAllNetworkDeviceLinks()
	if err != nil {
		return models.NetworkLinkImportPreview{}, err
	}
	preview.Diagnostics = summarizeNetworkLinks(existing)
	if len(normalized) == 0 {
		return preview, nil
	}
	exactMatches := map[string]models.NetworkDeviceLink{}
	runtimeClaims := map[string][]models.NetworkDeviceLink{}
	endpointClaims := map[string][]models.NetworkDeviceLink{}
	for _, link := range existing {
		exactMatches[link.NetworkDeviceID+"|"+link.ProfileID+"|"+link.RuntimeDeviceID] = link
		runtimeClaims[link.ProfileID+"|"+link.RuntimeDeviceID] = append(runtimeClaims[link.ProfileID+"|"+link.RuntimeDeviceID], link)
		endpointClaims[link.NetworkDeviceID+"|"+link.ProfileID] = append(endpointClaims[link.NetworkDeviceID+"|"+link.ProfileID], link)
	}
	for _, link := range normalized {
		exactKey := link.NetworkDeviceID + "|" + link.ProfileID + "|" + link.RuntimeDeviceID
		if _, ok := exactMatches[exactKey]; ok {
			preview.SafeLinks = append(preview.SafeLinks, link)
			continue
		}
		foundConflict := false
		for _, existingLink := range runtimeClaims[link.ProfileID+"|"+link.RuntimeDeviceID] {
			if existingLink.NetworkDeviceID == link.NetworkDeviceID {
				continue
			}
			preview.Conflicts = append(preview.Conflicts, models.NetworkLinkImportConflict{
				ConflictID: "runtime:" + link.ProfileID + "|" + link.RuntimeDeviceID + "|" + link.NetworkDeviceID,
				Type:       "runtime_claimed_elsewhere",
				Message:    fmt.Sprintf("Runtime device %s for profile %s is already linked to %s.", link.RuntimeDeviceID, link.ProfileID, existingLink.NetworkDeviceID),
				Existing:   existingLink,
				Incoming:   link,
			})
			foundConflict = true
		}
		for _, existingLink := range endpointClaims[link.NetworkDeviceID+"|"+link.ProfileID] {
			if existingLink.RuntimeDeviceID == link.RuntimeDeviceID {
				continue
			}
			preview.Conflicts = append(preview.Conflicts, models.NetworkLinkImportConflict{
				ConflictID: "endpoint:" + link.NetworkDeviceID + "|" + link.ProfileID + "|" + link.RuntimeDeviceID,
				Type:       "endpoint_profile_has_other_runtime",
				Message:    fmt.Sprintf("Endpoint %s already has runtime %s for profile %s.", link.NetworkDeviceID, existingLink.RuntimeDeviceID, link.ProfileID),
				Existing:   existingLink,
				Incoming:   link,
			})
			foundConflict = true
		}
		if !foundConflict {
			preview.SafeLinks = append(preview.SafeLinks, link)
		}
	}
	return preview, nil
}

func (s *Store) ApplyNetworkLinkMerge(link models.NetworkDeviceLink) error {
	link.NetworkDeviceID = strings.TrimSpace(link.NetworkDeviceID)
	link.ProfileID = strings.TrimSpace(link.ProfileID)
	link.RuntimeDeviceID = strings.TrimSpace(link.RuntimeDeviceID)
	if link.NetworkDeviceID == "" || link.ProfileID == "" || link.RuntimeDeviceID == "" {
		return nil
	}
	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.Exec(`DELETE FROM network_device_links WHERE profile_id = ? AND runtime_device_id = ? AND network_device_id <> ?`, link.ProfileID, link.RuntimeDeviceID, link.NetworkDeviceID); err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM network_device_links WHERE network_device_id = ? AND profile_id = ? AND runtime_device_id <> ?`, link.NetworkDeviceID, link.ProfileID, link.RuntimeDeviceID); err != nil {
		return err
	}
	firstSeen := link.FirstSeen.UTC().Format(time.RFC3339Nano)
	lastSeen := link.LastSeen.UTC().Format(time.RFC3339Nano)
	if _, err := tx.Exec(`INSERT INTO network_device_links (network_device_id, profile_id, runtime_device_id, source, confidence, seen_count, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(network_device_id, profile_id, runtime_device_id) DO UPDATE SET source = excluded.source, confidence = excluded.confidence, seen_count = network_device_links.seen_count + 1, last_seen = excluded.last_seen`, link.NetworkDeviceID, link.ProfileID, link.RuntimeDeviceID, link.Source, defaultLinkConfidence(link.Source, link.Confidence), maxInt(1, link.SeenCount), firstSeen, lastSeen); err != nil {
		return err
	}
	return tx.Commit()
}

func summarizeNetworkLinks(links []models.NetworkDeviceLink) models.NetworkLinkDiagnostics {
	diag := models.NetworkLinkDiagnostics{
		TotalLinks:         len(links),
		BySource:           map[string]int{},
		ByConfidenceBand:   map[string]int{},
	}
	for _, link := range links {
		source := strings.TrimSpace(link.Source)
		if source == "" {
			source = "unknown"
		}
		diag.BySource[source]++
		if strings.HasPrefix(source, "manual_") {
			diag.ManualLinks++
		} else {
			diag.AutomaticLinks++
		}
		band := "low"
		switch {
		case link.Confidence >= 0.95:
			band = "confirmed"
		case link.Confidence >= 0.75:
			band = "high"
		case link.Confidence >= 0.5:
			band = "medium"
		}
		diag.ByConfidenceBand[band]++
	}
	return diag
}

func defaultLinkConfidence(source string, current float64) float64 {
	if current > 0 {
		return current
	}
	switch strings.ToLower(strings.TrimSpace(source)) {
	case "manual_override", "manual_import":
		return 0.98
	case "payload":
		return 0.84
	case "profile_transport":
		return 0.62
	default:
		return 0.5
	}
}

func (s *Store) countCapturesForRuntimeLinks(links []models.NetworkDeviceLink) (int, error) {
	if len(links) == 0 {
		return 0, nil
	}
	clauses := make([]string, 0, len(links))
	args := make([]any, 0, len(links)*2)
	for _, link := range links {
		clauses = append(clauses, "(profile_id = ? AND device_id = ?)")
		args = append(args, link.ProfileID, link.RuntimeDeviceID)
	}
	query := `SELECT COUNT(*) FROM captures WHERE ` + strings.Join(clauses, " OR ")
	var count int
	if err := s.DB.QueryRow(query, args...).Scan(&count); err != nil {
		return 0, err
	}
	return count, nil
}

func (s *Store) countRuntimeErrorsForRuntimeLinks(links []models.NetworkDeviceLink, since time.Duration) (int, error) {
	if len(links) == 0 {
		return 0, nil
	}
	clauses := make([]string, 0, len(links))
	args := make([]any, 0, len(links)*2+1)
	for _, link := range links {
		clauses = append(clauses, "(profile_id = ? AND device_id = ?)")
		args = append(args, link.ProfileID, link.RuntimeDeviceID)
	}
	query := `SELECT COUNT(*) FROM runtime_errors WHERE created_at >= ? AND (` + strings.Join(clauses, " OR ") + `)`
	args = append([]any{time.Now().UTC().Add(-since).Format(time.RFC3339Nano)}, args...)
	var count int
	if err := s.DB.QueryRow(query, args...).Scan(&count); err != nil {
		return 0, err
	}
	return count, nil
}

func (s *Store) lastReplayForNetworkDevice(networkDeviceID string) (*time.Time, string, string, string, error) {
	row := s.DB.QueryRow(`SELECT created_at, status, capture_id, COALESCE(message, '') FROM replay_events WHERE network_device_id = ? ORDER BY created_at DESC LIMIT 1`, networkDeviceID)
	var createdAt, status, captureID, message string
	if err := row.Scan(&createdAt, &status, &captureID, &message); err != nil {
		if err == sql.ErrNoRows {
			return nil, "", "", "", nil
		}
		return nil, "", "", "", err
	}
	parsed, _ := time.Parse(time.RFC3339Nano, createdAt)
	return &parsed, status, captureID, message, nil
}

func (s *Store) recentReplayHistory(networkDeviceID string, limit int) ([]models.ReplayEventSummary, error) {
	if limit <= 0 {
		limit = 3
	}
	rows, err := s.DB.Query(`SELECT capture_id, status, COALESCE(message, ''), created_at FROM replay_events WHERE network_device_id = ? ORDER BY created_at DESC LIMIT ?`, networkDeviceID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []models.ReplayEventSummary{}
	for rows.Next() {
		var item models.ReplayEventSummary
		var createdAt string
		if err := rows.Scan(&item.CaptureID, &item.Status, &item.Message, &createdAt); err != nil {
			return nil, err
		}
		item.CreatedAt, _ = time.Parse(time.RFC3339Nano, createdAt)
		out = append(out, item)
	}
	return out, rows.Err()
}

func (s *Store) recentRuntimeErrorExcerpts(links []models.NetworkDeviceLink, limit int) ([]string, error) {
	if len(links) == 0 {
		return nil, nil
	}
	if limit <= 0 {
		limit = 3
	}
	clauses := make([]string, 0, len(links))
	args := make([]any, 0, len(links)*2+1)
	for _, link := range links {
		clauses = append(clauses, "(profile_id = ? AND device_id = ?)")
		args = append(args, link.ProfileID, link.RuntimeDeviceID)
	}
	query := `SELECT created_at, message FROM runtime_errors WHERE ` + strings.Join(clauses, " OR ") + ` ORDER BY created_at DESC LIMIT ?`
	args = append(args, limit)
	rows, err := s.DB.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var createdAt, message string
		if err := rows.Scan(&createdAt, &message); err != nil {
			return nil, err
		}
		out = append(out, fmt.Sprintf("%s | %s", createdAt, message))
	}
	return out, rows.Err()
}

func (s *Store) networkHistory(deviceID, column string) ([]models.NetworkHistoryEntry, error) {
	rows, err := s.DB.Query(`SELECT `+column+`, COUNT(*), MIN(created_at), MAX(created_at) FROM network_device_sightings WHERE device_id = ? AND COALESCE(`+column+`, '') <> '' GROUP BY `+column+` ORDER BY MAX(created_at) DESC, COUNT(*) DESC LIMIT 5`, deviceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []models.NetworkHistoryEntry{}
	for rows.Next() {
		var entry models.NetworkHistoryEntry
		var firstSeen, lastSeen string
		if err := rows.Scan(&entry.Value, &entry.Count, &firstSeen, &lastSeen); err != nil {
			return nil, err
		}
		entry.FirstSeen, _ = time.Parse(time.RFC3339Nano, firstSeen)
		entry.LastSeen, _ = time.Parse(time.RFC3339Nano, lastSeen)
		out = append(out, entry)
	}
	return out, rows.Err()
}

func lastSeenStatus(lastSeen time.Time) string {
	if lastSeen.IsZero() {
		return "unknown"
	}
	age := time.Since(lastSeen)
	switch {
	case age <= 15*time.Minute:
		return "online"
	case age <= 24*time.Hour:
		return "recent"
	default:
		return "stale"
	}
}

func calculateNetworkStability(device models.NetworkDevice) float64 {
	score := 0.2
	if len(device.OpenPorts) > 0 {
		score += 0.15
	}
	if len(device.OpenPorts) > 1 {
		score += 0.05
	}
	if device.SeenCount > 1 {
		score += 0.1
	}
	if device.SeenCount > 5 {
		score += 0.1
	}
	if len(device.CIDRHistory) == 1 && device.CIDRHistory[0].Count >= 2 {
		score += 0.15
	} else if len(device.CIDRHistory) > 1 {
		score += 0.05
	}
	if len(device.InterfaceHistory) == 1 && device.InterfaceHistory[0].Count >= 2 {
		score += 0.15
	} else if len(device.InterfaceHistory) > 1 {
		score += 0.05
	}
	if len(device.RuntimeLinks) > 0 {
		score += 0.08
	}
	if device.RecentCaptureCount > 0 {
		score += 0.06
	}
	if device.RecentParseFailures == 0 && device.RecentCaptureCount > 0 {
		score += 0.04
	}
	switch device.LastSeenStatus {
	case "online":
		score += 0.1
	case "recent":
		score += 0.05
	}
	if score > 0.99 {
		return 0.99
	}
	return score
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func (s *Store) ListSessionEvents(filter SessionEventFilter) ([]SessionEvent, error) {
	limit := filter.Limit
	if limit <= 0 {
		limit = 100
	}
	clauses := []string{}
	args := []any{}
	if strings.TrimSpace(filter.SessionID) != "" {
		clauses = append(clauses, "session_id = ?")
		args = append(args, strings.TrimSpace(filter.SessionID))
	}
	if strings.TrimSpace(filter.ProfileID) != "" {
		clauses = append(clauses, "profile_id = ?")
		args = append(args, strings.TrimSpace(filter.ProfileID))
	}
	if strings.TrimSpace(filter.DeviceID) != "" {
		clauses = append(clauses, "device_id = ?")
		args = append(args, strings.TrimSpace(filter.DeviceID))
	}
	query := `SELECT id, session_id, profile_id, device_id, transport_type, state, COALESCE(meta_json, ''), created_at FROM session_events`
	if len(clauses) > 0 {
		query += ` WHERE ` + strings.Join(clauses, ` AND `)
	}
	query += ` ORDER BY created_at DESC LIMIT ?`
	args = append(args, limit)
	rows, err := s.DB.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []SessionEvent{}
	for rows.Next() {
		var rec SessionEvent
		var metaJSON, createdAt string
		if err := rows.Scan(&rec.ID, &rec.SessionID, &rec.ProfileID, &rec.DeviceID, &rec.TransportType, &rec.State, &metaJSON, &createdAt); err != nil {
			return nil, err
		}
		rec.CreatedAt, _ = time.Parse(time.RFC3339Nano, createdAt)
		if metaJSON != "" {
			_ = json.Unmarshal([]byte(metaJSON), &rec.Meta)
		}
		out = append(out, rec)
	}
	return out, rows.Err()
}

func (s *Store) RecordProcessingSuccess(profileID, deviceID string, transport models.TransportType, protocol models.ProtocolType, captureID string, selectedSettings any, observations []models.Observation, occurredAt time.Time) error {
	settingsJSON, _ := json.Marshal(selectedSettings)
	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()

	_, err = tx.Exec(`INSERT INTO runtime_status (profile_id, device_id, transport_type, protocol_type, last_capture_id, last_success_at, session_state, selected_settings_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(profile_id, device_id) DO UPDATE SET transport_type = excluded.transport_type, protocol_type = excluded.protocol_type, last_capture_id = excluded.last_capture_id, last_success_at = excluded.last_success_at, session_state = excluded.session_state, selected_settings_json = excluded.selected_settings_json, updated_at = excluded.updated_at`, profileID, deviceID, string(transport), string(protocol), captureID, occurredAt.Format(time.RFC3339Nano), "active", string(settingsJSON), occurredAt.Format(time.RFC3339Nano))
	if err != nil {
		return err
	}
	for _, obs := range observations {
		if obs.MappedLISTestID != "" {
			continue
		}
		_, err = tx.Exec(`INSERT INTO unmapped_observations (id, capture_id, profile_id, device_id, instrument_test_code, instrument_test_name, value_raw, units_raw, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, util.NewID("unmapped"), captureID, profileID, deviceID, obs.InstrumentTestCode, obs.InstrumentTestName, obs.ValueRaw, obs.UnitsRaw, occurredAt.Format(time.RFC3339Nano))
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) RecordProcessingError(profileID, deviceID string, transport models.TransportType, message string, selectedSettings any, detail map[string]any) error {
	settingsJSON, _ := json.Marshal(selectedSettings)
	detailJSON, _ := json.Marshal(detail)
	now := time.Now().UTC()
	state := "error"
	if stage, ok := detail["stage"].(string); ok {
		switch stage {
		case "tcp_client_connect", "serial_open":
			state = "retrying"
		case "astm_checksum":
			state = "checksum_error"
		}
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()

	_, err = tx.Exec(`INSERT INTO runtime_errors (id, profile_id, device_id, transport_type, message, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`, util.NewID("err"), profileID, deviceID, string(transport), message, string(detailJSON), now.Format(time.RFC3339Nano))
	if err != nil {
		return err
	}
	_, err = tx.Exec(`INSERT INTO runtime_status (profile_id, device_id, transport_type, last_error_at, last_error_message, session_state, selected_settings_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(profile_id, device_id) DO UPDATE SET transport_type = excluded.transport_type, last_error_at = excluded.last_error_at, last_error_message = excluded.last_error_message, session_state = excluded.session_state, selected_settings_json = excluded.selected_settings_json, updated_at = excluded.updated_at`, profileID, deviceID, string(transport), now.Format(time.RFC3339Nano), message, state, string(settingsJSON), now.Format(time.RFC3339Nano))
	if err != nil {
		return err
	}
	return tx.Commit()
}

func (s *Store) RuntimeSnapshot(deviceLimit, unmappedLimit int) (RuntimeSnapshot, error) {
	devices, err := s.ListRuntimeStatus(deviceLimit)
	if err != nil {
		return RuntimeSnapshot{}, err
	}
	networkDevices, err := s.ListNetworkDevices(deviceLimit)
	if err != nil {
		return RuntimeSnapshot{}, err
	}
	unmapped, err := s.ListUnmappedObservations(unmappedLimit)
	if err != nil {
		return RuntimeSnapshot{}, err
	}
	maintenance, err := s.GetMaintenanceStatus()
	if err != nil {
		return RuntimeSnapshot{}, err
	}
	return RuntimeSnapshot{Devices: devices, NetworkDevices: networkDevices, Unmapped: unmapped, Maintenance: maintenance}, nil
}

func (s *Store) ListRuntimeStatus(limit int) ([]RuntimeStatus, error) {
	if limit <= 0 {
		limit = 50
	}
	rows, err := s.DB.Query(`SELECT rs.profile_id, rs.device_id, rs.transport_type, COALESCE(rs.protocol_type, ''), COALESCE(rs.session_id, ''), COALESCE(rs.session_state, ''), COALESCE(rs.last_capture_id, ''), COALESCE(rs.last_success_at, ''), COALESCE(rs.last_error_at, ''), COALESCE(rs.last_error_message, ''), COALESCE(rs.selected_settings_json, ''), rs.updated_at, (SELECT COUNT(*) FROM unmapped_observations uo WHERE uo.profile_id = rs.profile_id AND uo.device_id = rs.device_id) AS unmapped_count FROM runtime_status rs ORDER BY rs.updated_at DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []RuntimeStatus{}
	for rows.Next() {
		var rec RuntimeStatus
		var successAt, errorAt, settingsJSON, updatedAt string
		if err := rows.Scan(&rec.ProfileID, &rec.DeviceID, &rec.TransportType, &rec.ProtocolType, &rec.SessionID, &rec.SessionState, &rec.LastCaptureID, &successAt, &errorAt, &rec.LastErrorMessage, &settingsJSON, &updatedAt, &rec.UnmappedCount); err != nil {
			return nil, err
		}
		rec.LastSuccessAt = parseOptionalTime(successAt)
		rec.LastErrorAt = parseOptionalTime(errorAt)
		rec.UpdatedAt, _ = time.Parse(time.RFC3339Nano, updatedAt)
		if settingsJSON != "" {
			_ = json.Unmarshal([]byte(settingsJSON), &rec.SelectedSettings)
		}
		out = append(out, rec)
	}
	return out, rows.Err()
}

func (s *Store) ListRuntimeErrors(limit int) ([]RuntimeError, error) {
	if limit <= 0 {
		limit = 100
	}
	rows, err := s.DB.Query(`SELECT id, profile_id, device_id, transport_type, message, COALESCE(detail_json, ''), created_at FROM runtime_errors ORDER BY created_at DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []RuntimeError{}
	for rows.Next() {
		var rec RuntimeError
		var detailJSON, createdAt string
		if err := rows.Scan(&rec.ID, &rec.ProfileID, &rec.DeviceID, &rec.TransportType, &rec.Message, &detailJSON, &createdAt); err != nil {
			return nil, err
		}
		rec.CreatedAt, _ = time.Parse(time.RFC3339Nano, createdAt)
		if detailJSON != "" {
			_ = json.Unmarshal([]byte(detailJSON), &rec.Detail)
		}
		out = append(out, rec)
	}
	return out, rows.Err()
}

func (s *Store) ListUnmappedObservations(limit int) ([]UnmappedObservation, error) {
	if limit <= 0 {
		limit = 100
	}
	rows, err := s.DB.Query(`SELECT id, capture_id, profile_id, device_id, instrument_test_code, COALESCE(instrument_test_name, ''), value_raw, COALESCE(units_raw, ''), created_at FROM unmapped_observations ORDER BY created_at DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []UnmappedObservation{}
	for rows.Next() {
		var rec UnmappedObservation
		var createdAt string
		if err := rows.Scan(&rec.ID, &rec.CaptureID, &rec.ProfileID, &rec.DeviceID, &rec.InstrumentTestCode, &rec.InstrumentTestName, &rec.ValueRaw, &rec.UnitsRaw, &createdAt); err != nil {
			return nil, err
		}
		rec.CreatedAt, _ = time.Parse(time.RFC3339Nano, createdAt)
		out = append(out, rec)
	}
	return out, rows.Err()
}

func (s *Store) ListCaptures(filter CaptureFilter) ([]CaptureRecord, error) {
	limit := filter.Limit
	if limit <= 0 {
		limit = 100
	}
	clauses := []string{}
	args := []any{}
	if strings.TrimSpace(filter.ProfileID) != "" {
		clauses = append(clauses, "profile_id = ?")
		args = append(args, strings.TrimSpace(filter.ProfileID))
	}
	if strings.TrimSpace(filter.DeviceID) != "" {
		clauses = append(clauses, "device_id = ?")
		args = append(args, strings.TrimSpace(filter.DeviceID))
	}
	if len(filter.DeviceIDs) > 0 {
		placeholders := strings.TrimRight(strings.Repeat("?,", len(filter.DeviceIDs)), ",")
		clauses = append(clauses, "device_id IN ("+placeholders+")")
		for _, deviceID := range filter.DeviceIDs {
			args = append(args, strings.TrimSpace(deviceID))
		}
	}
	query := `SELECT id, profile_id, device_id, transport_type, raw_path, decoded_text, normalized_text, classification_json, parsed_json, received_at FROM captures`
	if len(clauses) > 0 {
		query += ` WHERE ` + strings.Join(clauses, ` AND `)
	}
	query += ` ORDER BY received_at DESC LIMIT ?`
	args = append(args, limit)
	rows, err := s.DB.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []CaptureRecord{}
	for rows.Next() {
		var rec CaptureRecord
		var clsJSON, received string
		var parsedJSON sql.NullString
		if err := rows.Scan(&rec.ID, &rec.ProfileID, &rec.DeviceID, &rec.TransportType, &rec.RawPath, &rec.DecodedText, &rec.NormalizedText, &clsJSON, &parsedJSON, &received); err != nil {
			return nil, err
		}
		if parsedJSON.Valid {
			rec.ParsedJSON = parsedJSON.String
		}
		_ = json.Unmarshal([]byte(clsJSON), &rec.Classification)
		rec.ReceivedAt, _ = time.Parse(time.RFC3339Nano, received)
		out = append(out, rec)
	}
	return out, rows.Err()
}

func (s *Store) GetCapture(id string) (CaptureRecord, []byte, error) {
	row := s.DB.QueryRow(`SELECT id, profile_id, device_id, transport_type, raw_path, decoded_text, normalized_text, classification_json, parsed_json, received_at FROM captures WHERE id = ?`, id)
	var rec CaptureRecord
	var clsJSON, received string
	var parsedJSON sql.NullString
	if err := row.Scan(&rec.ID, &rec.ProfileID, &rec.DeviceID, &rec.TransportType, &rec.RawPath, &rec.DecodedText, &rec.NormalizedText, &clsJSON, &parsedJSON, &received); err != nil {
		return CaptureRecord{}, nil, err
	}
	if parsedJSON.Valid {
		rec.ParsedJSON = parsedJSON.String
	}
	_ = json.Unmarshal([]byte(clsJSON), &rec.Classification)
	rec.ReceivedAt, _ = time.Parse(time.RFC3339Nano, received)
	raw, err := os.ReadFile(rec.RawPath)
	return rec, raw, err
}

func (s *Store) StartSession(profileID string, transport models.TransportType) (string, error) {
	id := util.NewID("sess")
	_, err := s.DB.Exec(`INSERT INTO sessions (id, profile_id, transport_type, state, started_at) VALUES (?, ?, ?, 'starting', ?)`, id, profileID, string(transport), time.Now().UTC().Format(time.RFC3339Nano))
	return id, err
}

func (s *Store) UpdateSessionState(id, state string) error {
	_, err := s.DB.Exec(`UPDATE sessions SET state = ? WHERE id = ?`, state, id)
	return err
}

func (s *Store) StopSession(id string) error {
	_, err := s.DB.Exec(`UPDATE sessions SET state = 'stopped', stopped_at = ? WHERE id = ?`, time.Now().UTC().Format(time.RFC3339Nano), id)
	return err
}

func (s *Store) SaveLearningSuggestions(profileID, captureID string, suggestions any) error {
	raw, _ := json.MarshalIndent(suggestions, "", "  ")
	_, err := s.DB.Exec(`INSERT INTO learning_runs (id, profile_id, capture_id, suggestions_json, created_at) VALUES (?, ?, ?, ?, ?)`, util.NewID("learn"), profileID, captureID, string(raw), time.Now().UTC().Format(time.RFC3339Nano))
	return err
}

func parseOptionalTime(v string) *time.Time {
	if v == "" {
		return nil
	}
	parsed, err := time.Parse(time.RFC3339Nano, v)
	if err != nil {
		return nil
	}
	return &parsed
}
