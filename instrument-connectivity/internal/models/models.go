package models

import "time"

type TransportType string
type ProtocolType string

const (
	TransportSerial    TransportType = "serial"
	TransportTCPClient TransportType = "tcp_client"
	TransportTCPServer TransportType = "tcp_server"
	TransportFileDrop  TransportType = "file_drop"
	TransportReplay    TransportType = "replay"

	ProtocolHL7        ProtocolType = "hl7_v2"
	ProtocolASTM       ProtocolType = "astm"
	ProtocolCSV        ProtocolType = "csv"
	ProtocolLineText   ProtocolType = "line_text"
	ProtocolFramedText ProtocolType = "framed_text"
	ProtocolBinary     ProtocolType = "binary"
	ProtocolWienerRES  ProtocolType = "wiener_res"
	ProtocolCM250      ProtocolType = "cm250"
	ProtocolUnknown    ProtocolType = "unknown"
)

type InstrumentMessage struct {
	MessageID       string         `json:"message_id"`
	SourceDeviceID  string         `json:"source_device_id"`
	SourceProfileID string         `json:"source_profile_id"`
	TransportType   TransportType  `json:"transport_type"`
	ProtocolType    ProtocolType   `json:"protocol_type"`
	ReceivedAt      time.Time      `json:"received_at"`
	RawPayloadRef   string         `json:"raw_payload_ref"`
	PatientID       string         `json:"patient_id,omitempty"`
	AccessionID     string         `json:"accession_id,omitempty"`
	SampleID        string         `json:"sample_id,omitempty"`
	SpecimenType    string         `json:"specimen_type,omitempty"`
	AnalyzerRunID   string         `json:"analyzer_run_id,omitempty"`
	Observations    []Observation  `json:"observations"`
	Metadata        map[string]any `json:"metadata,omitempty"`
}

type Observation struct {
	ObservationID      string     `json:"observation_id"`
	InstrumentTestCode string     `json:"instrument_test_code"`
	InstrumentTestName string     `json:"instrument_test_name,omitempty"`
	MappedLISTestID    string     `json:"mapped_lis_test_id,omitempty"`
	ValueRaw           string     `json:"value_raw"`
	ValueNumeric       *float64   `json:"value_numeric,omitempty"`
	ValueText          string     `json:"value_text,omitempty"`
	UnitsRaw           string     `json:"units_raw,omitempty"`
	UnitsNormalized    string     `json:"units_normalized,omitempty"`
	Flags              []string   `json:"flags,omitempty"`
	AbnormalFlag       string     `json:"abnormal_flag,omitempty"`
	ReferenceRange     string     `json:"reference_range,omitempty"`
	ResultStatus       string     `json:"result_status,omitempty"`
	ObservedAt         *time.Time `json:"observed_at,omitempty"`
}

type ClassificationScore struct {
	Protocol ProtocolType       `json:"protocol"`
	Score    float64            `json:"score"`
	Reasons  []string           `json:"reasons"`
	Signals  map[string]float64 `json:"signals,omitempty"`
}

type ClassificationResult struct {
	Selected   ProtocolType          `json:"selected"`
	Scores     []ClassificationScore `json:"scores"`
	Framing    string                `json:"framing"`
	Printable  float64               `json:"printable_ratio"`
	Delimiters map[string]int        `json:"delimiters,omitempty"`
}

type NormalizedPayload struct {
	RawBytes       []byte `json:"-"`
	DecodedText    string `json:"decoded_text"`
	NormalizedText string `json:"normalized_text"`
	Encoding       string `json:"encoding"`
}

type ParseResult struct {
	Classification ClassificationResult `json:"classification"`
	Payload        NormalizedPayload    `json:"payload"`
	Message        InstrumentMessage    `json:"message"`
	MappingTrace   []string             `json:"mapping_trace,omitempty"`
}

type DeviceFingerprint struct {
	PortName       string    `json:"port_name"`
	PortPath       string    `json:"port_path"`
	USBVID         string    `json:"usb_vid,omitempty"`
	USBPID         string    `json:"usb_pid,omitempty"`
	Manufacturer   string    `json:"manufacturer,omitempty"`
	Product        string    `json:"product,omitempty"`
	SerialNumber   string    `json:"serial_number,omitempty"`
	FirstSeen      time.Time `json:"first_seen"`
	LastSeen       time.Time `json:"last_seen"`
	StabilityScore float64   `json:"stability_score"`
}

type NetworkScanRequest struct {
	CIDRs     []string `json:"cidrs,omitempty"`
	Ports     []int    `json:"ports,omitempty"`
	Mode      string   `json:"mode,omitempty"`
	HostLimit int      `json:"host_limit,omitempty"`
}

type NetworkScanDiagnostics struct {
	Mode             string   `json:"mode"`
	CIDRs            []string `json:"cidrs,omitempty"`
	Ports            []int    `json:"ports,omitempty"`
	HostLimit        int      `json:"host_limit"`
	CandidateHosts   int      `json:"candidate_hosts"`
	NetworkDevices   int      `json:"network_devices"`
	SerialDevices    int      `json:"serial_devices"`
	DurationMS       int64    `json:"duration_ms"`
	Warnings         []string `json:"warnings,omitempty"`
	Recommendations  []string `json:"recommendations,omitempty"`
	ProfilePortCount int      `json:"profile_port_count,omitempty"`
}

type NetworkHistoryEntry struct {
	Value     string    `json:"value"`
	Count     int       `json:"count"`
	FirstSeen time.Time `json:"first_seen"`
	LastSeen  time.Time `json:"last_seen"`
}

type NetworkDeviceLink struct {
	NetworkDeviceID string    `json:"network_device_id"`
	ProfileID       string    `json:"profile_id"`
	RuntimeDeviceID string    `json:"runtime_device_id"`
	Source          string    `json:"source"`
	Confidence      float64   `json:"confidence"`
	SeenCount       int       `json:"seen_count"`
	FirstSeen       time.Time `json:"first_seen"`
	LastSeen        time.Time `json:"last_seen"`
}

type NetworkLinkDiagnostics struct {
	TotalLinks       int            `json:"total_links"`
	BySource         map[string]int `json:"by_source,omitempty"`
	ByConfidenceBand map[string]int `json:"by_confidence_band,omitempty"`
	ManualLinks      int            `json:"manual_links,omitempty"`
	AutomaticLinks   int            `json:"automatic_links,omitempty"`
}

type NetworkLinkImportConflict struct {
	ConflictID string            `json:"conflict_id"`
	Type       string            `json:"type"`
	Message    string            `json:"message"`
	Existing   NetworkDeviceLink `json:"existing"`
	Incoming   NetworkDeviceLink `json:"incoming"`
}

type NetworkLinkImportPreview struct {
	Links       []NetworkDeviceLink         `json:"links"`
	SafeLinks   []NetworkDeviceLink         `json:"safe_links,omitempty"`
	Conflicts   []NetworkLinkImportConflict `json:"conflicts,omitempty"`
	Diagnostics NetworkLinkDiagnostics      `json:"diagnostics"`
}

type NetworkLinkMergeDecision struct {
	ConflictID string `json:"conflict_id"`
	Resolution string `json:"resolution"`
}

type NetworkLinkAuditEntry struct {
	ID              string         `json:"id"`
	Action          string         `json:"action"`
	Actor           string         `json:"actor,omitempty"`
	NetworkDeviceID string         `json:"network_device_id,omitempty"`
	ProfileID       string         `json:"profile_id,omitempty"`
	RuntimeDeviceID string         `json:"runtime_device_id,omitempty"`
	Source          string         `json:"source,omitempty"`
	Confidence      float64        `json:"confidence,omitempty"`
	Detail          map[string]any `json:"detail,omitempty"`
	CreatedAt       time.Time      `json:"created_at"`
}

type NetworkLinkAuditFilter struct {
	Actor           string `json:"actor,omitempty"`
	ProfileID       string `json:"profile_id,omitempty"`
	NetworkDeviceID string `json:"network_device_id,omitempty"`
	Action          string `json:"action,omitempty"`
	Limit           int    `json:"limit,omitempty"`
}

type RedactionOptions struct {
	Preset                  string `json:"preset,omitempty"`
	RedactActors            bool   `json:"redact_actors,omitempty"`
	RedactNetworkEndpoints  bool   `json:"redact_network_endpoints,omitempty"`
	RedactRuntimeDeviceIDs  bool   `json:"redact_runtime_device_ids,omitempty"`
	RedactProfileTransports bool   `json:"redact_profile_transports,omitempty"`
	RedactDeviceMetadata    bool   `json:"redact_device_metadata,omitempty"`
}

type BundleSecretStatus struct {
	Algorithm        string `json:"algorithm"`
	Mode             string `json:"mode"`
	SharedConfigured bool   `json:"shared_configured"`
	Summary          string `json:"summary"`
}

type ReplayEventSummary struct {
	CaptureID string    `json:"capture_id"`
	Status    string    `json:"status"`
	Message   string    `json:"message,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

type NetworkDevice struct {
	DeviceID             string                `json:"device_id"`
	Host                 string                `json:"host,omitempty"`
	IP                   string                `json:"ip"`
	CIDR                 string                `json:"cidr,omitempty"`
	InterfaceName        string                `json:"interface_name,omitempty"`
	MAC                  string                `json:"mac,omitempty"`
	OpenPorts            []int                 `json:"open_ports,omitempty"`
	Reachability         string                `json:"reachability"`
	ProbeLatencyMS       int64                 `json:"probe_latency_ms,omitempty"`
	Banner               string                `json:"banner,omitempty"`
	BannerProtocol       string                `json:"banner_protocol,omitempty"`
	LikelyProtocols      []string              `json:"likely_protocols,omitempty"`
	SeenCount            int                   `json:"seen_count,omitempty"`
	FirstSeen            time.Time             `json:"first_seen"`
	LastSeen             time.Time             `json:"last_seen"`
	LastSeenStatus       string                `json:"last_seen_status,omitempty"`
	StabilityScore       float64               `json:"stability_score"`
	CorrelatedRuntimeIDs []string              `json:"correlated_runtime_ids,omitempty"`
	CorrelatedProfileIDs []string              `json:"correlated_profile_ids,omitempty"`
	RuntimeLinks         []NetworkDeviceLink   `json:"runtime_links,omitempty"`
	RecentCaptureCount   int                   `json:"recent_capture_count,omitempty"`
	RecentParseFailures  int                   `json:"recent_parse_failures,omitempty"`
	LastReplayAt         *time.Time            `json:"last_replay_at,omitempty"`
	LastReplayStatus     string                `json:"last_replay_status,omitempty"`
	LastReplayCaptureID  string                `json:"last_replay_capture_id,omitempty"`
	LastReplayMessage    string                `json:"last_replay_message,omitempty"`
	RecentReplayEvents   []ReplayEventSummary  `json:"recent_replay_events,omitempty"`
	RecentErrorExcerpts  []string              `json:"recent_error_excerpts,omitempty"`
	CIDRHistory          []NetworkHistoryEntry `json:"cidr_history,omitempty"`
	InterfaceHistory     []NetworkHistoryEntry `json:"interface_history,omitempty"`
	Metadata             map[string]any        `json:"metadata,omitempty"`
}

// PendingOrderRequest is the JSON body sent by the LIMS to pre-load an order
// so the engine can respond to ASTM host queries from analyzers.
type PendingOrderRequest struct {
	SampleID    string               `json:"sample_id"`
	PatientID   string               `json:"patient_id,omitempty"`
	PatientName string               `json:"patient_name,omitempty"`
	DOB         string               `json:"dob,omitempty"`
	Sex         string               `json:"sex,omitempty"`
	DoctorName  string               `json:"doctor_name,omitempty"`
	Tests       []PendingTestRequest `json:"tests"`
	ProfileID   string               `json:"profile_id,omitempty"`
}

// PendingTestRequest is one test within a PendingOrderRequest.
type PendingTestRequest struct {
	TestCode string `json:"test_code"`
	TestName string `json:"test_name,omitempty"`
}
