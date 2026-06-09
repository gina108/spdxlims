package runtime

import (
	"errors"
	"net"
	"sort"
	"strings"
	"sync"

	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/profile"
	"instrument-connectivity/internal/transport"
)

type sharedTCPSubscription struct {
	profile   profile.Profile
	sessionID string
	deviceID  string
}

type sharedTCPServer struct {
	address string
	worker  transport.Worker

	mu            sync.RWMutex
	subscriptions map[string]sharedTCPSubscription
}

type sharedTCPSubscriptionWorker struct {
	app       *App
	address   string
	sessionID string
}

func (w *sharedTCPSubscriptionWorker) Stop() error {
	return w.app.removeSharedTCPSubscription(w.address, w.sessionID)
}

func (a *App) startSharedTCPServerCapture(prof profile.Profile) (string, error) {
	address := strings.TrimSpace(prof.Transport.ListenAddress)
	if address == "" {
		return "", errors.New("tcp_server transport requires listen_address")
	}
	transportType := models.TransportTCPServer
	deviceID := transportDeviceID(prof)
	sessionID, err := a.captures.StartSession(prof.ID, transportType)
	if err != nil {
		return "", err
	}
	_ = a.linkRuntimeDevice(prof.ID, deviceID, prof.Transport, "profile_transport")
	_ = a.captures.UpdateRuntimeState(prof.ID, deviceID, transportType, sessionID, "starting", prof.Transport)
	_ = a.captures.AppendSessionEvent(sessionID, prof.ID, deviceID, transportType, "starting", map[string]any{"source": "runtime", "shared_listener": address})

	sub := sharedTCPSubscription{profile: prof, sessionID: sessionID, deviceID: deviceID}
	server, err := a.ensureSharedTCPServer(address, prof, a.makeQueryHandler(prof))
	if err != nil {
		_ = a.captures.StopSession(sessionID)
		_ = a.captures.UpdateRuntimeState(prof.ID, deviceID, transportType, sessionID, "error", prof.Transport)
		_ = a.captures.AppendSessionEvent(sessionID, prof.ID, deviceID, transportType, "error", map[string]any{"stage": "start_shared_tcp_listener", "message": err.Error()})
		a.recordError(prof.ID, deviceID, transportType, err, map[string]any{"stage": "start_shared_tcp_listener", "address": address}, prof.Transport)
		return "", err
	}
	server.mu.Lock()
	server.subscriptions[sessionID] = sub
	server.mu.Unlock()
	a.updateSharedTCPSubscriptionState(sub, "listening", map[string]any{"address": address, "shared_listener": true})

	a.workersMu.Lock()
	a.workers[sessionID] = &sharedTCPSubscriptionWorker{app: a, address: address, sessionID: sessionID}
	a.workersMu.Unlock()
	return sessionID, nil
}

func (a *App) ensureSharedTCPServer(address string, firstProfile profile.Profile, queryHandler transport.QueryHandler) (*sharedTCPServer, error) {
	a.workersMu.Lock()
	if server := a.tcpServers[address]; server != nil {
		a.workersMu.Unlock()
		return server, nil
	}
	server := &sharedTCPServer{address: address, subscriptions: map[string]sharedTCPSubscription{}}
	a.tcpServers[address] = server
	a.workersMu.Unlock()

	listenerProfile := firstProfile
	listenerProfile.Transport.ListenAddress = address
	listenerProfile.Transport.SessionMode = sharedTCPSessionMode(firstProfile)
	worker, err := transport.StartProfileWorker(listenerProfile, func(raw []byte, observedDeviceID string, observedTransport models.TransportType) error {
		return a.processSharedTCPPayload(address, raw, observedDeviceID, observedTransport)
	}, func(workerErr error, detail map[string]any) {
		a.recordSharedTCPError(address, workerErr, detail)
	}, func(state string, meta map[string]any) {
		a.updateSharedTCPState(address, state, meta)
	}, queryHandler)
	if err != nil {
		a.workersMu.Lock()
		delete(a.tcpServers, address)
		a.workersMu.Unlock()
		return nil, err
	}
	server.worker = worker
	return server, nil
}

func (a *App) removeSharedTCPSubscription(address, sessionID string) error {
	var stopServer transport.Worker
	a.workersMu.Lock()
	server := a.tcpServers[address]
	if server != nil {
		server.mu.Lock()
		delete(server.subscriptions, sessionID)
		empty := len(server.subscriptions) == 0
		server.mu.Unlock()
		if empty {
			stopServer = server.worker
			delete(a.tcpServers, address)
		}
	}
	a.workersMu.Unlock()
	if stopServer != nil {
		return stopServer.Stop()
	}
	return nil
}

func (a *App) processSharedTCPPayload(address string, raw []byte, observedDeviceID string, observedTransport models.TransportType) error {
	subs := a.matchSharedTCPSubscriptions(address, observedDeviceID)
	var firstErr error
	for _, sub := range subs {
		if _, _, err := a.ProcessPayload(raw, observedTransport, sub.profile.ID, observedDeviceID); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

func (a *App) matchSharedTCPSubscriptions(address, observedDeviceID string) []sharedTCPSubscription {
	a.workersMu.Lock()
	server := a.tcpServers[address]
	a.workersMu.Unlock()
	if server == nil {
		return nil
	}
	server.mu.RLock()
	all := make([]sharedTCPSubscription, 0, len(server.subscriptions))
	for _, sub := range server.subscriptions {
		all = append(all, sub)
	}
	server.mu.RUnlock()
	sort.Slice(all, func(i, j int) bool { return all[i].profile.ID < all[j].profile.ID })
	observedHost := hostOnly(observedDeviceID)
	matches := make([]sharedTCPSubscription, 0, len(all))
	for _, sub := range all {
		if profileMatchesRemoteHost(sub.profile, observedHost) {
			matches = append(matches, sub)
		}
	}
	if len(matches) > 0 {
		return matches
	}
	return all
}

func (a *App) recordSharedTCPError(address string, err error, detail map[string]any) {
	for _, sub := range a.matchSharedTCPSubscriptions(address, "") {
		a.recordError(sub.profile.ID, sub.deviceID, models.TransportTCPServer, err, detail, sub.profile.Transport)
	}
}

func (a *App) updateSharedTCPState(address, state string, meta map[string]any) {
	for _, sub := range a.matchSharedTCPSubscriptions(address, metaString(meta, "device_id")) {
		a.updateSharedTCPSubscriptionState(sub, state, meta)
	}
}

func (a *App) updateSharedTCPSubscriptionState(sub sharedTCPSubscription, state string, meta map[string]any) {
	_ = a.captures.UpdateSessionState(sub.sessionID, state)
	_ = a.captures.UpdateRuntimeState(sub.profile.ID, sub.deviceID, models.TransportTCPServer, sub.sessionID, state, sub.profile.Transport)
	_ = a.captures.AppendSessionEvent(sub.sessionID, sub.profile.ID, sub.deviceID, models.TransportTCPServer, state, meta)
}

func sharedTCPSessionMode(prof profile.Profile) string {
	if strings.EqualFold(prof.ProtocolHint, "astm") || strings.EqualFold(prof.Parsing.Strategy, "astm") {
		return "astm"
	}
	return prof.Transport.SessionMode
}

func profileMatchesRemoteHost(prof profile.Profile, observedHost string) bool {
	observedHost = strings.TrimSpace(observedHost)
	if observedHost == "" {
		return false
	}
	candidates := []string{
		prof.Transport.RemoteAddress,
		prof.DeviceMetadata["ip"],
		prof.DeviceMetadata["ip_address"],
		prof.DeviceMetadata["host"],
		prof.DeviceMetadata["hostname"],
	}
	for _, candidate := range candidates {
		if hostOnly(candidate) == observedHost {
			return true
		}
	}
	return false
}

func hostOnly(endpoint string) string {
	endpoint = strings.TrimSpace(endpoint)
	if endpoint == "" {
		return ""
	}
	if host, _, err := net.SplitHostPort(endpoint); err == nil {
		return strings.Trim(host, "[]")
	}
	if strings.Count(endpoint, ":") == 1 {
		if host, _, ok := strings.Cut(endpoint, ":"); ok {
			return strings.Trim(host, "[]")
		}
	}
	return strings.Trim(endpoint, "[]")
}

func metaString(meta map[string]any, key string) string {
	if meta == nil {
		return ""
	}
	value, _ := meta[key].(string)
	return value
}
