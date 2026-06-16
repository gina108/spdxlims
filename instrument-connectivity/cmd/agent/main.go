package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"time"

	"instrument-connectivity/internal/buildinfo"
	"instrument-connectivity/internal/config"
	"instrument-connectivity/internal/runtime"
)

func main() {
	var dataDir = flag.String("data-dir", filepath.Join("data", "instrument-engine"), "runtime data directory")
	var listen = flag.String("listen", "127.0.0.1:9088", "http listen address")
	var replay = flag.String("replay", "", "replay a saved capture file and print classification + normalized output")
	var profileID = flag.String("profile", "", "profile id for replay")
	var apiToken = flag.String("api-token", os.Getenv("INSTRUMENT_API_TOKEN"), "shared API token for /api and /api/v1 endpoints")
	var bundleHMACSecret = flag.String("bundle-hmac-secret", os.Getenv("INSTRUMENT_BUNDLE_HMAC_SECRET"), "optional shared HMAC secret for signing migration bundles")
	var retentionDays = flag.Int("retention-days", 30, "retain runtime history and diagnostics for this many days")
	var sessionEventMax = flag.Int("session-event-max", 5000, "maximum retained session history events")
	var runtimeErrorMax = flag.Int("runtime-error-max", 2000, "maximum retained runtime errors")
	var captureMax = flag.Int("capture-max", 2000, "maximum retained captures")
	var cleanupInterval = flag.Duration("cleanup-interval", 6*time.Hour, "background retention cleanup interval; set to 0 to disable scheduled cleanup")
	var installServiceFlag = flag.Bool("install-service", false, "install the agent as a Windows service")
	var uninstallServiceFlag = flag.Bool("uninstall-service", false, "uninstall the agent Windows service")
	var serviceName = flag.String("service-name", "InstrumentConnectivityEngine", "Windows service name")
	var serviceDisplayName = flag.String("service-display-name", "Instrument Connectivity Engine", "Windows service display name")
	var serviceDescription = flag.String("service-description", "Clinical LIS instrument connectivity runtime", "Windows service description")
	var noAutoResume = flag.Bool("no-auto-resume", false, "disable automatic session resume on startup")
	var versionFlag = flag.Bool("version", false, "print build version information")
	flag.Parse()

	var listenExplicit bool
	flag.Visit(func(f *flag.Flag) {
		if f.Name == "listen" {
			listenExplicit = true
		}
	})
	if !listenExplicit {
		if addr := readListenAddrFromConfig(*dataDir); addr != "" {
			*listen = addr
		}
	}

	if *versionFlag {
		fmt.Fprintln(os.Stdout, buildinfo.Current().String())
		return
	}

	cfg := config.Default(*dataDir, *listen)
	cfg.APIAuthToken = *apiToken
	cfg.BundleHMACSecret = *bundleHMACSecret
	cfg.AutoResume = !*noAutoResume
	cfg.RetentionDays = *retentionDays
	cfg.SessionEventMax = *sessionEventMax
	cfg.RuntimeErrorMax = *runtimeErrorMax
	cfg.CaptureMax = *captureMax
	cfg.CleanupInterval = *cleanupInterval

	if *installServiceFlag && *uninstallServiceFlag {
		log.Fatal("choose either -install-service or -uninstall-service, not both")
	}
	if *installServiceFlag {
		opts := windowsServiceOptions{
			Name:        *serviceName,
			DisplayName: *serviceDisplayName,
			Description: *serviceDescription,
			Args:        buildServiceArgs(cfg),
		}
		if err := installWindowsService(opts); err != nil {
			log.Fatalf("service install failed: %v", err)
		}
		fmt.Fprintf(os.Stdout, "installed Windows service %s\n", opts.Name)
		return
	}
	if *uninstallServiceFlag {
		if err := uninstallWindowsService(*serviceName); err != nil {
			log.Fatalf("service uninstall failed: %v", err)
		}
		fmt.Fprintf(os.Stdout, "uninstalled Windows service %s\n", *serviceName)
		return
	}

	if *replay != "" {
		app, err := runtime.New(cfg)
		if err != nil {
			log.Fatalf("bootstrap failed: %v", err)
		}
		defer app.Close()
		result, err := app.ReplayFile(*replay, *profileID)
		if err != nil {
			log.Fatalf("replay failed: %v", err)
		}
		fmt.Println(result.JSON())
		return
	}

	isService, err := runningAsWindowsService()
	if err != nil {
		log.Fatalf("service detection failed: %v", err)
	}
	if isService {
		if err := runWindowsService(*serviceName, cfg); err != nil {
			log.Fatalf("service runtime failed: %v", err)
		}
		return
	}

	if err := runConsole(cfg); err != nil {
		log.Fatalf("runtime stopped: %v", err)
	}
}

func readListenAddrFromConfig(dataDir string) string {
	data, err := os.ReadFile(filepath.Join(dataDir, "engine.json"))
	if err != nil {
		return ""
	}
	var cfg struct {
		ListenAddr string `json:"listen_addr"`
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return ""
	}
	return cfg.ListenAddr
}

func runConsole(cfg config.Config) error {
	app, err := runtime.New(cfg)
	if err != nil {
		return fmt.Errorf("bootstrap failed: %w", err)
	}
	defer app.Close()
	if err := app.Start(); err != nil {
		return fmt.Errorf("runtime start failed: %w", err)
	}
	fmt.Fprintf(os.Stdout, "build: %s\n", buildinfo.Summary())
	if cfg.APIAuthToken == "" {
		fmt.Fprintln(os.Stdout, "API authentication disabled for /api and /api/v1 endpoints")
	} else {
		fmt.Fprintln(os.Stdout, "API authentication enabled for /api and /api/v1 endpoints")
	}
	if cfg.CleanupInterval > 0 {
		fmt.Fprintf(os.Stdout, "scheduled retention cleanup enabled every %s\n", cfg.CleanupInterval)
	} else {
		fmt.Fprintln(os.Stdout, "scheduled retention cleanup disabled")
	}
	fmt.Fprintf(os.Stdout, "instrument connectivity engine listening on http://%s\n", cfg.ListenAddr)
	return app.Wait()
}
