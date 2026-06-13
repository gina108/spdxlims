package runtime

import (
	"strings"
	"testing"

	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/profile"
)

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
