const output = document.getElementById('output');
const portsOut = document.getElementById('portsOut');
const profilesOut = document.getElementById('profilesOut');
const capturesOut = document.getElementById('capturesOut');
const runtimeStatusOut = document.getElementById('runtimeStatusOut');
const runtimeErrorsOut = document.getElementById('runtimeErrorsOut');
const sessionHistoryOut = document.getElementById('sessionHistoryOut');
const cleanupOut = document.getElementById('cleanupOut');
const maintenanceSummary = document.getElementById('maintenanceSummary');
const supportBundleSummaryOut = document.getElementById('supportBundleSummary');
const supportBundleDetailsOut = document.getElementById('supportBundleDetails');
const apiTokenInput = document.getElementById('apiToken');
const operatorNameInput = document.getElementById('operatorName');
const networkSummary = document.getElementById('networkSummary');
const networkDevicesList = document.getElementById('networkDevicesList');
const networkDeviceDetail = document.getElementById('networkDeviceDetail');
const networkReplayOut = document.getElementById('networkReplayOut');
const networkLinkList = document.getElementById('networkLinkList');
const networkLinkImportSummary = document.getElementById('networkLinkImportSummary');
const networkLinkMergeList = document.getElementById('networkLinkMergeList');
const networkLinkAuditOut = document.getElementById('networkLinkAuditOut');
const migrationBundleSummaryOut = document.getElementById('migrationBundleSummary');
const migrationBundleDetailsOut = document.getElementById('migrationBundleDetails');
const bundleSecretStatusOut = document.getElementById('bundleSecretStatus');
const migrationDiffCardsOut = document.getElementById('migrationDiffCards');
const bundleAuditSummaryOut = document.getElementById('bundleAuditSummary');
const bundleAuditCardsOut = document.getElementById('bundleAuditCards');

const DISCOVERY_HINT_PRESETS = [
  { id: 'hl7_listener', label: 'HL7 Listener', description: 'Common HL7/MLLP listener ports.', ports: [2575, 3001, 4000, 5000] },
  { id: 'http_admin', label: 'HTTP Admin', description: 'Common embedded web admin ports.', ports: [80, 8000, 8080, 8081, 8888] },
  { id: 'raw_socket', label: 'Raw Socket', description: 'Raw listener ports used by simple socket endpoints.', ports: [9100] },
  { id: 'line_admin', label: 'Line Admin', description: 'Classic line-oriented admin ports with safe CRLF greeting probes.', ports: [21, 23] },
  { id: 'astm_serial', label: 'ASTM Serial', description: 'Non-network hint kept for profile intent and future transport guidance.', ports: [] },
  { id: 'file_drop', label: 'File Drop', description: 'Non-network hint kept for file-drop profiles and future UX guidance.', ports: [] },
];

const state = {
  activePage: 'overviewPage',
  runtimeSnapshot: null,
  networkDevices: [],
  selectedNetworkDeviceID: '',
  capturesByDevice: {},
  profiles: [],
  networkLinkImportPreview: null,
  activeProfileSessionId: '',
};

apiTokenInput.value = localStorage.getItem('instrumentApiToken') || '';
operatorNameInput.value = localStorage.getItem('instrumentOperatorName') || '';

document.getElementById('saveToken').onclick = () => {
  localStorage.setItem('instrumentApiToken', apiTokenInput.value || '');
  localStorage.setItem('instrumentOperatorName', operatorNameInput.value || '');
  output.textContent = 'Saved API token for local browser requests.';
};

function apiHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  const token = (apiTokenInput.value || '').trim();
  if (token) headers['X-API-Key'] = token;
  const operator = (operatorNameInput.value || '').trim();
  if (operator) headers['X-Operator-Name'] = operator;
  return headers;
}

async function call(path, options = {}) {
  const res = await fetch(`/api/v1${path}`, { headers: apiHeaders(), ...options });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'request failed');
  return data;
}

function scanQuery() {
  const params = new URLSearchParams();
  const cidrs = document.getElementById('scanCIDRs').value.trim();
  const ports = document.getElementById('scanPortsInput').value.trim();
  if (cidrs) params.set('cidrs', cidrs);
  if (ports) params.set('ports', ports);
  const suffix = params.toString();
  return suffix ? `/ports/scan?${suffix}` : '/ports/scan';
}

function formatPorts(result) {
  const serial = Array.isArray(result.ports) ? result.ports : [];
  const network = Array.isArray(result.network_devices) ? result.network_devices : [];
  const serialCandidates = Array.isArray(result.serial_candidates) ? result.serial_candidates : [];
  return [
    `Serial devices: ${serial.length}`,
    `Network devices: ${network.length}`,
    '',
    'Network Devices:',
    network.length
      ? network.map((device) => {
          const likely = Array.isArray(device.likely_protocols) && device.likely_protocols.length
            ? ` likely=${device.likely_protocols.join(',')}`
            : '';
          return `${device.ip} ports=${(device.open_ports || []).join(',')} seen=${device.seen_count || 0} status=${device.last_seen_status || 'unknown'} banner=${device.banner_protocol || ''} ${device.banner || ''}${likely}`.trim();
        }).join('\n')
      : 'None detected.',
    '',
    'Serial Candidates:',
    serialCandidates.length ? JSON.stringify(serialCandidates, null, 2) : 'None',
    '',
    'Raw Scan JSON:',
    JSON.stringify(result, null, 2),
  ].join('\n');
}

function payload() {
  return {
    profile_id: document.getElementById('profileId').value,
    device_id: document.getElementById('deviceId').value,
    payload_text: document.getElementById('payloadText').value,
  };
}

function historyQuery() {
  const params = new URLSearchParams();
  const sessionId = document.getElementById('historySessionId').value.trim();
  const profileId = document.getElementById('historyProfileId').value.trim();
  const deviceId = document.getElementById('historyDeviceId').value.trim();
  params.set('limit', '50');
  if (sessionId) params.set('session_id', sessionId);
  if (profileId) params.set('profile_id', profileId);
  if (deviceId) params.set('device_id', deviceId);
  return `/runtime/history?${params.toString()}`;
}

function formatHistory(events) {
  if (!Array.isArray(events) || events.length === 0) return 'No session events found.';
  return events.map((event) => {
    const meta = event.meta && Object.keys(event.meta).length ? ` ${JSON.stringify(event.meta)}` : '';
    return `${event.created_at} | ${event.state} | session=${event.session_id} | profile=${event.profile_id} | device=${event.device_id}${meta}`;
  }).join('\n');
}

function formatCleanup(report) {
  if (!report) return 'No cleanup report available.';
  return [
    `Executed At: ${report.executed_at}`,
    `Retention Days: ${report.policy?.retention_days ?? 0}`,
    `Session Event Max: ${report.policy?.session_event_max ?? 0}`,
    `Runtime Error Max: ${report.policy?.runtime_error_max ?? 0}`,
    `Capture Max: ${report.policy?.capture_max ?? 0}`,
    '',
    `Deleted Captures: ${report.deleted_captures ?? 0}`,
    `Deleted Capture Files: ${report.deleted_capture_files ?? 0}`,
    `Deleted Runtime Errors: ${report.deleted_runtime_errors ?? 0}`,
    `Deleted Session Events: ${report.deleted_session_events ?? 0}`,
    `Deleted Unmapped Observations: ${report.deleted_unmapped_observations ?? 0}`,
  ].join('\n');
}

function renderMaintenance(status, snapshot = {}) {
  const cleanup = status?.last_cleanup || null;
  const nextCleanupAt = status?.next_cleanup_at || 'not scheduled';
  const interval = status?.cleanup_interval || 'disabled';
  const updatedAt = status?.updated_at || 'not recorded';
  const deviceCount = Array.isArray(snapshot.devices) ? snapshot.devices.length : 0;
  const networkDeviceCount = Array.isArray(snapshot.network_devices) ? snapshot.network_devices.length : 0;
  const unmappedCount = Array.isArray(snapshot.unmapped) ? snapshot.unmapped.length : 0;

  if (!cleanup) {
    maintenanceSummary.textContent = `No cleanup report recorded yet. Next scheduled run: ${nextCleanupAt}. Interval: ${interval}.`;
  } else {
    const totalDeleted = (cleanup.deleted_captures || 0)
      + (cleanup.deleted_runtime_errors || 0)
      + (cleanup.deleted_session_events || 0)
      + (cleanup.deleted_unmapped_observations || 0);
    maintenanceSummary.textContent = `Last cleanup ran at ${cleanup.executed_at}. Deleted ${totalDeleted} database rows and ${cleanup.deleted_capture_files || 0} capture files. Next scheduled run: ${nextCleanupAt}.`;
  }

  cleanupOut.textContent = [
    `Cleanup Interval: ${interval}`,
    `Next Cleanup At: ${nextCleanupAt}`,
    `Status Updated At: ${updatedAt}`,
    `Visible Runtime Devices: ${deviceCount}`,
    `Visible Network Devices: ${networkDeviceCount}`,
    `Visible Unmapped Rows: ${unmappedCount}`,
    '',
    cleanup ? formatCleanup(cleanup) : 'No cleanup report recorded yet.',
  ].join('\n');
}

function escapeHTML(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function relativeLastSeen(lastSeen) {
  if (!lastSeen) return 'unknown';
  const diffMs = Date.now() - new Date(lastSeen).getTime();
  if (Number.isNaN(diffMs)) return 'unknown';
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function protocolSummary(device) {
  const set = new Set();
  if (device.banner_protocol) set.add(device.banner_protocol);
  (device.likely_protocols || []).forEach((value) => set.add(value));
  return Array.from(set);
}

function historyMarkup(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return '<span class="history-chip muted">No history yet</span>';
  return entries.map((entry) => `<span class="history-chip">${escapeHTML(entry.value)} <strong>${entry.count}</strong></span>`).join('');
}

function replayStatusSummary(device) {
  if (!device.last_replay_at) return 'No replay yet';
  return `${device.last_replay_status || 'unknown'} ${relativeLastSeen(device.last_replay_at)}`;
}

function replayHistoryMarkup(device) {
  const events = Array.isArray(device.recent_replay_events) ? device.recent_replay_events : [];
  if (!events.length) return '<span class="muted">No replay history</span>';
  return events.map((event) => `<span class="history-chip">${escapeHTML(event.status)} ${escapeHTML(relativeLastSeen(event.created_at))}</span>`).join('');
}

function recentErrorsMarkup(device) {
  const errors = Array.isArray(device.recent_error_excerpts) ? device.recent_error_excerpts : [];
  if (!errors.length) return '<span class="muted">No recent parse failures</span>';
  return errors.map((item) => `<div class="muted">${escapeHTML(item)}</div>`).join('');
}

function networkDeviceMatches(device, filters) {
  const haystack = [
    device.device_id,
    device.ip,
    device.host,
    device.cidr,
    device.interface_name,
    device.banner,
    ...(device.likely_protocols || []),
    device.banner_protocol,
  ].join(' ').toLowerCase();
  if (filters.search && !haystack.includes(filters.search)) return false;
  if (filters.status && (device.last_seen_status || '') !== filters.status) return false;
  if (filters.protocol && !protocolSummary(device).includes(filters.protocol)) return false;
  return true;
}

function networkFilters() {
  return {
    search: document.getElementById('networkSearch').value.trim().toLowerCase(),
    status: document.getElementById('networkStatusFilter').value,
    protocol: document.getElementById('networkProtocolFilter').value,
  };
}

function availableProtocols(devices) {
  const values = new Set();
  devices.forEach((device) => protocolSummary(device).forEach((value) => values.add(value)));
  return Array.from(values).sort();
}

function renderProtocolFilter(devices) {
  const select = document.getElementById('networkProtocolFilter');
  const current = select.value;
  const options = ['<option value="">Any protocol</option>']
    .concat(availableProtocols(devices).map((value) => `<option value="${escapeHTML(value)}">${escapeHTML(value)}</option>`));
  select.innerHTML = options.join('');
  if (Array.from(select.options).some((option) => option.value === current)) {
    select.value = current;
  }
}

function renderNetworkSummary(devices, filtered) {
  const online = filtered.filter((device) => device.last_seen_status === 'online').length;
  const recent = filtered.filter((device) => device.last_seen_status === 'recent').length;
  const stale = filtered.filter((device) => device.last_seen_status === 'stale').length;
  networkSummary.textContent = `Showing ${filtered.length} of ${devices.length} discovered network devices. Online: ${online}. Recent: ${recent}. Stale: ${stale}.`;
}

function selectedDevice() {
  return state.networkDevices.find((device) => device.device_id === state.selectedNetworkDeviceID) || null;
}

function renderSelectedDevice() {
  const device = selectedDevice();
  if (!device) {
    networkDeviceDetail.textContent = 'Select a device to inspect its history and recent captures.';
    networkLinkList.innerHTML = '<span class="muted">No runtime links loaded yet.</span>';
    return;
  }
  const captures = state.capturesByDevice[device.device_id] || [];
  const lines = [
    `Device ID: ${device.device_id}`,
    `IP: ${device.ip}`,
    `Host: ${device.host || 'n/a'}`,
    `Status: ${device.last_seen_status || 'unknown'} (${relativeLastSeen(device.last_seen)})`,
    `Open Ports: ${(device.open_ports || []).join(', ') || 'n/a'}`,
    `Likely Protocols: ${protocolSummary(device).join(', ') || 'n/a'}`,
    `Seen Count: ${device.seen_count || 0}`,
    `Stability Score: ${(device.stability_score || 0).toFixed(2)}`,
    `Recent Capture Count: ${device.recent_capture_count || 0}`,
    `Recent Parse Failures: ${device.recent_parse_failures || 0}`,
    `Last Replay: ${replayStatusSummary(device)}`,
    `Current CIDR: ${device.cidr || 'n/a'}`,
    `Current Interface: ${device.interface_name || 'n/a'}`,
    `Correlated Runtime IDs: ${(device.correlated_runtime_ids || []).join(', ') || 'n/a'}`,
    `Correlated Profiles: ${(device.correlated_profile_ids || []).join(', ') || 'n/a'}`,
    '',
    'CIDR History:',
    ...(device.cidr_history || []).map((entry) => `- ${entry.value} (${entry.count}) last=${entry.last_seen}`),
    '',
    'Interface History:',
    ...(device.interface_history || []).map((entry) => `- ${entry.value} (${entry.count}) last=${entry.last_seen}`),
    '',
    'Runtime Links:',
    ...(device.runtime_links || []).map((link) => `- ${link.profile_id} | ${link.runtime_device_id} | source=${link.source} | confidence=${(link.confidence || 0).toFixed(2)} | seen=${link.seen_count}`),
    '',
    'Recent Captures:',
    ...(captures.length
      ? captures.map((capture) => `- ${capture.id} | ${capture.profile_id} | ${capture.received_at}`)
      : ['- No captures linked to this exact device ID yet.']),
  ];
  networkDeviceDetail.textContent = lines.join('\n');
  document.getElementById('linkProfileId').value = device.correlated_profile_ids?.[0] || '';
  document.getElementById('linkRuntimeDeviceId').value = device.correlated_runtime_ids?.[0] || '';
  networkLinkList.innerHTML = (device.runtime_links || []).length
    ? device.runtime_links.map((link) => `<button class="link-button" data-delete-link="${escapeHTML([device.device_id, link.profile_id, link.runtime_device_id].join('|'))}">${escapeHTML(link.profile_id)} · ${escapeHTML(link.runtime_device_id)} · ${escapeHTML(link.source)} · conf=${escapeHTML((link.confidence || 0).toFixed(2))}</button>`).join('')
    : '<span class="muted">No runtime links loaded yet.</span>';
  document.querySelectorAll('[data-delete-link]').forEach((button) => {
    button.onclick = async () => {
      const [networkDeviceID, profileID, runtimeDeviceID] = button.dataset.deleteLink.split('|');
      await deleteNetworkLink(networkDeviceID, profileID, runtimeDeviceID);
    };
  });
}

function renderProfileEditor() {
  const select = document.getElementById('profileEditorSelect');
  const current = select.value;
  select.innerHTML = ['<option value="">Select profile</option>']
    .concat(state.profiles.map((profile) => `<option value="${escapeHTML(profile.id)}">${escapeHTML(profile.name || profile.id)}</option>`))
    .join('');
  if (Array.from(select.options).some((option) => option.value === current)) {
    select.value = current;
  }
  const selected = state.profiles.find((profile) => profile.id === select.value);
  document.getElementById('profileEditorId').value = selected?.id || '';
  document.getElementById('profileEditorName').value = selected?.name || '';
  document.getElementById('profileEditorVendor').value = selected?.device_metadata?.vendor || '';
  document.getElementById('profileEditorModel').value = selected?.device_metadata?.model || '';
  document.getElementById('profileEditorProtocolHint').value = selected?.protocol_hint || '';
  document.getElementById('profileTransportType').value = selected?.transport?.type || 'serial';
  document.getElementById('profileSessionMode').value = selected?.transport?.session_mode || '';
  document.getElementById('profileSerialPort').value = selected?.transport?.serial_port || '';
  document.getElementById('profileBaudRate').value = selected?.transport?.baud_rate || '';
  document.getElementById('profileDataBits').value = selected?.transport?.data_bits || '';
  document.getElementById('profileParity').value = selected?.transport?.parity || '';
  document.getElementById('profileStopBits').value = selected?.transport?.stop_bits || '';
  document.getElementById('profileListenAddress').value = selected?.transport?.listen_address || '';
  document.getElementById('profileRemoteAddress').value = selected?.transport?.remote_address || '';
  document.getElementById('profileWatchDirectories').value = selected?.transport?.watch_directories?.join(', ') || '';
  document.getElementById('profileParsingStrategy').value = selected?.parsing?.strategy || '';
  document.getElementById('profileDiscoveryHints').value = selected?.transport?.discovery_hints?.join(', ') || '';
  renderDiscoveryHintPresets();
  renderDiscoveryHintValidation();
  renderDiscoveryHintHelp();
  renderProfileCaptureSummary();
}

function supportedDiscoveryHintMap() {
  return Object.fromEntries(DISCOVERY_HINT_PRESETS.map((hint) => [hint.id, hint]));
}

function parseDiscoveryHints() {
  return document.getElementById('profileDiscoveryHints').value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderDiscoveryHintPresets() {
  const container = document.getElementById('discoveryHintPresets');
  const selected = new Set(parseDiscoveryHints());
  container.innerHTML = DISCOVERY_HINT_PRESETS.map((hint) => `<button type="button" class="preset-chip${selected.has(hint.id) ? ' active' : ''}" data-hint-toggle="${escapeHTML(hint.id)}" title="${escapeHTML(hint.description)}">${escapeHTML(hint.label)}</button>`).join('');
  document.querySelectorAll('[data-hint-toggle]').forEach((button) => {
    button.onclick = () => toggleDiscoveryHint(button.dataset.hintToggle);
  });
}

function renderDiscoveryHintValidation() {
  const validation = document.getElementById('profileHintValidation');
  const hints = parseDiscoveryHints();
  if (!document.getElementById('profileEditorSelect').value) {
    validation.className = 'summary-card';
    validation.textContent = 'Choose a profile to review supported discovery hints.';
    return;
  }
  const supported = supportedDiscoveryHintMap();
  const unknown = hints.filter((hint) => !supported[hint]);
  if (unknown.length) {
    validation.className = 'summary-card validation-error';
    validation.textContent = `Unsupported hints: ${unknown.join(', ')}. Use the preset buttons or one of: ${DISCOVERY_HINT_PRESETS.map((hint) => hint.id).join(', ')}.`;
    return;
  }
  const summary = hints.length
    ? hints.map((hint) => `${hint}: ${supported[hint]?.description || ''}`.trim()).join(' | ')
    : 'No discovery hints selected. The profile will use only explicit discovery ports/CIDRs.';
  validation.className = 'summary-card validation-ok';
  validation.textContent = summary;
}

function renderDiscoveryHintHelp() {
  const target = document.getElementById('profileHintHelp');
  const hints = parseDiscoveryHints();
  const supported = supportedDiscoveryHintMap();
  if (!hints.length) {
    target.innerHTML = '<span class="muted">Hint port expansions will appear here.</span>';
    return;
  }
  target.innerHTML = hints.map((hint) => {
    const meta = supported[hint];
    if (!meta) {
      return `<div class="hint-help-card"><strong>${escapeHTML(hint)}</strong><div class="muted">Unknown hint. No port expansion available.</div></div>`;
    }
    const ports = Array.isArray(meta.ports) && meta.ports.length ? meta.ports.join(', ') : 'No network ports added';
    return `<div class="hint-help-card"><strong>${escapeHTML(meta.label)}</strong><div>${escapeHTML(meta.description)}</div><div class="muted">Expanded ports: ${escapeHTML(ports)}</div></div>`;
  }).join('');
}

function toggleDiscoveryHint(hintID) {
  const hints = parseDiscoveryHints();
  const set = new Set(hints);
  if (set.has(hintID)) {
    set.delete(hintID);
  } else {
    set.add(hintID);
  }
  document.getElementById('profileDiscoveryHints').value = Array.from(set).sort().join(', ');
  renderDiscoveryHintPresets();
  renderDiscoveryHintValidation();
  renderDiscoveryHintHelp();
}

function formatLinkDiagnostics(diagnostics) {
  if (!diagnostics) return 'No runtime-link diagnostics loaded.';
  const bySource = Object.entries(diagnostics.by_source || {}).map(([key, value]) => `${key}: ${value}`).join(', ') || 'none';
  const byConfidence = Object.entries(diagnostics.by_confidence_band || {}).map(([key, value]) => `${key}: ${value}`).join(', ') || 'none';
  return [
    `Total links: ${diagnostics.total_links || 0}`,
    `Manual links: ${diagnostics.manual_links || 0}`,
    `Automatic links: ${diagnostics.automatic_links || 0}`,
    `By source: ${bySource}`,
    `By confidence: ${byConfidence}`,
  ].join('\n');
}

function formatMigrationPreview(preview) {
  const lines = [
    `Integrity valid: ${preview?.integrity_valid ? 'yes' : 'no'}`,
  ];
  if (preview?.integrity_error) {
    lines.push(`Integrity error: ${preview.integrity_error}`);
  }
  lines.push('');
  lines.push('Profile diffs:');
  if (Array.isArray(preview?.profile_diffs) && preview.profile_diffs.length) {
    preview.profile_diffs.forEach((diff) => {
      lines.push(`- ${diff.profile_id}: ${diff.status}${(diff.changed_sections || []).length ? ` (${diff.changed_sections.join(', ')})` : ''}`);
      if (Array.isArray(diff.field_changes) && diff.field_changes.length) {
        diff.field_changes.forEach((field) => {
          lines.push(`  ${field.path}`);
          lines.push(`    old: ${formatDiffValue(field.old_value)}`);
          lines.push(`    new: ${formatDiffValue(field.new_value)}`);
        });
      } else {
        (diff.changed_fields || []).forEach((field) => lines.push(`  field: ${field}`));
      }
    });
  } else {
    lines.push('- No profile changes detected.');
  }
  lines.push('');
  lines.push(`Link conflicts: ${(preview?.link_preview?.conflicts || []).length}`);
  lines.push(`Safe links: ${(preview?.link_preview?.safe_links || []).length}`);
  return lines.join('\n');
}

function formatDiffValue(value) {
  if (typeof value === 'undefined') return '(missing)';
  if (value === null) return 'null';
  if (typeof value === 'string') return value || '""';
  return JSON.stringify(value);
}

function renderSupportBundleDiagnostics(diagnostics) {
  supportBundleSummaryOut.textContent = diagnostics
    ? `Runtime links: ${diagnostics.total_links || 0}. Manual: ${diagnostics.manual_links || 0}. Automatic: ${diagnostics.automatic_links || 0}.`
    : 'No support-bundle summary loaded yet.';
  supportBundleDetailsOut.textContent = formatLinkDiagnostics(diagnostics);
}

function renderBundleSecretStatus(status) {
  if (!status) {
    bundleSecretStatusOut.textContent = 'Bundle signing status not loaded yet.';
    return;
  }
  const mode = status.shared_configured ? 'shared configured secret' : 'locally generated secret';
  bundleSecretStatusOut.textContent = `Bundle signing: ${mode}. Algorithm: ${status.algorithm || 'unknown'}. ${status.summary || ''}`.trim();
}

function buildRedactionParams(prefix) {
  const params = new URLSearchParams();
  const preset = document.getElementById(`${prefix}RedactionPreset`)?.value || '';
  if (preset) params.set('redaction_preset', preset);
  if (document.getElementById(`${prefix}RedactActors`)?.checked) params.set('redact_actors', 'true');
  if (document.getElementById(`${prefix}RedactNetworkEndpoints`)?.checked) params.set('redact_network_endpoints', 'true');
  if (document.getElementById(`${prefix}RedactRuntimeIDs`)?.checked) params.set('redact_runtime_device_ids', 'true');
  if (document.getElementById(`${prefix}RedactProfileTransports`)?.checked) params.set('redact_profile_transports', 'true');
  if (document.getElementById(`${prefix}RedactDeviceMetadata`)?.checked) params.set('redact_device_metadata', 'true');
  return params;
}

function applyPresetToggles(prefix) {
  const preset = document.getElementById(`${prefix}RedactionPreset`)?.value || '';
  const isExternal = preset === 'external_share';
  const actorToggle = document.getElementById(`${prefix}RedactActors`);
  const endpointToggle = document.getElementById(`${prefix}RedactNetworkEndpoints`);
  const runtimeToggle = document.getElementById(`${prefix}RedactRuntimeIDs`);
  const transportToggle = document.getElementById(`${prefix}RedactProfileTransports`);
  const metadataToggle = document.getElementById(`${prefix}RedactDeviceMetadata`);
  if (actorToggle) actorToggle.checked = isExternal;
  if (endpointToggle) endpointToggle.checked = isExternal || preset === 'identifiers_only';
  if (runtimeToggle) runtimeToggle.checked = isExternal || preset === 'identifiers_only';
  if (transportToggle) transportToggle.checked = isExternal || preset === 'transport_only';
  if (metadataToggle) metadataToggle.checked = isExternal || preset === 'metadata_only';
}

function renderMigrationDiffCards(preview) {
  const diffs = Array.isArray(preview?.profile_diffs) ? preview.profile_diffs : [];
  const changed = diffs.filter((diff) => Array.isArray(diff.field_changes) && diff.field_changes.length);
  if (!changed.length) {
    migrationDiffCardsOut.innerHTML = '<div class="empty-state">Preview a bundle to see side-by-side field changes.</div>';
    return;
  }
  migrationDiffCardsOut.innerHTML = changed.map((diff) => `
    <article class="diff-card">
      <h3>${escapeHTML(diff.profile_id)} · ${escapeHTML(diff.status)}</h3>
      ${(diff.field_changes || []).map((field) => `
        <div class="diff-row">
          <div class="diff-path">${escapeHTML(field.path)}</div>
          <div class="diff-column">
            <strong>Current</strong>
            <div class="diff-value">${escapeHTML(formatDiffValue(field.old_value))}</div>
          </div>
          <div class="diff-column">
            <strong>Incoming</strong>
            <div class="diff-value">${escapeHTML(formatDiffValue(field.new_value))}</div>
          </div>
        </div>
      `).join('')}
    </article>
  `).join('');
}

function collectMergeDecisions() {
  return Array.from(document.querySelectorAll('input[name^="merge-"]:checked')).map((input) => ({
    conflict_id: input.name.replace('merge-', ''),
    resolution: input.value,
  }));
}

function renderNetworkLinkImportPreview(preview) {
  state.networkLinkImportPreview = preview;
  const safeCount = Array.isArray(preview?.safe_links) ? preview.safe_links.length : 0;
  const conflictCount = Array.isArray(preview?.conflicts) ? preview.conflicts.length : 0;
  const diagnosticsText = formatLinkDiagnostics(preview?.diagnostics);
  networkLinkImportSummary.textContent = `Preview loaded. Safe links: ${safeCount}. Conflicts: ${conflictCount}. ${diagnosticsText.replace(/\n/g, ' ')}`;
  if (!conflictCount) {
    networkLinkMergeList.innerHTML = '<span class="muted">No import conflicts detected. Import will only add/update safe links.</span>';
    return;
  }
  networkLinkMergeList.innerHTML = preview.conflicts.map((conflict) => `
    <div class="merge-card">
      <strong>${escapeHTML(conflict.type)}</strong>
      <div>${escapeHTML(conflict.message || '')}</div>
      <div class="muted">Existing: ${escapeHTML(conflict.existing.network_device_id)} · ${escapeHTML(conflict.existing.profile_id)} · ${escapeHTML(conflict.existing.runtime_device_id)} · ${escapeHTML(conflict.existing.source)} · conf=${escapeHTML((conflict.existing.confidence || 0).toFixed(2))}</div>
      <div class="muted">Imported: ${escapeHTML(conflict.incoming.network_device_id)} · ${escapeHTML(conflict.incoming.profile_id)} · ${escapeHTML(conflict.incoming.runtime_device_id)} · ${escapeHTML(conflict.incoming.source)} · conf=${escapeHTML((conflict.incoming.confidence || 0).toFixed(2))}</div>
      <div class="merge-actions">
        <label><input type="radio" name="merge-${escapeHTML(conflict.conflict_id)}" value="keep_existing" checked /> Keep existing</label>
        <label><input type="radio" name="merge-${escapeHTML(conflict.conflict_id)}" value="use_imported" /> Use imported</label>
      </div>
    </div>
  `).join('');
}

function bindNetworkDeviceActions() {
  document.querySelectorAll('[data-device-select]').forEach((button) => {
    button.onclick = async () => {
      state.selectedNetworkDeviceID = button.dataset.deviceSelect;
      renderNetworkDevices();
      await loadCapturesForDevice(state.selectedNetworkDeviceID, false);
    };
  });
  document.querySelectorAll('[data-device-captures]').forEach((button) => {
    button.onclick = async () => {
      await loadCapturesForDevice(button.dataset.deviceCaptures, true);
    };
  });
  document.querySelectorAll('[data-replay-capture]').forEach((button) => {
    button.onclick = async () => {
      await replayCapture(button.dataset.replayCapture, button.dataset.profileId || '');
    };
  });
}

function renderNetworkDevices() {
  const filters = networkFilters();
  const devices = state.networkDevices.slice();
  renderProtocolFilter(devices);
  const filtered = devices.filter((device) => networkDeviceMatches(device, filters));
  renderNetworkSummary(devices, filtered);
  if (!filtered.length) {
    networkDevicesList.innerHTML = '<div class="empty-state">No network devices match the current filters.</div>';
    renderSelectedDevice();
    return;
  }

  networkDevicesList.innerHTML = filtered.map((device) => {
    const captures = state.capturesByDevice[device.device_id] || [];
    const selected = state.selectedNetworkDeviceID === device.device_id ? ' selected' : '';
    const protocols = protocolSummary(device).join(', ') || 'n/a';
    const latestCapture = captures[0] || null;
    return `
      <article class="device-card${selected}">
        <div class="device-card-header">
          <div>
            <h3>${escapeHTML(device.host || device.ip)}</h3>
            <p>${escapeHTML(device.ip)}${device.cidr ? ` <span class="muted">in ${escapeHTML(device.cidr)}</span>` : ''}</p>
          </div>
          <span class="status-pill status-${escapeHTML(device.last_seen_status || 'unknown')}">${escapeHTML(device.last_seen_status || 'unknown')}</span>
        </div>
        <div class="device-meta">
          <span><strong>Ports:</strong> ${escapeHTML((device.open_ports || []).join(', ') || 'n/a')}</span>
          <span><strong>Protocols:</strong> ${escapeHTML(protocols)}</span>
          <span><strong>Seen:</strong> ${escapeHTML(String(device.seen_count || 0))}</span>
          <span><strong>Stability:</strong> ${escapeHTML((device.stability_score || 0).toFixed(2))}</span>
          <span><strong>Last seen:</strong> ${escapeHTML(relativeLastSeen(device.last_seen))}</span>
          <span><strong>Interface:</strong> ${escapeHTML(device.interface_name || 'n/a')}</span>
          <span><strong>Captures:</strong> ${escapeHTML(String(device.recent_capture_count || 0))}</span>
          <span><strong>Parse failures:</strong> ${escapeHTML(String(device.recent_parse_failures || 0))}</span>
          <span><strong>Replay:</strong> ${escapeHTML(replayStatusSummary(device))}</span>
          <span><strong>Runtime IDs:</strong> ${escapeHTML((device.correlated_runtime_ids || []).join(', ') || 'n/a')}</span>
        </div>
        <div class="device-banner">${escapeHTML(device.banner_protocol || 'no banner')} ${escapeHTML(device.banner || '')}</div>
        <div class="history-block">
          <div><strong>Subnet history</strong></div>
          <div class="history-chip-row">${historyMarkup(device.cidr_history)}</div>
        </div>
        <div class="history-block">
          <div><strong>Interface history</strong></div>
          <div class="history-chip-row">${historyMarkup(device.interface_history)}</div>
        </div>
        <div class="history-block">
          <div><strong>Replay history</strong></div>
          <div class="history-chip-row">${replayHistoryMarkup(device)}</div>
        </div>
        <div class="history-block">
          <div><strong>Recent parse failures</strong></div>
          <div class="device-sublist">${recentErrorsMarkup(device)}</div>
        </div>
        <div class="actions compact">
          <button data-device-select="${escapeHTML(device.device_id)}">Inspect</button>
          <button data-device-captures="${escapeHTML(device.device_id)}">Load Captures</button>
          ${latestCapture ? `<button data-replay-capture="${escapeHTML(latestCapture.id)}" data-profile-id="${escapeHTML(latestCapture.profile_id || '')}">Replay Latest</button>` : '<button disabled>No Capture Yet</button>'}
        </div>
        <div class="capture-links">
          ${captures.length
            ? captures.map((capture) => `<button class="link-button" data-replay-capture="${escapeHTML(capture.id)}" data-profile-id="${escapeHTML(capture.profile_id || '')}">${escapeHTML(capture.id)} · ${escapeHTML(capture.received_at)}</button>`).join('')
            : '<span class="muted">No recent captures loaded for this device.</span>'}
        </div>
      </article>
    `;
  }).join('');
  bindNetworkDeviceActions();
  renderSelectedDevice();
}

async function loadCapturesForDevice(deviceID, announce) {
  if (!deviceID) return;
  try {
    const device = state.networkDevices.find((item) => item.device_id === deviceID);
    const correlated = Array.isArray(device?.correlated_runtime_ids) ? device.correlated_runtime_ids.filter(Boolean) : [];
    let path = `/captures?device_id=${encodeURIComponent(deviceID)}&limit=5`;
    if (correlated.length) {
      path = `/captures?device_ids=${encodeURIComponent(correlated.join(','))}&limit=5`;
    }
    const captures = await call(path);
    state.capturesByDevice[deviceID] = Array.isArray(captures) ? captures : [];
    if (announce) {
      output.textContent = `Loaded ${state.capturesByDevice[deviceID].length} captures for ${deviceID}${correlated.length ? ` via ${correlated.length} correlated runtime IDs` : ''}.`;
    }
    renderNetworkDevices();
  } catch (err) {
    output.textContent = err.message;
  }
}

async function replayCapture(captureID, profileID) {
  try {
    const result = await call('/replay', { method: 'POST', body: JSON.stringify({ capture_id: captureID, profile_id: profileID }) });
    networkReplayOut.textContent = JSON.stringify(result, null, 2);
    output.textContent = `Replayed capture ${captureID}.`;
    await loadNetworkDevices();
    setPage('networkDevicesPage');
  } catch (err) {
    output.textContent = err.message;
  }
}

async function saveNetworkLink(override) {
  const device = selectedDevice();
  if (!device) {
    output.textContent = 'Select a network device first.';
    return;
  }
  const profileID = document.getElementById('linkProfileId').value.trim();
  const runtimeDeviceID = document.getElementById('linkRuntimeDeviceId').value.trim();
  if (!profileID || !runtimeDeviceID) {
    output.textContent = 'Profile ID and runtime device ID are required.';
    return;
  }
  try {
    await call('/network-links', {
      method: 'POST',
      body: JSON.stringify({
        network_device_id: device.device_id,
        profile_id: profileID,
        runtime_device_id: runtimeDeviceID,
        override,
        confidence: override ? 0.98 : 0.95,
      }),
    });
    output.textContent = `${override ? 'Overrode' : 'Saved'} runtime link for ${device.device_id}.`;
    await loadNetworkDevices();
    await loadNetworkLinkAudit();
  } catch (err) {
    output.textContent = err.message;
  }
}

async function deleteNetworkLink(networkDeviceID, profileID, runtimeDeviceID) {
  try {
    const actor = encodeURIComponent((operatorNameInput.value || '').trim());
    await call(`/network-links?network_device_id=${encodeURIComponent(networkDeviceID)}&profile_id=${encodeURIComponent(profileID)}&runtime_device_id=${encodeURIComponent(runtimeDeviceID)}&actor=${actor}`, { method: 'DELETE' });
    output.textContent = `Removed runtime link ${runtimeDeviceID}.`;
    await loadNetworkDevices();
    await loadNetworkLinkAudit();
  } catch (err) {
    output.textContent = err.message;
  }
}

async function loadProfilesData() {
  try {
    const response = await call('/profiles');
    const profiles = Array.isArray(response) ? response : (Array.isArray(response.profiles) ? response.profiles : []);
    const catalog = Array.isArray(response?.discovery_hint_catalog) ? response.discovery_hint_catalog : [];
    if (catalog.length) {
      DISCOVERY_HINT_PRESETS.splice(0, DISCOVERY_HINT_PRESETS.length, ...catalog);
    }
    state.profiles = profiles;
    profilesOut.textContent = JSON.stringify({ profiles: state.profiles, discovery_hint_catalog: DISCOVERY_HINT_PRESETS }, null, 2);
    renderProfileEditor();
  } catch (err) {
    output.textContent = err.message;
  }
}

function csvValues(inputID) {
  return document.getElementById(inputID).value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseOptionalInt(inputID) {
  const raw = document.getElementById(inputID).value.trim();
  if (!raw) return undefined;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function buildProfileFromEditor(existingProfile = {}) {
  const id = document.getElementById('profileEditorId').value.trim();
  const name = document.getElementById('profileEditorName').value.trim();
  const vendor = document.getElementById('profileEditorVendor').value.trim();
  const model = document.getElementById('profileEditorModel').value.trim();
  const protocolHint = document.getElementById('profileEditorProtocolHint').value.trim();
  const transportType = document.getElementById('profileTransportType').value.trim();
  const sessionMode = document.getElementById('profileSessionMode').value.trim();
  const serialPort = document.getElementById('profileSerialPort').value.trim();
  const parity = document.getElementById('profileParity').value.trim();
  const listenAddress = document.getElementById('profileListenAddress').value.trim();
  const remoteAddress = document.getElementById('profileRemoteAddress').value.trim();
  const parsingStrategy = document.getElementById('profileParsingStrategy').value.trim();
  const deviceMetadata = { ...(existingProfile.device_metadata || {}) };
  if (vendor) {
    deviceMetadata.vendor = vendor;
  } else {
    delete deviceMetadata.vendor;
  }
  if (model) {
    deviceMetadata.model = model;
  } else {
    delete deviceMetadata.model;
  }
  return {
    ...existingProfile,
    id,
    name,
    protocol_hint: protocolHint,
    device_metadata: deviceMetadata,
    transport: {
      ...(existingProfile.transport || {}),
      type: transportType,
      session_mode: sessionMode,
      serial_port: serialPort,
      baud_rate: parseOptionalInt('profileBaudRate'),
      data_bits: parseOptionalInt('profileDataBits'),
      parity,
      stop_bits: parseOptionalInt('profileStopBits'),
      listen_address: listenAddress,
      remote_address: remoteAddress,
      watch_directories: csvValues('profileWatchDirectories'),
      discovery_hints: parseDiscoveryHints(),
    },
    parsing: {
      ...(existingProfile.parsing || {}),
      strategy: parsingStrategy,
    },
    mapping: {
      ...(existingProfile.mapping || {}),
    },
    learning_mode: {
      enabled: existingProfile.learning_mode?.enabled ?? true,
    },
  };
}

function renderProfileCaptureSummary() {
  const select = document.getElementById('profileEditorSelect');
  const selectedProfileID = select.value || document.getElementById('profileEditorId').value.trim();
  const parts = [];
  if (selectedProfileID) {
    parts.push(`Selected profile: ${selectedProfileID}`);
  } else {
    parts.push('No profile selected.');
  }
  if (state.activeProfileSessionId) {
    parts.push(`Active session: ${state.activeProfileSessionId}`);
  } else {
    parts.push('No active session started from this browser.');
  }
  document.getElementById('profileCaptureSummary').textContent = parts.join(' | ');
}

async function saveProfile() {
  const selectedID = document.getElementById('profileEditorSelect').value;
  const existingProfile = state.profiles.find((item) => item.id === selectedID) || {};
  const updated = buildProfileFromEditor(existingProfile);
  if (!updated.id) {
    output.textContent = 'Profile ID is required.';
    return;
  }
  if (!updated.name) {
    output.textContent = 'Profile name is required.';
    return;
  }
  const unknown = parseDiscoveryHints().filter((hint) => !supportedDiscoveryHintMap()[hint]);
  if (unknown.length) {
    output.textContent = `Unsupported discovery hints: ${unknown.join(', ')}.`;
    renderDiscoveryHintValidation();
    return;
  }
  try {
    await call('/profiles', { method: 'POST', body: JSON.stringify(updated) });
    output.textContent = `Saved profile ${updated.id}.`;
    await loadProfilesData();
    document.getElementById('profileEditorSelect').value = updated.id;
    renderProfileEditor();
  } catch (err) {
    output.textContent = err.message;
  }
}

async function startProfileCapture() {
  const profileID = document.getElementById('profileEditorId').value.trim() || document.getElementById('profileEditorSelect').value;
  if (!profileID) {
    output.textContent = 'Select or save a profile first.';
    return;
  }
  try {
    const result = await call('/capture/start', { method: 'POST', body: JSON.stringify({ profile_id: profileID }) });
    state.activeProfileSessionId = result.session_id || '';
    renderProfileCaptureSummary();
    output.textContent = `Started capture for ${profileID} with session ${state.activeProfileSessionId}.`;
    document.getElementById('historySessionId').value = state.activeProfileSessionId;
    document.getElementById('historyProfileId').value = profileID;
  } catch (err) {
    output.textContent = err.message;
  }
}

async function stopProfileCapture() {
  if (!state.activeProfileSessionId) {
    output.textContent = 'No active profile-editor session to stop.';
    return;
  }
  try {
    await call('/capture/stop', { method: 'POST', body: JSON.stringify({ session_id: state.activeProfileSessionId }) });
    output.textContent = `Stopped capture session ${state.activeProfileSessionId}.`;
    state.activeProfileSessionId = '';
    renderProfileCaptureSummary();
  } catch (err) {
    output.textContent = err.message;
  }
}

async function exportNetworkLinks() {
  try {
    const payload = await call('/network-links/export');
    document.getElementById('networkLinksImport').value = JSON.stringify(payload, null, 2);
    renderSupportBundleDiagnostics(payload.diagnostics || null);
    renderNetworkLinkImportPreview({ links: payload.links || [], safe_links: payload.links || [], conflicts: [], diagnostics: payload.diagnostics || null });
    output.textContent = `Exported ${(payload.links || []).length} runtime links.`;
  } catch (err) {
    output.textContent = err.message;
  }
}

async function previewImportNetworkLinks() {
  const raw = document.getElementById('networkLinksImport').value.trim();
  if (!raw) {
    output.textContent = 'Paste exported runtime link JSON first.';
    return;
  }
  try {
    const parsed = JSON.parse(raw);
    const preview = await call('/network-links/preview-import', {
      method: 'POST',
      body: JSON.stringify({ links: Array.isArray(parsed.links) ? parsed.links : [] }),
    });
    renderNetworkLinkImportPreview(preview);
    output.textContent = `Previewed ${(preview.links || []).length} runtime links with ${(preview.conflicts || []).length} conflicts.`;
  } catch (err) {
    output.textContent = err.message;
  }
}

async function importNetworkLinks() {
  const raw = document.getElementById('networkLinksImport').value.trim();
  if (!raw) {
    output.textContent = 'Paste exported runtime link JSON first.';
    return;
  }
  try {
    const parsed = JSON.parse(raw);
    const links = Array.isArray(parsed.links) ? parsed.links : [];
    const preview = await call('/network-links/preview-import', {
      method: 'POST',
      body: JSON.stringify({ links }),
    });
    renderNetworkLinkImportPreview(preview);
    const body = {
      replace: Boolean(parsed.replace),
      links,
      merges: collectMergeDecisions(),
      actor: (operatorNameInput.value || '').trim(),
    };
    if ((preview.conflicts || []).length && body.merges.length === 0 && !body.replace) {
      output.textContent = 'Preview import first and choose how to resolve each conflict.';
      renderNetworkLinkImportPreview(preview);
      return;
    }
    await call('/network-links/import', { method: 'POST', body: JSON.stringify(body) });
    output.textContent = `Imported ${body.links.length} runtime links with ${body.merges.length} merge decisions.`;
    await loadNetworkDevices();
    await refreshSupportBundleSummary();
    await loadNetworkLinkAudit();
  } catch (err) {
    output.textContent = err.message;
  }
}

async function refreshSupportBundleSummary() {
  try {
    const payload = await call('/network-links/export');
    renderSupportBundleDiagnostics(payload.diagnostics || null);
  } catch (err) {
    output.textContent = err.message;
  }
}

async function downloadSupportBundle() {
  try {
    const res = await fetch('/api/v1/support-bundle', { headers: apiHeaders() });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || 'support bundle download failed');
    }
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = href;
    link.download = 'instrument-support.zip';
    link.click();
    URL.revokeObjectURL(href);
    output.textContent = 'Downloaded support bundle.';
  } catch (err) {
    output.textContent = err.message;
  }
}

async function exportMigrationBundle() {
  try {
    const params = buildRedactionParams('migration');
    const suffix = params.toString();
    const bundle = await call(`/migration-bundle/export${suffix ? `?${suffix}` : ''}`);
    document.getElementById('migrationBundlePayload').value = JSON.stringify(bundle, null, 2);
    migrationBundleSummaryOut.textContent = `Exported bundle with ${(bundle.profiles || []).length} profiles and ${(bundle.network_links || []).length} runtime links. Checksum: ${bundle.integrity?.payload_sha256 || 'missing'}.`;
    migrationBundleDetailsOut.textContent = JSON.stringify(bundle.integrity || {}, null, 2);
    renderMigrationDiffCards(null);
  } catch (err) {
    output.textContent = err.message;
  }
}

async function previewMigrationBundle() {
  const raw = document.getElementById('migrationBundlePayload').value.trim();
  if (!raw) {
    output.textContent = 'Paste a migration bundle first.';
    return;
  }
  try {
    const bundle = JSON.parse(raw);
    const preview = await call('/migration-bundle/preview', {
      method: 'POST',
      body: JSON.stringify({ bundle }),
    });
    renderNetworkLinkImportPreview(preview.link_preview || {});
    renderMigrationDiffCards(preview);
    migrationBundleSummaryOut.textContent = `Bundle preview: ${(bundle.profiles || []).length} profiles, ${(bundle.network_links || []).length} links, ${(preview.link_preview?.conflicts || []).length} link conflicts, integrity ${preview.integrity_valid ? 'valid' : 'invalid'}.`;
    migrationBundleDetailsOut.textContent = formatMigrationPreview(preview);
  } catch (err) {
    output.textContent = err.message;
  }
}

async function importMigrationBundle() {
  const raw = document.getElementById('migrationBundlePayload').value.trim();
  if (!raw) {
    output.textContent = 'Paste a migration bundle first.';
    return;
  }
  try {
    const bundle = JSON.parse(raw);
    await call('/migration-bundle/import', {
      method: 'POST',
      body: JSON.stringify({
        actor: (operatorNameInput.value || '').trim(),
        merges: collectMergeDecisions(),
        bundle,
      }),
    });
    output.textContent = `Imported migration bundle with ${(bundle.profiles || []).length} profiles and ${(bundle.network_links || []).length} links.`;
    await loadProfilesData();
    await loadNetworkDevices();
    await refreshSupportBundleSummary();
    await loadBundleSecretStatus();
    await loadNetworkLinkAudit();
  } catch (err) {
    output.textContent = err.message;
  }
}

function formatAudit(entries) {
  if (!Array.isArray(entries) || !entries.length) return 'No audit events found.';
  return entries.map((entry) => {
    const detail = entry.detail && Object.keys(entry.detail).length ? ` ${JSON.stringify(entry.detail)}` : '';
    return `${entry.created_at} | ${entry.actor || 'unknown'} | ${entry.action} | ${entry.network_device_id || 'n/a'} | ${entry.profile_id || 'n/a'} | ${entry.runtime_device_id || 'n/a'} | source=${entry.source || 'n/a'} | conf=${(entry.confidence || 0).toFixed(2)}${detail}`;
  }).join('\n');
}

function isBundleAuditEvent(entry) {
  return typeof entry?.action === 'string' && entry.action.startsWith('migration_bundle_');
}

function summarizeBundleAudit(entries) {
  const bundleEvents = (Array.isArray(entries) ? entries : []).filter(isBundleAuditEvent);
  if (!bundleEvents.length) {
    bundleAuditSummaryOut.textContent = 'No bundle transfer events loaded yet.';
    bundleAuditCardsOut.innerHTML = '<div class="empty-state">Refresh audit to see bundle export/import activity.</div>';
    return;
  }
  const exports = bundleEvents.filter((entry) => entry.action === 'migration_bundle_export');
  const imports = bundleEvents.filter((entry) => entry.action === 'migration_bundle_import');
  const redacted = bundleEvents.filter((entry) => Boolean(entry.detail?.redacted)).length;
  bundleAuditSummaryOut.textContent = `Bundle events: ${bundleEvents.length}. Exports: ${exports.length}. Imports: ${imports.length}. Redacted: ${redacted}.`;
  bundleAuditCardsOut.innerHTML = bundleEvents.map((entry) => {
    const detail = entry.detail || {};
    const redactionMode = detail.redaction?.preset || (detail.redacted ? 'custom' : 'none');
    const mergeCount = detail.merge_count ?? 0;
    return `
      <article class="audit-bundle-card">
        <h3>${escapeHTML(entry.action)}</h3>
        <div class="muted">${escapeHTML(entry.created_at || '')}</div>
        <div class="audit-bundle-meta">
          <div><strong>Actor</strong><div>${escapeHTML(entry.actor || 'unknown')}</div></div>
          <div><strong>Redaction</strong><div>${escapeHTML(redactionMode)}</div></div>
          <div><strong>Profiles</strong><div>${escapeHTML(String(detail.profile_count ?? 0))}</div></div>
          <div><strong>Links</strong><div>${escapeHTML(String(detail.link_count ?? 0))}</div></div>
          <div><strong>Merges</strong><div>${escapeHTML(String(mergeCount))}</div></div>
        </div>
        <div class="audit-bundle-detail">${escapeHTML(JSON.stringify(detail, null, 2))}</div>
      </article>
    `;
  }).join('');
}

async function loadNetworkLinkAudit() {
  try {
    const params = new URLSearchParams({ limit: '50' });
    const actor = document.getElementById('auditActorFilter').value.trim();
    const profileID = document.getElementById('auditProfileFilter').value.trim();
    const deviceID = document.getElementById('auditDeviceFilter').value.trim();
    const action = document.getElementById('auditActionFilter').value.trim();
    if (actor) params.set('actor', actor);
    if (profileID) params.set('profile_id', profileID);
    if (deviceID) params.set('network_device_id', deviceID);
    if (action) params.set('action', action);
    const entries = await call(`/network-links/audit?${params.toString()}`);
    networkLinkAuditOut.textContent = formatAudit(entries);
    summarizeBundleAudit(entries);
  } catch (err) {
    output.textContent = err.message;
  }
}

async function exportNetworkLinkAudit() {
  try {
    const params = new URLSearchParams({ limit: '500' });
    const actor = document.getElementById('auditActorFilter').value.trim();
    const profileID = document.getElementById('auditProfileFilter').value.trim();
    const deviceID = document.getElementById('auditDeviceFilter').value.trim();
    const action = document.getElementById('auditActionFilter').value.trim();
    if (actor) params.set('actor', actor);
    if (profileID) params.set('profile_id', profileID);
    if (deviceID) params.set('network_device_id', deviceID);
    if (action) params.set('action', action);
    buildRedactionParams('audit').forEach((value, key) => params.set(key, value));
    const res = await fetch(`/api/v1/network-links/audit/export?${params.toString()}`, { headers: apiHeaders() });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || 'audit export failed');
    }
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = href;
    link.download = 'network-link-audit.json';
    link.click();
    URL.revokeObjectURL(href);
    output.textContent = 'Downloaded filtered audit export.';
  } catch (err) {
    output.textContent = err.message;
  }
}

async function loadBundleSecretStatus() {
  try {
    const status = await call('/runtime/secret-status');
    renderBundleSecretStatus(status);
  } catch (err) {
    bundleSecretStatusOut.textContent = err.message;
  }
}

async function loadNetworkDevices() {
  try {
    const snapshot = await call('/runtime/status?limit=200');
    state.runtimeSnapshot = snapshot;
    state.networkDevices = Array.isArray(snapshot.network_devices) ? snapshot.network_devices : [];
    if (!state.selectedNetworkDeviceID && state.networkDevices.length) {
      state.selectedNetworkDeviceID = state.networkDevices[0].device_id;
    }
    renderNetworkDevices();
  } catch (err) {
    output.textContent = err.message;
  }
}

function setPage(pageID) {
  state.activePage = pageID;
  document.querySelectorAll('[data-page]').forEach((section) => {
    section.classList.toggle('active', section.id === pageID);
  });
  document.querySelectorAll('[data-page-button]').forEach((button) => {
    button.classList.toggle('active', button.dataset.pageButton === pageID);
  });
}

async function run(target, fn, formatter = null, after = null) {
  try {
    const result = await fn();
    target.textContent = formatter ? formatter(result) : JSON.stringify(result, null, 2);
    if (after) after(result);
  } catch (err) {
    output.textContent = err.message;
  }
}

async function refreshMaintenanceStatus() {
  try {
    const [status, errors, captures] = await Promise.all([
      call('/runtime/status?limit=50'),
      call('/runtime/errors?limit=10'),
      call('/captures?limit=10'),
    ]);
    state.runtimeSnapshot = status;
    state.networkDevices = Array.isArray(status.network_devices) ? status.network_devices : [];
    if (!state.selectedNetworkDeviceID && state.networkDevices.length) {
      state.selectedNetworkDeviceID = state.networkDevices[0].device_id;
    }
    const maintenance = status.maintenance || {};
    renderMaintenance(maintenance, status);
    renderNetworkDevices();
    if (!runtimeErrorsOut.textContent.trim()) {
      runtimeErrorsOut.textContent = JSON.stringify(errors, null, 2);
    }
    if (!capturesOut.textContent.trim()) {
      capturesOut.textContent = JSON.stringify(captures, null, 2);
    }
  } catch (err) {
    output.textContent = err.message;
  }
}

document.querySelectorAll('[data-page-button]').forEach((button) => {
  button.onclick = () => setPage(button.dataset.pageButton);
});

document.getElementById('networkSearch').oninput = renderNetworkDevices;
document.getElementById('networkStatusFilter').onchange = renderNetworkDevices;
document.getElementById('networkProtocolFilter').onchange = renderNetworkDevices;
document.getElementById('refreshNetworkDevices').onclick = loadNetworkDevices;
document.getElementById('refreshNetworkCaptures').onclick = async () => {
  if (!state.selectedNetworkDeviceID) {
    output.textContent = 'Select a network device first.';
    return;
  }
  await loadCapturesForDevice(state.selectedNetworkDeviceID, true);
};
document.getElementById('saveNetworkLink').onclick = async () => saveNetworkLink(false);
document.getElementById('overrideNetworkLink').onclick = async () => saveNetworkLink(true);
document.getElementById('exportNetworkLinks').onclick = exportNetworkLinks;
document.getElementById('previewImportNetworkLinks').onclick = previewImportNetworkLinks;
document.getElementById('importNetworkLinks').onclick = importNetworkLinks;
document.getElementById('saveProfile').onclick = saveProfile;
document.getElementById('startProfileCapture').onclick = startProfileCapture;
document.getElementById('stopProfileCapture').onclick = stopProfileCapture;
document.getElementById('profileEditorSelect').onchange = renderProfileEditor;
document.getElementById('profileDiscoveryHints').oninput = () => {
  renderDiscoveryHintPresets();
  renderDiscoveryHintValidation();
  renderDiscoveryHintHelp();
};
document.getElementById('networkLinksImport').oninput = () => {
  state.networkLinkImportPreview = null;
  networkLinkImportSummary.textContent = 'Import payload changed. Preview again to review conflicts and merge choices.';
  networkLinkMergeList.innerHTML = '<span class="muted">No import conflicts loaded.</span>';
};
document.getElementById('refreshSupportBundleSummary').onclick = refreshSupportBundleSummary;
document.getElementById('downloadSupportBundle').onclick = downloadSupportBundle;
document.getElementById('exportMigrationBundle').onclick = exportMigrationBundle;
document.getElementById('previewMigrationBundle').onclick = previewMigrationBundle;
document.getElementById('importMigrationBundle').onclick = importMigrationBundle;
document.getElementById('refreshLinkAudit').onclick = loadNetworkLinkAudit;
document.getElementById('exportLinkAudit').onclick = exportNetworkLinkAudit;
document.getElementById('migrationRedactionPreset').onchange = () => applyPresetToggles('migration');
document.getElementById('auditRedactionPreset').onchange = () => applyPresetToggles('audit');

document.getElementById('scanPorts').onclick = async () => run(portsOut, () => call(scanQuery()), formatPorts, (result) => {
  state.networkDevices = Array.isArray(result.network_devices) ? result.network_devices : state.networkDevices;
  renderNetworkDevices();
});
document.getElementById('loadProfiles').onclick = loadProfilesData;
document.getElementById('loadCaptures').onclick = async () => run(capturesOut, () => call('/captures?limit=25'));
document.getElementById('loadRuntimeStatus').onclick = async () => run(runtimeStatusOut, () => call('/runtime/status?limit=25'), null, (snapshot) => {
  state.runtimeSnapshot = snapshot;
  state.networkDevices = Array.isArray(snapshot.network_devices) ? snapshot.network_devices : [];
  renderNetworkDevices();
});
document.getElementById('loadRuntimeErrors').onclick = async () => run(runtimeErrorsOut, () => call('/runtime/errors?limit=25'));
document.getElementById('loadSessionHistory').onclick = async () => run(sessionHistoryOut, () => call(historyQuery()), formatHistory);
document.getElementById('classifyBtn').onclick = async () => run(output, () => call('/classify', { method: 'POST', body: JSON.stringify(payload()) }));
document.getElementById('parseBtn').onclick = async () => run(output, () => call('/results/ingest', { method: 'POST', body: JSON.stringify(payload()) }));
document.getElementById('learnBtn').onclick = async () => run(output, () => call('/learning/suggest', { method: 'POST', body: JSON.stringify({ raw_text: payload().payload_text, profile_id: payload().profile_id }) }));
document.getElementById('runCleanup').onclick = async () => run(cleanupOut, () => call('/runtime/cleanup', { method: 'POST', body: '{}' }), formatCleanup, async () => { await refreshMaintenanceStatus(); });
document.getElementById('refreshMaintenance').onclick = refreshMaintenanceStatus;

setPage('overviewPage');
refreshMaintenanceStatus();
loadProfilesData();
refreshSupportBundleSummary();
loadBundleSecretStatus();
loadNetworkLinkAudit();
