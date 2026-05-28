package config

import (
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
}

func Default(dataDir, listenAddr string) Config {
    return Config{
        DataDir: dataDir,
        DBPath: filepath.Join(dataDir, "engine.db"),
        ProfileDir: filepath.Join(dataDir, "profiles"),
        CaptureDir: filepath.Join(dataDir, "captures"),
        BundleDir: filepath.Join(dataDir, "support-bundles"),
        ListenAddr: listenAddr,
        UIAssetsDir: filepath.Join("web"),
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
    }
}
