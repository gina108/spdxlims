package profile

import (
    "os"
    "path/filepath"
    "sort"
    "strings"

    "gopkg.in/yaml.v3"
)

type Profile struct {
    ID string `json:"id" yaml:"id"`
    Name string `json:"name" yaml:"name"`
    ProtocolHint string `json:"protocol_hint,omitempty" yaml:"protocol_hint,omitempty"`
    Bidirectional bool `json:"bidirectional,omitempty" yaml:"bidirectional,omitempty"`
    DeviceMetadata map[string]string `json:"device_metadata,omitempty" yaml:"device_metadata,omitempty"`
    Transport TransportSettings `json:"transport" yaml:"transport"`
    Parsing ParsingSettings `json:"parsing" yaml:"parsing"`
    Mapping MappingSettings `json:"mapping" yaml:"mapping"`
    LearningSettings LearningSettings `json:"learning_mode" yaml:"learning_mode"`
    Orders OrdersSettings `json:"orders,omitempty" yaml:"orders,omitempty"`
}

// OrdersSettings configures order-file (worklist) handling for instruments that
// import orders as drop files — e.g. the CM250, which reads one `.ANA` per order
// from Z:\Pedidos. When ArchiveOnResult is set, the engine retires the matching
// order file once a result for that order/sample number is stored.
type OrdersSettings struct {
    Directory       string `json:"directory,omitempty" yaml:"directory,omitempty"`
    FileExtension   string `json:"file_extension,omitempty" yaml:"file_extension,omitempty"`
    ArchiveOnResult bool   `json:"archive_on_result,omitempty" yaml:"archive_on_result,omitempty"`
    ArchiveDir      string `json:"archive_dir,omitempty" yaml:"archive_dir,omitempty"`
}

type TransportSettings struct {
    Type string `json:"type" yaml:"type"`
    SessionMode string `json:"session_mode,omitempty" yaml:"session_mode,omitempty"`
    SerialPort string `json:"serial_port,omitempty" yaml:"serial_port,omitempty"`
    BaudRate int `json:"baud_rate,omitempty" yaml:"baud_rate,omitempty"`
    DataBits int `json:"data_bits,omitempty" yaml:"data_bits,omitempty"`
    Parity string `json:"parity,omitempty" yaml:"parity,omitempty"`
    StopBits int `json:"stop_bits,omitempty" yaml:"stop_bits,omitempty"`
    ListenAddress string `json:"listen_address,omitempty" yaml:"listen_address,omitempty"`
    RemoteAddress string `json:"remote_address,omitempty" yaml:"remote_address,omitempty"`
    WatchDirectories []string `json:"watch_directories,omitempty" yaml:"watch_directories,omitempty"`
    DiscoveryCIDRs []string `json:"discovery_cidrs,omitempty" yaml:"discovery_cidrs,omitempty"`
    DiscoveryPorts []int `json:"discovery_ports,omitempty" yaml:"discovery_ports,omitempty"`
    DiscoveryHints []string `json:"discovery_hints,omitempty" yaml:"discovery_hints,omitempty"`
}

type ParsingSettings struct {
    Strategy string `json:"strategy" yaml:"strategy"`
    Delimiter string `json:"delimiter,omitempty" yaml:"delimiter,omitempty"`
    FieldExtractors map[string]string `json:"field_extractors,omitempty" yaml:"field_extractors,omitempty"`
    IgnorePatterns []string `json:"ignore_patterns,omitempty" yaml:"ignore_patterns,omitempty"`
}

type MappingSettings struct {
    TestCodeAliases    map[string][]string `json:"test_code_aliases,omitempty" yaml:"test_code_aliases,omitempty"`
    TestMappings       []TestMapping       `json:"test_mappings,omitempty" yaml:"test_mappings,omitempty"`
    UnitNormalization  map[string]string   `json:"unit_normalization,omitempty" yaml:"unit_normalization,omitempty"`
    ValueNormalization map[string]string   `json:"value_normalization,omitempty" yaml:"value_normalization,omitempty"`
    QCFilterPatterns   []string            `json:"qc_filter_patterns,omitempty" yaml:"qc_filter_patterns,omitempty"`
}

type TestMapping struct {
    MatchType       string                    `json:"match_type" yaml:"match_type"`
    Pattern         string                    `json:"pattern" yaml:"pattern"`
    CanonicalAssay  string                    `json:"canonical_assay" yaml:"canonical_assay"`
    LISTestID       string                    `json:"lis_test_id" yaml:"lis_test_id"`
    NormalizedUnits string                    `json:"normalized_units,omitempty" yaml:"normalized_units,omitempty"`
    ComponentIndex  *int                      `json:"component_index,omitempty" yaml:"component_index,omitempty"`
    SemiquantMap    map[string]SemiquantEntry `json:"semiquant_map,omitempty" yaml:"semiquant_map,omitempty"`
}

type SemiquantEntry struct {
    Display string   `json:"display,omitempty" yaml:"display,omitempty"`
    Value   *float64 `json:"value,omitempty" yaml:"value,omitempty"`
}

type LearningSettings struct {
    Enabled bool `json:"enabled" yaml:"enabled"`
}

type Store struct{ Dir string }

func NewStore(dir string) *Store { return &Store{Dir: dir} }
func (s *Store) Ensure() error { return os.MkdirAll(s.Dir, 0o755) }

func (s *Store) List() ([]Profile, error) {
    if err := s.Ensure(); err != nil { return nil, err }
    entries, err := os.ReadDir(s.Dir)
    if err != nil { return nil, err }
    profiles := []Profile{}
    for _, entry := range entries {
        if entry.IsDir() || !(strings.HasSuffix(entry.Name(), ".yaml") || strings.HasSuffix(entry.Name(), ".yml")) { continue }
        p, err := s.Get(strings.TrimSuffix(strings.TrimSuffix(entry.Name(), ".yaml"), ".yml"))
        if err == nil { profiles = append(profiles, p) }
    }
    sort.Slice(profiles, func(i, j int) bool { return profiles[i].Name < profiles[j].Name })
    return profiles, nil
}

func (s *Store) Get(id string) (Profile, error) {
    raw, err := os.ReadFile(filepath.Join(s.Dir, id+".yaml"))
    if err != nil { return Profile{}, err }
    var p Profile
    if err := yaml.Unmarshal(raw, &p); err != nil { return Profile{}, err }
    if p.ID == "" { p.ID = id }
    return p, nil
}

func (s *Store) Save(p Profile) error {
    if err := s.Ensure(); err != nil { return err }
    raw, err := yaml.Marshal(p)
    if err != nil { return err }
    return os.WriteFile(filepath.Join(s.Dir, p.ID+".yaml"), raw, 0o644)
}
