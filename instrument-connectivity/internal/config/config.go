package config

import (
    "os"
    "path/filepath"
    "time"
)

type Config struct {
    DataDir string
    DBPath string
    ProfileDir string
    CaptureDir string
    BundleDir string
    ListenAddr string
    UIAssetsDir string
    APIAuthToken string
    RetentionDays int
    SessionEventMax int
    RuntimeErrorMax int
    CaptureMax int
    CleanupInterval time.Duration
    NetworkDiscoveryEnabled bool
    NetworkProbePorts []int
    NetworkProbeTimeout time.Duration
    NetworkScanConcurrency int
    NetworkScanHostLimit int
    BundleHMACSecret string
    AutoResume bool
}

func Default(dataDir, listenAddr string) Config {
    return Config{
        DataDir: dataDir,
        DBPath: filepath.Join(dataDir, "engine.db"),
        ProfileDir: filepath.Join(dataDir, "profiles"),
        CaptureDir: filepath.Join(dataDir, "captures"),
        BundleDir: filepath.Join(dataDir, "support-bundles"),
        ListenAddr: listenAddr,
        UIAssetsDir: resolveUIAssetsDir(),
        RetentionDays: 30,
        SessionEventMax: 5000,
        RuntimeErrorMax: 2000,
        CaptureMax: 2000,
        CleanupInterval: 6 * time.Hour,
        NetworkDiscoveryEnabled: true,
        NetworkProbePorts: []int{5000, 3001, 4000, 8080, 9100},
        NetworkProbeTimeout: 250 * time.Millisecond,
        NetworkScanConcurrency: 24,
        NetworkScanHostLimit: 64,
        AutoResume: true,
    }
}

// resolveUIAssetsDir finds the web/ UI assets directory. It tries paths relative
// to the running executable first (works for service and manual binary runs where
// CWD may differ from the install root), then falls back to a CWD-relative path
// (which covers `go run` where the working directory is set to the source root).
func resolveUIAssetsDir() string {
    if exe, err := os.Executable(); err == nil {
        exeDir := filepath.Dir(exe)
        // Deployed layout: bin/exe with web/ in the parent (package root).
        // Dev layout: instrument-connectivity/bin/exe with web/ one level up.
        for _, candidate := range []string{
            filepath.Join(exeDir, "..", "web"),
            filepath.Join(exeDir, "web"),
        } {
            if info, err := os.Stat(candidate); err == nil && info.IsDir() {
                return filepath.Clean(candidate)
            }
        }
    }
    return "web"
}
