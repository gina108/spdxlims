package profile

import (
	"time"

	"instrument-connectivity/internal/models"
)

type MigrationBundle struct {
	Version      string                        `json:"version"`
	ExportedAt   time.Time                     `json:"exported_at"`
	Profiles     []Profile                     `json:"profiles"`
	NetworkLinks []models.NetworkDeviceLink    `json:"network_links"`
	Diagnostics  models.NetworkLinkDiagnostics `json:"diagnostics"`
	Integrity    MigrationBundleIntegrity      `json:"integrity"`
}

type MigrationBundleIntegrity struct {
	Algorithm     string `json:"algorithm"`
	PayloadSHA256 string `json:"payload_sha256"`
	Signature     string `json:"signature,omitempty"`
}

type MigrationProfileDiff struct {
	ProfileID       string                 `json:"profile_id"`
	Status          string                 `json:"status"`
	ChangedSections []string               `json:"changed_sections,omitempty"`
	ChangedFields   []string               `json:"changed_fields,omitempty"`
	FieldChanges    []MigrationFieldChange `json:"field_changes,omitempty"`
}

type MigrationFieldChange struct {
	Path     string `json:"path"`
	OldValue any    `json:"old_value,omitempty"`
	NewValue any    `json:"new_value,omitempty"`
}

type MigrationBundlePreview struct {
	IntegrityValid bool                            `json:"integrity_valid"`
	IntegrityError string                          `json:"integrity_error,omitempty"`
	ProfileDiffs   []MigrationProfileDiff          `json:"profile_diffs,omitempty"`
	LinkPreview    models.NetworkLinkImportPreview `json:"link_preview"`
}
