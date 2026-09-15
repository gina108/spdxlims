package runtime

import (
	"strings"
	"testing"

	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/profile"
	"instrument-connectivity/internal/transport"
)

type stubWorker struct{ stopped bool }

func (w *stubWorker) Stop() error { w.stopped = true; return nil }

func TestDiffProfileIncludesOldAndNewValues(t *testing.T) {
	current := profile.Profile{
		ID:           "generic-hl7",
		Name:         "Generic HL7",
		ProtocolHint: "hl7_v2",
		Transport:    profile.TransportSettings{Type: "tcp_client", RemoteAddress: "10.1.1.10:5000"},
		Mapping:      profile.MappingSettings{UnitNormalization: map[string]string{"mg/dl": "mg/dL"}},
	}
	incoming := current
	incoming.Name = "Generic HL7 Updated"
	incoming.Transport.RemoteAddress = "10.1.1.11:5000"
	incoming.Mapping.UnitNormalization = map[string]string{"mg/dl": "mg/dL", "mmol/l": "mmol/L"}

	sections, fields, changes := diffProfile(current, incoming)
	if len(sections) == 0 || len(fields) == 0 || len(changes) == 0 {
		t.Fatalf("diffProfile() = %#v %#v %#v, expected populated diff", sections, fields, changes)
	}

	foundName := false
	foundAddress := false
	for _, change := range changes {
		switch change.Path {
		case "general.name":
			foundName = change.OldValue == "Generic HL7" && change.NewValue == "Generic HL7 Updated"
		case "transport.remote_address":
			foundAddress = change.OldValue == "10.1.1.10:5000" && change.NewValue == "10.1.1.11:5000"
		}
	}
	if !foundName || !foundAddress {
		t.Fatalf("field changes = %#v", changes)
	}
}

func TestRedactMigrationBundle(t *testing.T) {
	bundle := profile.MigrationBundle{
		Profiles: []profile.Profile{{
			ID:             "generic-hl7",
			Name:           "Generic HL7",
			DeviceMetadata: map[string]string{"serial_number": "ABC123"},
			Transport:      profile.TransportSettings{RemoteAddress: "10.1.1.10:5000", DiscoveryCIDRs: []string{"10.1.1.0/24"}},
		}},
		NetworkLinks: []models.NetworkDeviceLink{{
			NetworkDeviceID: "net:10.1.1.10",
			RuntimeDeviceID: "analyzer-10",
		}},
	}
	redacted := redactMigrationBundle(bundle, models.RedactionOptions{
		RedactNetworkEndpoints:  true,
		RedactRuntimeDeviceIDs:  true,
		RedactProfileTransports: true,
		RedactDeviceMetadata:    true,
	})

	if redacted.Profiles[0].Transport.RemoteAddress == "10.1.1.10:5000" {
		t.Fatalf("expected remote address to be redacted: %#v", redacted.Profiles[0].Transport)
	}
	if redacted.Profiles[0].DeviceMetadata["serial_number"] == "ABC123" {
		t.Fatalf("expected device metadata to be redacted: %#v", redacted.Profiles[0].DeviceMetadata)
	}
	if redacted.NetworkLinks[0].NetworkDeviceID == "net:10.1.1.10" || redacted.NetworkLinks[0].RuntimeDeviceID == "analyzer-10" {
		t.Fatalf("expected network links to be redacted: %#v", redacted.NetworkLinks[0])
	}
}

func TestLoadOrCreateBundleHMACSecretMode(t *testing.T) {
	secret, mode, err := loadOrCreateBundleHMACSecret(t.TempDir(), "")
	if err != nil {
		t.Fatalf("loadOrCreateBundleHMACSecret() error = %v", err)
	}
	if mode != "generated" {
		t.Fatalf("mode = %q, want generated", mode)
	}
	if len(strings.TrimSpace(string(secret))) == 0 {
		t.Fatal("expected generated secret")
	}

	configured, mode, err := loadOrCreateBundleHMACSecret(t.TempDir(), "shared-secret")
	if err != nil {
		t.Fatalf("loadOrCreateBundleHMACSecret(configured) error = %v", err)
	}
	if mode != "configured" {
		t.Fatalf("mode = %q, want configured", mode)
	}
	if string(configured) != "shared-secret" {
		t.Fatalf("configured secret = %q", configured)
	}
}

func TestSharedTCPProfileMatchesRemoteHost(t *testing.T) {
	prof := profile.Profile{
		ID:        "mindray-bc30s",
		Transport: profile.TransportSettings{RemoteAddress: "10.0.0.2:5100"},
	}
	if !profileMatchesRemoteHost(prof, "10.0.0.2") {
		t.Fatal("expected remote_address host to match observed host")
	}
	if profileMatchesRemoteHost(prof, "10.0.0.3") {
		t.Fatal("did not expect different remote host to match")
	}
}

func TestHostOnlyAcceptsPlainIPAndEndpoint(t *testing.T) {
	cases := map[string]string{
		"10.0.0.2:5100":     "10.0.0.2",
		"10.0.0.2":          "10.0.0.2",
		"[fe80::1]:5100":    "fe80::1",
		"analyzer.local:80": "analyzer.local",
	}
	for input, want := range cases {
		if got := hostOnly(input); got != want {
			t.Fatalf("hostOnly(%q) = %q, want %q", input, got, want)
		}
	}
}

func TestLiveSessionForProfileReusesRunningWorker(t *testing.T) {
	app := &App{workers: map[string]transport.Worker{}, profileSessions: map[string]string{}}

	if _, ok := app.liveSessionForProfile("mindray-bc30s"); ok {
		t.Fatal("expected no live session before one is started")
	}

	worker := &stubWorker{}
	app.workers["sess_1"] = worker
	app.profileSessions["mindray-bc30s"] = "sess_1"

	got, ok := app.liveSessionForProfile("mindray-bc30s")
	if !ok || got != "sess_1" {
		t.Fatalf("liveSessionForProfile() = %q, %v; want sess_1, true", got, ok)
	}
	if _, ok := app.liveSessionForProfile("cm250"); ok {
		t.Fatal("did not expect a different profile to share the session")
	}

	// A mapping that outlived its worker must not block a restart.
	delete(app.workers, "sess_1")
	if _, ok := app.liveSessionForProfile("mindray-bc30s"); ok {
		t.Fatal("expected stale mapping to be ignored once the worker is gone")
	}
	if _, exists := app.profileSessions["mindray-bc30s"]; exists {
		t.Fatal("expected the stale mapping to be cleaned up")
	}
}

func TestStopWorkerClearsProfileMapping(t *testing.T) {
	worker := &stubWorker{}
	app := &App{
		workers:         map[string]transport.Worker{"sess_1": worker},
		profileSessions: map[string]string{"urinalysis-com6": "sess_1"},
	}

	app.stopWorker("sess_1")

	if !worker.stopped {
		t.Fatal("expected the worker to be stopped")
	}
	if _, exists := app.profileSessions["urinalysis-com6"]; exists {
		t.Fatal("expected the profile mapping to be removed so the profile can start again")
	}
	if _, ok := app.liveSessionForProfile("urinalysis-com6"); ok {
		t.Fatal("expected no live session after stopping")
	}
}

func TestLookupInstrumentCodeNormalized(t *testing.T) {
	prof := profile.Profile{Mapping: profile.MappingSettings{TestMappings: []profile.TestMapping{
		{Pattern: "GLU L", CanonicalAssay: "Glucose", LISTestID: "CM250-GLU"},
		{Pattern: "CRE L", CanonicalAssay: "Creatinine", LISTestID: "CM250-CRE"},
		{Pattern: "%HbA1c", CanonicalAssay: "HbA1c (%)", LISTestID: "CM250-HBA1CP"},
	}}}
	cases := map[string]string{
		"GLUL":         "GLU L", // LIMS-normalized raw_code -> spaced pattern
		"CREL":         "CRE L",
		"GLU L":        "GLU L", // exact pattern
		"CM250-GLU":    "GLU L", // lis_test_id
		"Glucose":      "GLU L", // canonical assay
		"%HbA1c":       "%HbA1c",
		"%HBA1C":       "%HbA1c", // LIMS-normalized raw_code keeps the %
		"nonexistent":  "",
	}
	for in, want := range cases {
		if got := lookupInstrumentCode(prof, in); got != want {
			t.Errorf("lookupInstrumentCode(%q) = %q, want %q", in, got, want)
		}
	}
}
