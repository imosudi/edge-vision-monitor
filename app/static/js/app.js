/**
 * Edge Vision Monitor - Live Dashboard Client & WebSocket Coordination
 */

let ws = null;
let reconnectTimer = null;
let currentSourceType = 'file';
let isInferenceRunning = true;
let isSwitchingBackend = false;
let activeWorkloadMode = 'hailo'; // 'hailo' | 'cpu' | 'benchmark' | 'workload_suite'
let isWorkloadSuiteActive = false;
let isBenchmarkRunning = false;
let currentActiveBackend = 'hailo';
let selectedWorkloadType = 'A';

function getActiveRunningWorkload() {
  if (isWorkloadSuiteActive) return 'workload_suite';
  if (typeof isBenchmarkRunning !== 'undefined' && isBenchmarkRunning) return 'benchmark';
  if (isInferenceRunning) {
    return currentActiveBackend === 'cpu' ? 'cpu' : 'hailo';
  }
  return null;
}
window.getActiveRunningWorkload = getActiveRunningWorkload;

function syncWorkloadModeSelectorUI(runningWorkload) {
  const effectiveMode = activeWorkloadMode;

  const btnHailo = document.getElementById('btn-backend-hailo');
  const btnCpu = document.getElementById('btn-backend-cpu');
  const btnBench = document.getElementById('btn-mode-benchmark');
  const btnSuite = document.getElementById('btn-mode-workload-suite');

  if (btnHailo) btnHailo.classList.toggle('active', effectiveMode === 'hailo');
  if (btnCpu) btnCpu.classList.toggle('active', effectiveMode === 'cpu');
  if (btnBench) btnBench.classList.toggle('active', effectiveMode === 'benchmark');
  if (btnSuite) btnSuite.classList.toggle('active', effectiveMode === 'workload_suite');
}

function syncContextualWorkloadButtons(runningWorkload) {
  // 1. Workload Suite section in-card controls
  const btnSuiteStart = document.getElementById('btn-workload-start');
  const btnSuiteAbort = document.getElementById('btn-workload-abort');
  if (btnSuiteStart) {
    if (runningWorkload === 'workload_suite') {
      btnSuiteStart.className = 'btn btn-danger pulsing-stop';
      btnSuiteStart.innerHTML = '<span>⏹</span> Stop Workload';
      btnSuiteStart.disabled = false;
    } else if (runningWorkload !== null) {
      btnSuiteStart.className = 'btn btn-primary';
      btnSuiteStart.innerHTML = '<span>▶</span> Start Workload';
      btnSuiteStart.disabled = true;
    } else {
      btnSuiteStart.className = 'btn btn-primary';
      btnSuiteStart.innerHTML = '<span>▶</span> Start Workload';
      btnSuiteStart.disabled = false;
    }
  }
  if (btnSuiteAbort) {
    btnSuiteAbort.disabled = (runningWorkload !== 'workload_suite');
  }

  // 2. Dual Benchmark button inside benchmark toolbar
  const btnAutoBench = document.getElementById('btn-run-auto-benchmark');
  if (btnAutoBench) {
    if (runningWorkload === 'benchmark') {
      btnAutoBench.className = 'btn btn-danger pulsing-stop';
      btnAutoBench.innerHTML = '<span>⏹</span> Stop Benchmark';
      btnAutoBench.disabled = false;
    } else if (runningWorkload !== null) {
      btnAutoBench.className = 'btn btn-benchmark';
      btnAutoBench.innerHTML = '<span>▶</span> Run Automated Dual-Phase Benchmark';
      btnAutoBench.disabled = true;
    } else {
      btnAutoBench.className = 'btn btn-benchmark';
      btnAutoBench.innerHTML = '<span>▶</span> Run Automated Dual-Phase Benchmark';
      btnAutoBench.disabled = false;
    }
  }
}

function updateMasterWorkloadButton() {
  const btnInf = document.getElementById('btn-inference-toggle');
  const txtInf = document.getElementById('text-inference');
  const icoInf = document.getElementById('icon-inference');
  if (!btnInf || !txtInf || !icoInf) return;

  // Determine if the currently selected workload is running
  let isSelectedRunning = false;
  if (activeWorkloadMode === 'workload_suite') {
    isSelectedRunning = isWorkloadSuiteActive;
  } else if (activeWorkloadMode === 'benchmark') {
    isSelectedRunning = isBenchmarkRunning;
  } else if (activeWorkloadMode === 'cpu') {
    isSelectedRunning = isInferenceRunning && currentActiveBackend === 'cpu' && !isWorkloadSuiteActive && !isBenchmarkRunning;
  } else if (activeWorkloadMode === 'hailo') {
    isSelectedRunning = isInferenceRunning && currentActiveBackend === 'hailo' && !isWorkloadSuiteActive && !isBenchmarkRunning;
  }

  const runningWorkload = getActiveRunningWorkload();

  if (isSelectedRunning) {
    btnInf.className = 'btn btn-danger pulsing-stop';
    icoInf.textContent = '⏹';

    if (activeWorkloadMode === 'workload_suite') {
      const prof = selectedWorkloadType || 'A';
      txtInf.textContent = `Stop Workload (Profile ${prof})`;
      btnInf.title = `Stop Active Hailo-8L Stress Workload (Profile ${prof})`;
    } else if (activeWorkloadMode === 'benchmark') {
      txtInf.textContent = 'Stop Dual Benchmark';
      btnInf.title = 'Stop Running Automated Dual Benchmark';
    } else if (activeWorkloadMode === 'cpu') {
      txtInf.textContent = 'Stop CPU (ONNX)';
      btnInf.title = 'Stop Continuous Host CPU Inference';
    } else {
      txtInf.textContent = 'Stop Hailo-8L';
      btnInf.title = 'Stop Continuous Hailo-8L NPU Inference';
    }
  } else {
    btnInf.classList.remove('pulsing-stop', 'btn-danger');
    icoInf.textContent = '▶';

    if (activeWorkloadMode === 'workload_suite') {
      btnInf.className = 'btn btn-primary';
      const prof = selectedWorkloadType || 'A';
      txtInf.textContent = `Start Workload (Profile ${prof})`;
      btnInf.title = `Start Hailo-8L Stress Workload (Profile ${prof})`;
    } else if (activeWorkloadMode === 'benchmark') {
      btnInf.className = 'btn btn-primary';
      txtInf.textContent = 'Start Dual Benchmark';
      btnInf.title = 'Start Automated Dual Benchmark (Hailo-8L vs Host CPU)';
    } else if (activeWorkloadMode === 'cpu') {
      btnInf.className = 'btn btn-primary';
      txtInf.textContent = 'Start CPU (ONNX)';
      btnInf.title = 'Start Continuous CPU (ONNX) Inference';
    } else {
      btnInf.className = 'btn btn-primary';
      txtInf.textContent = 'Start Hailo-8L';
      btnInf.title = 'Start Continuous Hailo-8L NPU Inference';
    }
  }

  syncWorkloadModeSelectorUI(runningWorkload);
  syncContextualWorkloadButtons(runningWorkload);
}
window.updateMasterWorkloadButton = updateMasterWorkloadButton;

async function selectWorkloadMode(mode) {
  console.log(`[WORKLOAD] Workload mode selected: ${mode}`);
  activeWorkloadMode = mode;

  if (mode === 'hailo') {
    if (currentActiveBackend !== 'hailo' && typeof switchBackend === 'function') {
      await switchBackend('hailo');
    }
  } else if (mode === 'cpu') {
    if (currentActiveBackend !== 'cpu' && typeof switchBackend === 'function') {
      await switchBackend('cpu');
    }
  } else if (mode === 'benchmark') {
    const benchPanel = document.getElementById('benchmark-waveforms-panel');
    if (benchPanel) {
      benchPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  } else if (mode === 'workload_suite') {
    if (typeof scrollToWorkloadSuite === 'function') {
      scrollToWorkloadSuite();
    }
  }

  updateMasterWorkloadButton();
}
window.selectWorkloadMode = selectWorkloadMode;

async function toggleGlobalWorkload() {
  // Determine if the currently selected workload is running
  let isSelectedRunning = false;
  if (activeWorkloadMode === 'workload_suite') {
    isSelectedRunning = isWorkloadSuiteActive;
  } else if (activeWorkloadMode === 'benchmark') {
    isSelectedRunning = isBenchmarkRunning;
  } else if (activeWorkloadMode === 'cpu') {
    isSelectedRunning = isInferenceRunning && currentActiveBackend === 'cpu' && !isWorkloadSuiteActive && !isBenchmarkRunning;
  } else if (activeWorkloadMode === 'hailo') {
    isSelectedRunning = isInferenceRunning && currentActiveBackend === 'hailo' && !isWorkloadSuiteActive && !isBenchmarkRunning;
  }

  if (isSelectedRunning) {
    console.log(`[WORKLOAD] Halting running workload via master button: ${activeWorkloadMode}`);
    if (activeWorkloadMode === 'workload_suite') {
      await emergencyAbortWorkload();
    } else if (activeWorkloadMode === 'benchmark') {
      if (typeof stopBenchmarkOperations === 'function') {
        stopBenchmarkOperations('Master Stop requested');
      }
      try {
        await fetch('/api/v1/inference/stop', { method: 'POST' });
      } catch (e) {
        console.warn('Failed to stop inference on benchmark abort:', e);
      }
    } else {
      clearDetectionCountdown();
      if (typeof stopBenchmarkOperations === 'function') {
        stopBenchmarkOperations('Master Stop requested');
      }
      try {
        await fetch('/api/v1/inference/stop', { method: 'POST' });
      } catch (e) {
        console.warn('Failed to stop inference:', e);
      }
      isInferenceRunning = false;
    }
    updateMasterWorkloadButton();
    return;
  }

  // Pre-empt prior active workload if another workload was running
  const priorRunning = getActiveRunningWorkload();
  if (priorRunning !== null) {
    console.log(`[WORKLOAD] Pre-empting prior active workload (${priorRunning}) to start ${activeWorkloadMode}`);
    if (priorRunning === 'workload_suite') {
      await emergencyAbortWorkload();
    } else if (priorRunning === 'benchmark') {
      if (typeof stopBenchmarkOperations === 'function') {
        stopBenchmarkOperations('Switching to another workload');
      }
      try { await fetch('/api/v1/inference/stop', { method: 'POST' }); } catch (e) {}
    } else {
      clearDetectionCountdown();
      try { await fetch('/api/v1/inference/stop', { method: 'POST' }); } catch (e) {}
      isInferenceRunning = false;
    }
    await new Promise(r => setTimeout(r, 200));
  }

  console.log(`[WORKLOAD] Starting workload mode via master button: ${activeWorkloadMode}`);

  if (activeWorkloadMode === 'workload_suite') {
    await startWorkloadFromUI();
  } else if (activeWorkloadMode === 'benchmark') {
    await startAutomatedBenchmark();
  } else if (activeWorkloadMode === 'cpu') {
    if (currentActiveBackend !== 'cpu' && typeof switchBackend === 'function') {
      await switchBackend('cpu');
    }
    setWaveformsPaused(false, 'CPU Inference Started');
    await resetTelemetryAndDetectionData();
    try {
      const res = await fetch('/api/v1/inference/start', { method: 'POST' });
      const data = await res.json();
      console.log('CPU inference start response:', data);
      isInferenceRunning = true;
      if (detectionDurationSec > 0) {
        startDetectionCountdown(detectionDurationSec);
      }
    } catch (e) {
      console.error('Failed to start CPU inference:', e);
    }
  } else {
    if (currentActiveBackend !== 'hailo' && typeof switchBackend === 'function') {
      await switchBackend('hailo');
    }
    setWaveformsPaused(false, 'Hailo-8L Inference Started');
    await resetTelemetryAndDetectionData();
    try {
      const res = await fetch('/api/v1/inference/start', { method: 'POST' });
      const data = await res.json();
      console.log('Hailo inference start response:', data);
      isInferenceRunning = true;
      if (detectionDurationSec > 0) {
        startDetectionCountdown(detectionDurationSec);
      }
    } catch (e) {
      console.error('Failed to start Hailo-8L inference:', e);
    }
  }

  updateMasterWorkloadButton();
}
window.toggleGlobalWorkload = toggleGlobalWorkload;
window.toggleInference = toggleGlobalWorkload;

async function toggleWorkloadSuiteFromUI() {
  if (isWorkloadSuiteActive) {
    await emergencyAbortWorkload();
  } else {
    activeWorkloadMode = 'workload_suite';
    await startWorkloadFromUI();
  }
}
window.toggleWorkloadSuiteFromUI = toggleWorkloadSuiteFromUI;

// Class colour palette matching backend
const CLASS_COLORS = [
  '#2563eb', '#7c3aed', '#16a34a', '#f59e0b', '#ef4444',
  '#ec4899', '#0891b2', '#6366f1', '#f97316', '#84cc16'
];

// Cumulative session cache for detection confidence distribution histogram
let sessionConfBins = new Array(10).fill(0);
let sessionConfTotal = 0;
let sessionConfSum = 0;
let lastChartTickSec = -1;
let hailoLoadMovingWindow = [];

// Waveform streaming pause state (e.g. frozen when detection time elapses)
let isWaveformsPaused = false;
window.isWaveformsPaused = false;

function setWaveformsPaused(paused, reason = '') {
  isWaveformsPaused = !!paused;
  window.isWaveformsPaused = isWaveformsPaused;
  const badge = document.getElementById('badge-waveforms-status');
  if (badge) {
    if (isWaveformsPaused) {
      badge.style.display = 'inline-flex';
      const label = reason ? `⏸️ Waveforms Paused (${reason})` : '⏸️ Waveforms Paused';
      badge.innerHTML = `${label} &bull; <span style="text-decoration: underline; font-size: 0.72rem; cursor: pointer;">Resume</span>`;
    } else {
      badge.style.display = 'none';
    }
  }
  console.log(`[WAVEFORMS] Paused: ${isWaveformsPaused} (${reason})`);
}

function toggleWaveformsPause() {
  setWaveformsPaused(!isWaveformsPaused, isWaveformsPaused ? 'User Resumed' : 'User Paused');
}
window.toggleWaveformsPause = toggleWaveformsPause;
window.setWaveformsPaused = setWaveformsPaused;

function updateConfidenceHistogramUI() {
  if (!confHistChart) {
    setTimeout(updateConfidenceHistogramUI, 100);
    return;
  }
  confHistChart.data.datasets[0].data = [...sessionConfBins];
  confHistChart.update('none');

  if (typeof activeEnlargedChartId !== 'undefined' && activeEnlargedChartId === 'chart-conf-hist' && typeof enlargedChart !== 'undefined' && enlargedChart) {
    enlargedChart.data.datasets[0].data = [...sessionConfBins];
    enlargedChart.update('none');
  }

  const lblConf = document.getElementById('lbl-conf-summary');
  if (lblConf) {
    if (sessionConfTotal > 0) {
      const mean = (sessionConfSum / sessionConfTotal).toFixed(2);
      lblConf.textContent = `N=${sessionConfTotal} · Mean Conf: ${mean}`;
    } else {
      lblConf.textContent = '0 Detections';
    }
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/v1/ws`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('[WS] Connected to live telemetry stream');
    clearTimeout(reconnectTimer);
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleLiveUpdate(data);
    } catch (e) {
      console.error('[WS] Parse error', e);
    }
  };

  ws.onclose = () => {
    console.warn('[WS] Connection closed, retrying in 2s...');
    reconnectTimer = setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.error('[WS] Error', err);
    ws.close();
  };
}

function handleLiveUpdate(data) {
  try {
    const { status, inference, detections, metrics } = data;

  // 1. Update Header & Badges
  const wasRunning = isInferenceRunning;
  isInferenceRunning = status.inference_running;
  if (!isInferenceRunning && wasRunning) {
    clearDetectionCountdown();
  }
  currentActiveBackend = inference.active_backend || status.active_backend || 'hailo';
  updateMasterWorkloadButton();

  document.getElementById('label-source').textContent = `Source: ${status.active_source}`;
  const badgeSource = document.getElementById('badge-source');
  badgeSource.className = 'badge active';

  // Synchronise header Hailo badge in real-time
  const hailoBadge = document.getElementById('badge-hailo');
  const hailoLabel = document.getElementById('label-hailo');
  const activeBackend = inference.active_backend || status.active_backend || 'hailo';
  if (hailoBadge && hailoLabel) {
    const isHailoActive = (activeBackend === 'hailo');
    const hailoMetricPresent = metrics?.['hailo_device_present']?.value === 1.0;
    const hailoEngReady = inference?.engine_status?.hailo_ready || (inference?.engine_status?.ready && inference?.engine_status?.backend === 'hailo');
    if (isHailoActive || hailoMetricPresent || hailoEngReady) {
      hailoBadge.className = 'badge active';
      hailoLabel.textContent = isHailoActive ? 'Hailo-8L: Online' : 'Hailo-8L: Ready';
    } else if (inference?.engine_status?.is_mock) {
      hailoBadge.className = 'badge mock';
      hailoLabel.textContent = 'Hailo-8L: Mock Mode';
    } else {
      hailoBadge.className = 'badge warning';
      hailoLabel.textContent = 'Hailo-8L: Missing';
    }
  }

  // Synchronise backend buttons & labels
  if (!isSwitchingBackend) {
    syncWorkloadModeSelectorUI(getActiveRunningWorkload());
  }

  // Update HUD Accelerator label
  const hudExecLbl = document.getElementById('hud-exec-label');
  if (hudExecLbl) {
    hudExecLbl.textContent = activeBackend === 'cpu' ? 'CPU' : 'Hailo';
  }
  const execTitle = document.getElementById('lbl-backend-exec-title');
  if (execTitle) {
    execTitle.textContent = activeBackend === 'cpu' ? 'CPU' : 'NPU';
  }

  // 2. Video HUD
  const fps = inference.fps || 0;
  document.getElementById('hud-fps').textContent = fps.toFixed(1);
  const npuLat = inference.latencies?.execution_ms?.mean || inference.latencies?.hailo_execution_ms?.mean || 0;
  document.getElementById('hud-hailo-lat').textContent = npuLat.toFixed(1);
  document.getElementById('hud-objects').textContent = detections ? detections.length : 0;
  document.getElementById('badge-det-count').textContent = `${detections ? detections.length : 0} objects`;

  // 3. Latency Breakdown Cards
  const prepLat = inference.latencies?.preprocessing_ms?.mean || 0;
  const postLat = inference.latencies?.postprocessing_ms?.mean || 0;
  const totLat = inference.latencies?.total_ms?.mean || (prepLat + npuLat + postLat);

  document.getElementById('val-total-latency').textContent = `${totLat.toFixed(1)} ms`;
  document.getElementById('lbl-lat-prep').textContent = `${prepLat.toFixed(1)} ms`;
  document.getElementById('lbl-lat-hailo').textContent = `${npuLat.toFixed(1)} ms`;
  document.getElementById('lbl-lat-post').textContent = `${postLat.toFixed(1)} ms`;

  const totalSum = Math.max(0.1, prepLat + npuLat + postLat);
  document.getElementById('bar-lat-prep').style.width = `${(prepLat / totalSum) * 100}%`;
  document.getElementById('bar-lat-hailo').style.width = `${(npuLat / totalSum) * 100}%`;
  document.getElementById('bar-lat-post').style.width = `${(postLat / totalSum) * 100}%`;

  // 4. Telemetry Metrics
  let cpuTemp = null;
  let rp1Temp = null;
  let hailoTemp = null;
  let hailoJunctionTemp = null;
  let hailoTs0 = null;
  let hailoTs1 = null;
  let ambientTemp = null;
  let ambientHumidity = null;
  let ambientComfort = null;
  let ambientColor = null;
  let ambientConnected = false;
  let cpuUtil = null;
  let memUtil = null;
  let isThermalThrottling = false;
  let isFreqCapped = false;
  let isFullBase = false;
  let curFreq = 2400.0;
  let throttleDrop = 0.0;

  if (metrics) {
    // 1. Direct key lookups for Hailo NPU thermals
    if (metrics.hailo_junction_temperature_c && metrics.hailo_junction_temperature_c.value !== null) {
      hailoJunctionTemp = metrics.hailo_junction_temperature_c.value;
    } else if (metrics.hailo_temperature_c && metrics.hailo_temperature_c.value !== null) {
      hailoJunctionTemp = metrics.hailo_temperature_c.value;
    }
    if (metrics.hailo_temp_ts0_c && metrics.hailo_temp_ts0_c.value !== null) {
      hailoTs0 = metrics.hailo_temp_ts0_c.value;
    }
    if (metrics.hailo_temp_ts1_c && metrics.hailo_temp_ts1_c.value !== null) {
      hailoTs1 = metrics.hailo_temp_ts1_c.value;
    }

    // Find CPU Temp and fallbacks
    for (const [k, v] of Object.entries(metrics)) {
      if (k.includes('cpu') && v.unit === 'celsius' && v.value !== null) {
        cpuTemp = v.value;
      }
      if (k.includes('rp1') && v.unit === 'celsius' && v.value !== null) {
        rp1Temp = v.value;
      }
      if (k.includes('junction') && v.value !== null && hailoJunctionTemp === null) {
        hailoJunctionTemp = v.value;
      }
      if (k.includes('ts0') && v.value !== null && hailoTs0 === null) {
        hailoTs0 = v.value;
      }
      if (k.includes('ts1') && v.value !== null && hailoTs1 === null) {
        hailoTs1 = v.value;
      }
    }

    if (hailoJunctionTemp === null && (hailoTs0 !== null || hailoTs1 !== null)) {
      hailoJunctionTemp = Math.max(hailoTs0 ?? 0, hailoTs1 ?? 0);
    }
    hailoTemp = hailoJunctionTemp;

    // Ambient Sensor Telemetry (ESP32-S3 / DHT22)
    if (metrics.ambient_temperature_c && metrics.ambient_temperature_c.value !== null) {
      ambientTemp = metrics.ambient_temperature_c.value;
      if (metrics.ambient_temperature_c.comfort_status) {
        ambientComfort = metrics.ambient_temperature_c.comfort_status;
        ambientColor = metrics.ambient_temperature_c.comfort_color;
      }
    }
    if (metrics.ambient_humidity_percent && metrics.ambient_humidity_percent.value !== null) {
      ambientHumidity = metrics.ambient_humidity_percent.value;
    }
    if (metrics.ambient_metadata) {
      const meta = metrics.ambient_metadata;
      ambientConnected = !!(meta.value > 0 || meta.status === 'AVAILABLE');
      if (meta.comfort_status && !ambientComfort) ambientComfort = meta.comfort_status;
      if (meta.comfort_color && !ambientColor) ambientColor = meta.comfort_color;
      if (meta.chip_type && document.getElementById('val-esp32-chip')) {
        document.getElementById('val-esp32-chip').textContent = meta.chip_type;
      }
      if (meta.serial_port && document.getElementById('val-esp32-port')) {
        document.getElementById('val-esp32-port').textContent = `${meta.serial_port} (${meta.baud_rate || 115200})`;
      }
    } else if (ambientTemp !== null) {
      ambientConnected = true;
    }

    if (metrics.cpu_utilisation && metrics.cpu_utilisation.value !== null) {
      cpuUtil = metrics.cpu_utilisation.value;
    }
    if (metrics.memory_utilisation && metrics.memory_utilisation.value !== null) {
      memUtil = metrics.memory_utilisation.value;
    }
    if (metrics.disk_utilisation && metrics.disk_utilisation.value !== null) {
      document.getElementById('val-disk-util').textContent = `${metrics.disk_utilisation.value}%`;
    }

    // Undervoltage / Thermal Throttling / Frequency Drop
    isThermalThrottling = !!(metrics.cpu_thermal_throttle_active && metrics.cpu_thermal_throttle_active.value > 0);
    isFreqCapped = !!(metrics.rpi_arm_freq_capped_now && metrics.rpi_arm_freq_capped_now.value > 0);
    const isThrottled = !!(metrics.rpi_is_throttled && metrics.rpi_is_throttled.value > 0);
    const isUndervolt = !!(metrics.rpi_undervoltage_now && metrics.rpi_undervoltage_now.value > 0);
    const banner = document.getElementById('alert-banner');
    const bannerText = document.getElementById('alert-banner-text');

    if (isThermalThrottling || isFreqCapped || isThrottled || isUndervolt) {
      banner.style.display = 'flex';
      if (isThermalThrottling) {
        const dropMhz = metrics.cpu_freq_throttle_drop_mhz && metrics.cpu_freq_throttle_drop_mhz.value !== null ? metrics.cpu_freq_throttle_drop_mhz.value : 0;
        const curMhz = metrics.cpu_freq_cur_mhz && metrics.cpu_freq_cur_mhz.value !== null ? metrics.cpu_freq_cur_mhz.value : 0;
        bannerText.textContent = `CRITICAL: Hardware Thermal Throttling Active! CPU clock dropped down to ${Math.round(curMhz)} MHz (-${Math.round(dropMhz)} MHz from 2.4 GHz base).`;
      } else if (isFreqCapped) {
        const curMhz = metrics.cpu_freq_cur_mhz && metrics.cpu_freq_cur_mhz.value !== null ? metrics.cpu_freq_cur_mhz.value : 0;
        bannerText.textContent = `WARNING: ARM frequency capping active on Raspberry Pi 5! Processor running at ${Math.round(curMhz)} MHz.`;
      } else if (isUndervolt) {
        bannerText.textContent = 'WARNING: Hardware undervoltage detected on power supply rail!';
      } else {
        bannerText.textContent = 'WARNING: Hardware throttling flag detected via vcgencmd!';
      }
    } else {
      banner.style.display = 'none';
    }

    // Electrical & Clock Throttling Card elements
    const baseFreq = metrics.cpu_freq_base_mhz && metrics.cpu_freq_base_mhz.value !== null ? metrics.cpu_freq_base_mhz.value : 2400.0;
    const armActualMhz = metrics.cpu_freq_arm_actual_mhz && metrics.cpu_freq_arm_actual_mhz.value !== null ? metrics.cpu_freq_arm_actual_mhz.value : null;
    curFreq = armActualMhz !== null && (isFreqCapped || isThermalThrottling || armActualMhz < 2385.0)
      ? armActualMhz
      : (metrics.cpu_freq_cur_mhz && metrics.cpu_freq_cur_mhz.value !== null ? metrics.cpu_freq_cur_mhz.value : (metrics.cpu_freq_cpu0_mhz?.value || baseFreq));
    isFullBase = (metrics.cpu_is_full_base_freq && metrics.cpu_is_full_base_freq.value > 0) && curFreq >= 2385.0;
    throttleDrop = metrics.cpu_freq_throttle_drop_mhz && metrics.cpu_freq_throttle_drop_mhz.value !== null ? metrics.cpu_freq_throttle_drop_mhz.value : Math.max(0, baseFreq - curFreq);

    const elClock = document.getElementById('val-cpu-clock');
    if (elClock) {
      elClock.textContent = `${Math.round(curFreq)} MHz (${(curFreq / 1000).toFixed(2)} GHz)`;
    }

    const elState = document.getElementById('val-clock-state');
    if (elState) {
      if (isThermalThrottling && throttleDrop > 15) {
        elState.textContent = `THROTTLED: ${Math.round(curFreq)} MHz (-${Math.round(throttleDrop)} MHz)`;
        elState.className = 'metric-val red';
      } else if (isFreqCapped) {
        elState.textContent = `FREQ CAPPED (${Math.round(curFreq)} MHz)`;
        elState.className = 'metric-val amber';
      } else if (isFullBase) {
        elState.textContent = `2.4 GHz Full Base (${Math.round(curFreq)} MHz)`;
        elState.className = 'metric-val green';
      } else {
        elState.textContent = `${Math.round(curFreq)} MHz (Governor)`;
        elState.className = 'metric-val';
      }
    }

    const elDrop = document.getElementById('val-throttle-drop');
    if (elDrop) {
      if ((isThermalThrottling || isFreqCapped) && throttleDrop > 0) {
        elDrop.textContent = `-${Math.round(throttleDrop)} MHz`;
        elDrop.className = 'metric-val red';
      } else {
        elDrop.textContent = '0 MHz (None)';
        elDrop.className = 'metric-val green';
      }
    }

    const elFreqCapped = document.getElementById('val-freq-capped');
    if (elFreqCapped) {
      elFreqCapped.textContent = isFreqCapped ? `YES (${Math.round(curFreq)} MHz)` : 'No';
      elFreqCapped.className = isFreqCapped ? 'metric-val amber' : 'metric-val green';
    }

    document.getElementById('val-undervolt').textContent = isUndervolt ? 'YES (Active)' : 'No';
    document.getElementById('val-undervolt').className = isUndervolt ? 'metric-val red' : 'metric-val green';

    if (metrics.ina219_bus_voltage && metrics.ina219_bus_voltage.value !== null) {
      document.getElementById('val-ina-voltage').textContent = `${metrics.ina219_bus_voltage.value} V`;
    }
  }

  // Update Thermals DOM
  if (cpuTemp !== null) {
    document.getElementById('val-cpu-temp').textContent = `${cpuTemp}°C`;
    const cpuBar = document.getElementById('bar-cpu-temp');
    cpuBar.style.width = `${Math.min(100, (cpuTemp / 90) * 100)}%`;
    if (cpuTemp >= 80) cpuBar.style.background = 'var(--accent-rose)';
    else if (cpuTemp >= 70) cpuBar.style.background = 'var(--accent-amber)';
    else cpuBar.style.background = 'var(--accent-blue)';
  }
  if (rp1Temp !== null) {
    const elRp1 = document.getElementById('val-rp1-temp');
    if (elRp1) elRp1.textContent = `${Number(rp1Temp).toFixed(1)}°C`;
  }

  // Update NPU Junction Temperature (Tj) & Die Sensors in Hardware Thermals Card
  const effectiveJunctionTemp = hailoJunctionTemp !== null ? hailoJunctionTemp : hailoTemp;
  const elHailoTj = document.getElementById('val-hailo-tj-temp');
  const barHailoTj = document.getElementById('bar-hailo-tj-temp');
  if (effectiveJunctionTemp !== null) {
    const tjValStr = `${Number(effectiveJunctionTemp).toFixed(1)}°C`;
    if (elHailoTj) {
      elHailoTj.textContent = tjValStr;
      if (effectiveJunctionTemp >= 100.0) {
        elHailoTj.className = 'metric-val red';
      } else if (effectiveJunctionTemp >= 85.0) {
        elHailoTj.className = 'metric-val amber';
      } else {
        elHailoTj.className = 'metric-val green';
      }
    }
    if (barHailoTj) {
      const tjPct = Math.max(0, Math.min(100, (effectiveJunctionTemp / 105.0) * 100.0));
      barHailoTj.style.width = `${tjPct}%`;
      if (effectiveJunctionTemp >= 100.0) {
        barHailoTj.style.background = 'var(--accent-rose, #ef4444)';
      } else if (effectiveJunctionTemp >= 85.0) {
        barHailoTj.style.background = 'var(--accent-amber, #f59e0b)';
      } else {
        barHailoTj.style.background = 'var(--accent-emerald, #10b981)';
      }
    }
  } else {
    if (elHailoTj) elHailoTj.textContent = 'N/A';
    if (barHailoTj) barHailoTj.style.width = '0%';
  }

  // Legacy fallback alias for val-hailo-temp
  const elHailoLegacy = document.getElementById('val-hailo-temp');
  if (elHailoLegacy) {
    elHailoLegacy.textContent = effectiveJunctionTemp !== null ? `${Number(effectiveJunctionTemp).toFixed(1)}°C` : 'N/A';
  }

  // Update NPU Die Sensors (TS0 / TS1)
  const elHailoDie = document.getElementById('val-hailo-die-temp');
  if (elHailoDie) {
    if (hailoTs0 !== null && hailoTs1 !== null) {
      elHailoDie.textContent = `${Number(hailoTs0).toFixed(0)} / ${Number(hailoTs1).toFixed(0)} °C`;
    } else if (effectiveJunctionTemp !== null) {
      elHailoDie.textContent = `~${Number(effectiveJunctionTemp).toFixed(0)} °C`;
    } else {
      elHailoDie.textContent = '-- / -- °C';
    }
  }

  // Update Thermal Status Pill
  const pillThermal = document.getElementById('thermal-status-pill');
  if (pillThermal) {
    const maxT = Math.max(cpuTemp || 0, effectiveJunctionTemp || 0);
    if (isThermalThrottling || maxT >= 100.0) {
      pillThermal.textContent = 'Critical (Throttle)';
      pillThermal.className = 'status-pill unavailable';
    } else if (maxT >= 85.0) {
      pillThermal.textContent = 'Elevated';
      pillThermal.className = 'status-pill degraded';
    } else {
      pillThermal.textContent = 'Nominal';
      pillThermal.className = 'status-pill available';
    }
  }

  // Update Ambient Environment DOM (ESP32-S3 + DHT22)
  const valAmbTemp = document.getElementById('val-ambient-temp');
  const barAmbTemp = document.getElementById('bar-ambient-temp');
  const valAmbHum = document.getElementById('val-ambient-humidity');
  const barAmbHum = document.getElementById('bar-ambient-humidity');
  const valAmbComfort = document.getElementById('val-ambient-comfort-text');
  const pillAmbComfort = document.getElementById('ambient-comfort-pill');

  if (ambientTemp !== null) {
    if (valAmbTemp) valAmbTemp.textContent = `${ambientTemp.toFixed(1)} °C`;
    if (barAmbTemp) {
      const pct = Math.max(0, Math.min(100, (ambientTemp / 50) * 100));
      barAmbTemp.style.width = `${pct}%`;
      if (ambientTemp >= 35) barAmbTemp.style.background = 'var(--accent-rose, #ef4444)';
      else if (ambientTemp >= 28) barAmbTemp.style.background = 'var(--accent-amber, #f59e0b)';
      else barAmbTemp.style.background = '#06b6d4';
    }
  } else {
    if (valAmbTemp) valAmbTemp.textContent = '-- °C';
    if (barAmbTemp) barAmbTemp.style.width = '0%';
  }

  if (ambientHumidity !== null) {
    if (valAmbHum) valAmbHum.textContent = `${ambientHumidity.toFixed(1)} %`;
    if (barAmbHum) {
      const pct = Math.max(0, Math.min(100, ambientHumidity));
      barAmbHum.style.width = `${pct}%`;
    }
  } else {
    if (valAmbHum) valAmbHum.textContent = '-- %';
    if (barAmbHum) barAmbHum.style.width = '0%';
  }

  if (ambientComfort) {
    if (valAmbComfort) {
      valAmbComfort.textContent = ambientComfort;
      if (ambientColor) valAmbComfort.style.color = ambientColor;
    }
    if (pillAmbComfort) {
      pillAmbComfort.textContent = ambientComfort;
      if (ambientColor) {
        pillAmbComfort.style.color = ambientColor;
        pillAmbComfort.style.borderColor = `${ambientColor}66`;
        pillAmbComfort.style.backgroundColor = `${ambientColor}1f`;
      }
    }
  } else if (!ambientConnected) {
    if (valAmbComfort) {
      valAmbComfort.textContent = 'ESP32 Offline';
      valAmbComfort.style.color = 'var(--text-muted, #94a3b8)';
    }
    if (pillAmbComfort) {
      pillAmbComfort.textContent = 'Disconnected';
      pillAmbComfort.style.color = '#94a3b8';
      pillAmbComfort.style.borderColor = 'rgba(148, 163, 184, 0.3)';
      pillAmbComfort.style.backgroundColor = 'rgba(148, 163, 184, 0.1)';
    }
  }

  // Update Resources DOM
  if (cpuUtil !== null) {
    document.getElementById('val-cpu-util').textContent = `${cpuUtil}%`;
    document.getElementById('bar-cpu-util').style.width = `${cpuUtil}%`;
  }
  if (memUtil !== null) {
    document.getElementById('val-mem-util').textContent = `${memUtil}%`;
    document.getElementById('bar-mem-util').style.width = `${memUtil}%`;
  }

  // 5. Update Waveform Charts (1 Hz cadence across the entire detection session duration)
  const currentSec = Math.floor(Date.now() / 1000);
  const shouldTickChart = (currentSec !== lastChartTickSec);
  const nowLabel = new Date().toLocaleTimeString();

  // Accumulate detections into confidence distribution histogram across the whole session
  if (!isWaveformsPaused && data.detections && Array.isArray(data.detections) && data.detections.length > 0) {
    data.detections.forEach(d => {
      if (typeof d.confidence === 'number' && !isNaN(d.confidence)) {
        let idx = Math.floor(d.confidence * 10);
        if (idx >= 10) idx = 9;
        if (idx < 0) idx = 0;
        sessionConfBins[idx]++;
        sessionConfTotal++;
        sessionConfSum += d.confidence;
      }
    });
    updateConfidenceHistogramUI();
  }

  // Real-time Text Indicators (Updated on every incoming packet)
  const lblFps = document.getElementById('lbl-fps-stat');
  if (lblFps) lblFps.textContent = `${fps.toFixed(1)} FPS`;

  const interFrameMs = inference?.inter_frame_ms !== undefined && inference?.inter_frame_ms !== null
    ? inference.inter_frame_ms
    : (fps > 0 ? (1000 / fps) : 0);
  const lblInter = document.getElementById('lbl-inter-frame');
  if (lblInter && interFrameMs !== null && interFrameMs >= 0) {
    lblInter.textContent = `${interFrameMs.toFixed(1)} ms`;
  }

  const detCount = inference?.detections_count !== undefined
    ? inference.detections_count
    : (data.detections ? data.detections.length : 0);
  const lblDet = document.getElementById('lbl-detections-per-frame');
  if (lblDet) lblDet.textContent = `${detCount} object${detCount === 1 ? '' : 's'}`;

  const fanRpm = metrics.hwmon_pwmfan_fan1_rpm && metrics.hwmon_pwmfan_fan1_rpm.value !== null ? metrics.hwmon_pwmfan_fan1_rpm.value : null;
  const fanState = metrics.cooling_pwm_fan_cur_state && metrics.cooling_pwm_fan_cur_state.value !== null ? metrics.cooling_pwm_fan_cur_state.value : null;
  const fanBadge = document.getElementById('lbl-fan-speed');
  if (fanBadge && fanRpm !== null) {
    fanBadge.textContent = `${Math.round(fanRpm)} RPM${fanState !== null ? ' (Lvl ' + fanState + ')' : ''}`;
  }

  const cpu0Freq = metrics.cpu_freq_cpu0_mhz && metrics.cpu_freq_cpu0_mhz.value !== null ? metrics.cpu_freq_cpu0_mhz.value : null;
  const cpu1Freq = metrics.cpu_freq_cpu1_mhz && metrics.cpu_freq_cpu1_mhz.value !== null ? metrics.cpu_freq_cpu1_mhz.value : null;
  const cpu2Freq = metrics.cpu_freq_cpu2_mhz && metrics.cpu_freq_cpu2_mhz.value !== null ? metrics.cpu_freq_cpu2_mhz.value : null;
  const cpu3Freq = metrics.cpu_freq_cpu3_mhz && metrics.cpu_freq_cpu3_mhz.value !== null ? metrics.cpu_freq_cpu3_mhz.value : null;
  const baseTag = document.getElementById('lbl-cpu-base-tag');
  if (baseTag && cpu0Freq !== null) {
    if (isThermalThrottling) {
      baseTag.textContent = `⚠️ Throttled: ${Math.round(curFreq)} MHz (-${Math.round(throttleDrop)} MHz)`;
      baseTag.style.background = '#fee2e2';
      baseTag.style.color = '#b91c1c';
      baseTag.style.border = '1px solid #fca5a5';
    } else if (isFreqCapped) {
      baseTag.textContent = `⚠️ Freq Capped (${Math.round(curFreq)} MHz)`;
      baseTag.style.background = '#fef3c7';
      baseTag.style.color = '#b45309';
      baseTag.style.border = '1px solid #fcd34d';
    } else if (isFullBase) {
      baseTag.textContent = '⚡ 2.4 GHz Full Base Active';
      baseTag.style.background = '#dcfce7';
      baseTag.style.color = '#15803d';
      baseTag.style.border = '1px solid #86efac';
    } else {
      baseTag.textContent = `${Math.round(curFreq)} MHz (Governor)`;
      baseTag.style.background = '#f1f5f9';
      baseTag.style.color = '#0f172a';
      baseTag.style.border = '1px solid #cbd5e1';
    }
  }

  const vIn1 = metrics.hwmon_rp1_adc_in1_voltage && metrics.hwmon_rp1_adc_in1_voltage.value !== null ? metrics.hwmon_rp1_adc_in1_voltage.value : null;
  const vIn2 = metrics.hwmon_rp1_adc_in2_voltage && metrics.hwmon_rp1_adc_in2_voltage.value !== null ? metrics.hwmon_rp1_adc_in2_voltage.value : null;
  const vIn3 = metrics.hwmon_rp1_adc_in3_voltage && metrics.hwmon_rp1_adc_in3_voltage.value !== null ? metrics.hwmon_rp1_adc_in3_voltage.value : null;
  const vIn4 = metrics.hwmon_rp1_adc_in4_voltage && metrics.hwmon_rp1_adc_in4_voltage.value !== null ? metrics.hwmon_rp1_adc_in4_voltage.value : null;

  const procCpu = metrics?.process_cpu_percent && metrics.process_cpu_percent.value !== null ? metrics.process_cpu_percent.value : null;
  const procRss = metrics?.process_memory_rss_mb && metrics.process_memory_rss_mb.value !== null ? metrics.process_memory_rss_mb.value : null;
  const sysLoad = metrics?.load_average_1m && metrics.load_average_1m.value !== null ? metrics.load_average_1m.value : null;
  const lblProc = document.getElementById('lbl-proc-footprint');
  if (lblProc && (procCpu !== null || procRss !== null || sysLoad !== null)) {
    const cpuPart = procCpu !== null ? `${Math.round(procCpu)}% CPU` : '--';
    const rssPart = procRss !== null ? `${Math.round(procRss)} MB RSS` : '--';
    const loadPart = sysLoad !== null ? `Load ${sysLoad.toFixed(2)}` : '--';
    lblProc.textContent = `${cpuPart} | ${rssPart} | ${loadPart}`;
  }

  const diskUtil = metrics?.disk_utilisation && metrics.disk_utilisation.value !== null ? metrics.disk_utilisation.value : null;
  const lblDisk = document.getElementById('lbl-disk-utilisation');
  if (lblDisk && diskUtil !== null) {
    lblDisk.textContent = `${diskUtil.toFixed(1)}% Used`;
  }

  // Hailo NPU Compute Load, Silicon Thermals & Clock Telemetry
  let hailoClockMhz = null;
  let hailoUtilPct = null;

  if (metrics.hailo_clock_frequency_mhz && metrics.hailo_clock_frequency_mhz.value !== null) {
    hailoClockMhz = metrics.hailo_clock_frequency_mhz.value;
  } else if (data.workload && typeof data.workload.clock_frequency_mhz === 'number') {
    hailoClockMhz = data.workload.clock_frequency_mhz;
  } else {
    hailoClockMhz = 400.0;
  }

  if (data.workload && typeof data.workload.npu_utilization_percent === 'number') {
    hailoUtilPct = data.workload.npu_utilization_percent;
  } else if (metrics.hailo_utilization_percent && metrics.hailo_utilization_percent.value !== null) {
    hailoUtilPct = metrics.hailo_utilization_percent.value;
  } else if ((currentActiveBackend === 'hailo' && isInferenceRunning) || isWorkloadSuiteActive) {
    hailoUtilPct = Math.min(100.0, Math.max(0.0, ((fps || 0) * (npuLat || 0) / 1000.0) * 100.0));
  } else {
    hailoUtilPct = 0.0;
  }

  const hailoLoadPct = Math.round((hailoUtilPct || 0) * 10) / 10;
  hailoLoadMovingWindow.push(hailoLoadPct);
  if (hailoLoadMovingWindow.length > 10) hailoLoadMovingWindow.shift();
  const hailoLoadMa = Math.round((hailoLoadMovingWindow.reduce((a, b) => a + b, 0) / hailoLoadMovingWindow.length) * 10) / 10;

  const lblHailoLoad = document.getElementById('lbl-hailo-load-stat');
  if (lblHailoLoad) {
    lblHailoLoad.textContent = `${hailoLoadPct.toFixed(1)}% (MA: ${hailoLoadMa.toFixed(1)}%)`;
  }

  const lblHailoThermal = document.getElementById('lbl-hailo-thermal-stat');
  if (lblHailoThermal) {
    const tjStr = hailoJunctionTemp !== null ? `${hailoJunctionTemp.toFixed(1)}°C` : (hailoTemp !== null ? `${hailoTemp.toFixed(1)}°C` : '--');
    const ts0Str = hailoTs0 !== null ? `${hailoTs0.toFixed(1)}°C` : '--';
    const ts1Str = hailoTs1 !== null ? `${hailoTs1.toFixed(1)}°C` : '--';
    lblHailoThermal.textContent = `Tj: ${tjStr} | TS0: ${ts0Str} | TS1: ${ts1Str}`;
  }

  const lblHailoClock = document.getElementById('lbl-hailo-clock-stat');
  if (lblHailoClock) {
    lblHailoClock.textContent = `${Math.round(hailoClockMhz)} MHz`;
  }

  // Sample waveform series once per second across the full detection duration session
  if (!isWaveformsPaused && shouldTickChart && typeof updateChartSeries === 'function') {
    lastChartTickSec = currentSec;

    // 1. Latency Breakdown History (ms)
    if (latencyChart) updateChartSeries(latencyChart, nowLabel, [npuLat, prepLat, postLat]);

    // 2. Processed Frames Per Second (FPS)
    if (fpsChart) updateChartSeries(fpsChart, nowLabel, [fps]);

    // 3. Inter-Frame Interval (ms)
    if (interFrameChart && interFrameMs !== null && interFrameMs >= 0) {
      updateChartSeries(interFrameChart, nowLabel, [interFrameMs]);
    }

    // 4. Detections Per Frame
    if (detectionsCountChart) {
      updateChartSeries(detectionsCountChart, nowLabel, [detCount]);
    }

    // 5. Thermal Profile History (°C)
    if (thermalChart) updateChartSeries(thermalChart, nowLabel, [cpuTemp || 0, rp1Temp || 0, hailoTemp || 0, ambientTemp !== null ? ambientTemp : null]);

    // 6. System Utilisation History (%)
    if (resourceChart) updateChartSeries(resourceChart, nowLabel, [cpuUtil || 0, memUtil || 0]);

    // 7. Active Cooling & Fan Speed
    if (fanChart && fanRpm !== null) {
      updateChartSeries(fanChart, nowLabel, [fanRpm]);
    }

    // 8. CPU Quad-Core Frequencies (MHz)
    if (cpuFreqChart && cpu0Freq !== null) {
      updateChartSeries(cpuFreqChart, nowLabel, [
        cpu0Freq,
        cpu1Freq !== null ? cpu1Freq : cpu0Freq,
        cpu2Freq !== null ? cpu2Freq : cpu0Freq,
        cpu3Freq !== null ? cpu3Freq : cpu0Freq
      ]);
    }

    // 9. RP1 Southbridge Rail Voltages (V)
    if (voltageChart && vIn1 !== null) {
      updateChartSeries(voltageChart, nowLabel, [
        vIn1,
        vIn2 !== null ? vIn2 : 0,
        vIn3 !== null ? vIn3 : 0,
        vIn4 !== null ? vIn4 : 0
      ]);
    }

    // 10. Process Footprint & System Load
    if (procFootprintChart && (procCpu !== null || procRss !== null || sysLoad !== null)) {
      updateChartSeries(procFootprintChart, nowLabel, [
        procCpu !== null ? procCpu : 0,
        procRss !== null ? procRss : 0,
        sysLoad !== null ? sysLoad : 0
      ]);
    }

    // 11. Disk Utilisation (%)
    if (diskChart && diskUtil !== null) {
      updateChartSeries(diskChart, nowLabel, [diskUtil]);
    }

    // 12. Hailo-8L NPU Compute Load (%)
    if (typeof hailoLoadChart !== 'undefined' && hailoLoadChart) {
      updateChartSeries(hailoLoadChart, nowLabel, [hailoLoadPct, hailoLoadMa]);
    }

    // 13. Hailo-8L Silicon Thermals: Tj & Die Sensors (TS0 / TS1) (°C)
    if (typeof hailoThermalChart !== 'undefined' && hailoThermalChart) {
      updateChartSeries(hailoThermalChart, nowLabel, [
        hailoJunctionTemp !== null ? hailoJunctionTemp : (hailoTemp || 0),
        hailoTs0 !== null ? hailoTs0 : 0,
        hailoTs1 !== null ? hailoTs1 : 0
      ]);
    }

    // 14. Hailo-8L NPU Core Clock Frequency (MHz)
    if (typeof hailoClockChart !== 'undefined' && hailoClockChart) {
      updateChartSeries(hailoClockChart, nowLabel, [
        hailoClockMhz,
        400.0
      ]);
    }

    // Benchmark Telemetry Capture (Relative-time aligned point collection)
    if (currentBenchmarkPhase && (currentBenchmarkPhase === 'hailo' || currentBenchmarkPhase === 'cpu')) {
      if (!benchmarkData[currentBenchmarkPhase]) benchmarkData[currentBenchmarkPhase] = [];
      const relT = benchmarkData[currentBenchmarkPhase].length;
      benchmarkData[currentBenchmarkPhase].push({
        t: relT,
        fps: fps || 0,
        latency_exec: npuLat || 0,
        latency_prep: prepLat || 0,
        latency_post: postLat || 0,
        latency_total: ((npuLat || 0) + (prepLat || 0) + (postLat || 0)),
        interframe: (interFrameMs !== null && interFrameMs >= 0) ? interFrameMs : 0,
        det_count: detCount || 0,
        cpu_util: cpuUtil !== null ? cpuUtil : 0,
        cpu_temp: cpuTemp !== null ? cpuTemp : 0,
        rp1_temp: rp1Temp !== null ? rp1Temp : 0,
        hailo_temp: hailoTemp !== null ? hailoTemp : 0,
        ambient_temp: ambientTemp !== null ? ambientTemp : 0,
        ambient_humidity: ambientHumidity !== null ? ambientHumidity : 0,
        mem_util: memUtil !== null ? memUtil : 0,
        fan_rpm: fanRpm !== null ? fanRpm : 0,
        disk_util: diskUtil !== null ? diskUtil : 0,
        cpu0_freq: cpu0Freq !== null ? cpu0Freq : 0,
        cpu1_freq: cpu1Freq !== null ? cpu1Freq : (cpu0Freq || 0),
        cpu2_freq: cpu2Freq !== null ? cpu2Freq : (cpu0Freq || 0),
        cpu3_freq: cpu3Freq !== null ? cpu3Freq : (cpu0Freq || 0),
        v_in1: vIn1 !== null ? vIn1 : 0,
        v_in2: vIn2 !== null ? vIn2 : 0,
        v_in3: vIn3 !== null ? vIn3 : 0,
        v_in4: vIn4 !== null ? vIn4 : 0,
        proc_cpu: procCpu !== null ? procCpu : 0,
        proc_rss: procRss !== null ? procRss : 0,
        sys_load: sysLoad !== null ? sysLoad : 0,
        npu_load: hailoLoadPct,
        hailo_tj: hailoJunctionTemp !== null ? hailoJunctionTemp : (hailoTemp || 0),
        hailo_ts0: hailoTs0 !== null ? hailoTs0 : 0,
        hailo_ts1: hailoTs1 !== null ? hailoTs1 : 0,
        hailo_clock: hailoClockMhz,
        backend: currentBenchmarkPhase
      });
      if (Array.isArray(detections)) {
        if (!benchmarkConfList[currentBenchmarkPhase]) benchmarkConfList[currentBenchmarkPhase] = [];
        detections.forEach(d => {
          if (d && typeof d.confidence === 'number' && !isNaN(d.confidence)) {
            benchmarkConfList[currentBenchmarkPhase].push(d.confidence);
          }
        });
      }
      updateBenchmarkStepperUI();
    }

    // Update live values in Diagnostics modal if open
    updateModalTelemetryLive(metrics, nowLabel);

    // 6. Update Workload Suite UI & Live Trajectory (Phase 4)
    if (data.workload) {
      updateWorkloadUI(data.workload);
    }
  }

    // 7. Render Detections List
    renderDetections(detections);
  } catch (err) {
    console.error('[TELEMETRY] Error in handleLiveUpdate:', err);
  }
}

function renderDetections(detections) {
  const container = document.getElementById('detections-feed');
  if (!detections || detections.length === 0) {
    container.innerHTML = `
      <div style="color: var(--text-muted); font-size: 0.8rem; text-align: center; padding: 1rem;">
        No objects currently detected
      </div>`;
    return;
  }

  let html = '';
  detections.forEach((d) => {
    const color = CLASS_COLORS[d.class_id % CLASS_COLORS.length];
    const pct = Math.round(d.confidence * 100);
    html += `
      <div class="detection-row">
        <div class="detection-tag">
          <span style="display:inline-block; width:10px; height:10px; border-radius:2px; background:${color};"></span>
          <span>${d.class_name}</span>
        </div>
        <div style="display:flex; align-items:center; gap:0.75rem;">
          <div class="confidence-bar-bg">
            <div class="confidence-bar-fill" style="width:${pct}%; background:${color};"></div>
          </div>
          <span style="font-family:var(--font-mono); font-size:0.75rem; color:var(--text-secondary); width:35px; text-align:right;">
            ${pct}%
          </span>
        </div>
      </div>
    `;
  });
  container.innerHTML = html;
}

// -----------------------------------------------------------------------------
// -----------------------------------------------------------------------------
// Configurable Detection Duration / Session Timer Management
// -----------------------------------------------------------------------------

let detectionDurationSec = 0; // 0 = Continuous (∞)
let detectionTimerHandle = null;
let detectionEndTime = null;

function formatDurationText(sec) {
  if (sec <= 0) return 'Continuous (∞)';
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m ${s}s` : `${m} min`;
}

function formatCountdownText(sec) {
  if (sec <= 0) return '0s left';
  if (sec < 60) return `${sec}s left`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m ${s}s left` : `${m}m left`;
}

function onDetectionDurationChange(val) {
  const sec = parseInt(val, 10) || 0;
  detectionDurationSec = sec;
  localStorage.setItem('evm_detection_duration_sec', sec);

  const badge = document.getElementById('badge-detection-duration');
  if (badge) {
    badge.textContent = formatDurationText(sec);
    badge.style.color = sec > 0 ? 'var(--accent-blue)' : 'var(--text-secondary)';
  }

  const elBenchVal = document.getElementById('lbl-bench-target-val');
  if (elBenchVal) {
    elBenchVal.textContent = sec > 0 ? formatDurationText(sec) : 'Continuous (30s)';
    elBenchVal.style.color = sec > 0 ? 'var(--accent-blue)' : 'var(--text-secondary)';
  }

  // If currently running, sync countdown
  if (isInferenceRunning) {
    if (sec > 0) {
      startDetectionCountdown(sec);
    } else {
      clearDetectionCountdown();
    }
  } else {
    clearDetectionCountdown();
  }
}

function startDetectionCountdown(totalSeconds) {
  clearDetectionCountdown();
  if (totalSeconds <= 0) return;

  const now = Date.now();
  detectionEndTime = now + (totalSeconds * 1000);

  const badgeCountdown = document.getElementById('badge-detection-countdown');
  if (badgeCountdown) {
    badgeCountdown.style.display = 'inline-block';
    badgeCountdown.textContent = formatCountdownText(totalSeconds);
  }

  detectionTimerHandle = setInterval(async () => {
    const remainingMs = detectionEndTime - Date.now();
    const remainingSec = Math.ceil(remainingMs / 1000);

    if (remainingSec <= 0) {
      clearDetectionCountdown();
      console.log(`[TIMER] Configured detection duration (${totalSeconds}s) elapsed. Stopping inference...`);

      // Freeze / Pause Live System & Hardware Telemetry Waveforms so session data is preserved
      setWaveformsPaused(true, 'Detection Time Elapsed');

      if (isInferenceRunning) {
        try {
          await fetch('/api/v1/inference/stop', { method: 'POST' });
        } catch (e) {
          console.error('Failed to auto-stop inference after timer expiry', e);
        }
      }

      const badgeDuration = document.getElementById('badge-detection-duration');
      if (badgeDuration) {
        badgeDuration.textContent = '⏱️ Session Finished';
        badgeDuration.style.color = '#ef4444';
        setTimeout(() => {
          badgeDuration.textContent = formatDurationText(detectionDurationSec);
          badgeDuration.style.color = detectionDurationSec > 0 ? 'var(--accent-blue)' : 'var(--text-secondary)';
        }, 3500);
      }
    } else {
      if (badgeCountdown) {
        badgeCountdown.textContent = formatCountdownText(remainingSec);
      }
    }
  }, 500);
}

function clearDetectionCountdown() {
  if (detectionTimerHandle) {
    clearInterval(detectionTimerHandle);
    detectionTimerHandle = null;
  }
  detectionEndTime = null;
  const badgeCountdown = document.getElementById('badge-detection-countdown');
  if (badgeCountdown) {
    badgeCountdown.style.display = 'none';
  }
}

function initDetectionDurationSlider() {
  const saved = localStorage.getItem('evm_detection_duration_sec');
  const slider = document.getElementById('slider-detection-duration');
  if (saved !== null && slider) {
    slider.value = saved;
    onDetectionDurationChange(saved);
  } else {
    onDetectionDurationChange(0);
  }
}

/**
 * Reset Sensor Catalogue & Live Data Provenance telemetry and detection data:
 * - Wipes backend persisted SQLite telemetry and detections via API
 * - Clears all dashboard charts and modal sensor plotter
 * - Resets modal min/max/avg stats and catalogue table live pills
 * - Resets HUD pills, counters, and detection list
 */
async function resetTelemetryAndDetectionData() {
  console.log('[INFERENCE] Resetting Sensor Catalogue & Live Data Provenance telemetry and detection data...');
  setWaveformsPaused(false, 'Session Reset');

  // 1. Reset frontend charts
  if (typeof resetAllCharts === 'function') {
    resetAllCharts();
  }

  // 2. Reset modal sensor statistics and values
  modalMetricStats = { min: Infinity, max: -Infinity, sum: 0, count: 0 };
  const valEl = document.getElementById('modal-sensor-val');
  const minEl = document.getElementById('modal-sensor-min');
  const maxEl = document.getElementById('modal-sensor-max');
  const avgEl = document.getElementById('modal-sensor-avg');
  if (valEl) valEl.textContent = '--';
  if (minEl) minEl.textContent = '--';
  if (maxEl) maxEl.textContent = '--';
  if (avgEl) avgEl.textContent = '--';

  // 3. Reset catalogue table live value pills
  if (cachedMetricsCatalog && Array.isArray(cachedMetricsCatalog)) {
    cachedMetricsCatalog.forEach(c => {
      const cell = document.getElementById(`cat-val-${c.metric_name}`);
      if (cell) cell.textContent = '--';
    });
  }

  // 4. Reset detection HUD pills and lists
  sessionConfBins = new Array(10).fill(0);
  sessionConfTotal = 0;
  sessionConfSum = 0;
  lastChartTickSec = -1;
  updateConfidenceHistogramUI();

  const container = document.getElementById('detections-feed');
  if (container) {
    container.innerHTML = '<div class="empty-state">No detections in current frame</div>';
  }

  const hudObj = document.getElementById('hud-objects');
  if (hudObj) hudObj.textContent = '0';
  const badgeDet = document.getElementById('badge-det-count');
  if (badgeDet) badgeDet.textContent = '0 objects';
  const lblDet = document.getElementById('lbl-detections-per-frame');
  if (lblDet) lblDet.textContent = '0 objects';

  const hudFps = document.getElementById('hud-fps');
  if (hudFps) hudFps.textContent = '--';
  const hudLat = document.getElementById('hud-hailo-lat');
  if (hudLat) hudLat.textContent = '--';
  const lblLat = document.getElementById('lbl-latency-val');
  if (lblLat) lblLat.textContent = '-- ms';
  const lblFps = document.getElementById('lbl-fps-val');
  if (lblFps) lblFps.textContent = '-- FPS';
  const lblInter = document.getElementById('lbl-inter-frame');
  if (lblInter) lblInter.textContent = '-- ms';

  hailoLoadMovingWindow = [];
  const lblHailoLoad = document.getElementById('lbl-hailo-load-stat');
  if (lblHailoLoad) lblHailoLoad.textContent = '--%';
  const lblHailoThermal = document.getElementById('lbl-hailo-thermal-stat');
  if (lblHailoThermal) lblHailoThermal.textContent = 'Tj: --°C';
  const lblHailoClock = document.getElementById('lbl-hailo-clock-stat');
  if (lblHailoClock) lblHailoClock.textContent = '-- MHz';

  // 5. Call backend reset endpoint to wipe SQLite records
  try {
    await fetch('/api/v1/history/reset', { method: 'POST' });
  } catch (err) {
    console.warn('Failed to call /api/v1/history/reset:', err);
  }
}

async function toggleInference() {
  await toggleGlobalWorkload();
}

function selectSourceTab(type) {
  if (type === 'synthetic' || !type || type === 'none') {
    type = 'file';
  }

  if (type !== 'browser' && typeof isBrowserCameraStreaming !== 'undefined' && isBrowserCameraStreaming) {
    stopBrowserCamera();
  }

  currentSourceType = type;
  document.getElementById('tab-source-file').className = `tab-btn ${type === 'file' ? 'active' : ''}`;
  document.getElementById('tab-source-usb').className = `tab-btn ${type === 'usb' ? 'active' : ''}`;
  document.getElementById('tab-source-picam').className = `tab-btn ${type === 'picamera' ? 'active' : ''}`;
  const tabBrowser = document.getElementById('tab-source-browser');
  if (tabBrowser) {
    tabBrowser.className = `tab-btn ${type === 'browser' ? 'active' : ''}`;
  }

  document.getElementById('controls-file').style.display = type === 'file' ? 'flex' : 'none';
  document.getElementById('controls-usb').style.display = type === 'usb' ? 'flex' : 'none';
  document.getElementById('controls-picam').style.display = type === 'picamera' ? 'flex' : 'none';
  const controlsBrowser = document.getElementById('controls-browser');
  if (controlsBrowser) {
    controlsBrowser.style.display = type === 'browser' ? 'flex' : 'none';
    if (type === 'browser') {
      populateBrowserCameras();
    }
  }
}

async function loadDiscoveredSources() {
  try {
    const res = await fetch('/api/v1/video/sources');
    const data = await res.json();

    // Populate browser client camera devices
    populateBrowserCameras();

    // Populate Files dropdown
    const fileSel = document.getElementById('select-video-file');
    fileSel.innerHTML = '<option value="">Synthetic Edge Stream</option>';
    if (data.media_files) {
      data.media_files.forEach((f) => {
        const opt = document.createElement('option');
        opt.value = f;
        opt.textContent = f;
        fileSel.appendChild(opt);
      });
    }

    // Populate USB dropdown
    const usbSel = document.getElementById('select-usb-device');
    usbSel.innerHTML = '';
    if (data.usb_devices && data.usb_devices.length > 0) {
      data.usb_devices.forEach((dev) => {
        const opt = document.createElement('option');
        opt.value = dev;
        opt.textContent = dev;
        usbSel.appendChild(opt);
      });
    } else {
      usbSel.innerHTML = '<option value="/dev/video0">/dev/video0 (Default)</option>';
    }

    // Set initial tab based on current source
    if (data.current_source_type && data.current_source_type !== 'none') {
      selectSourceTab(data.current_source_type);
    }

    // Reflect currently active video file in dropdown
    if (data.current_source_id && data.current_source_id.startsWith('file:')) {
      const activeFile = data.current_source_id.replace(/^file:/, '');
      if (activeFile && fileSel.querySelector(`option[value="${activeFile}"]`)) {
        fileSel.value = activeFile;
      }
    }
  } catch (e) {
    console.error('Failed to load video sources', e);
  }
}

async function switchToFileSource() {
  const fileVal = document.getElementById('select-video-file').value;
  try {
    const res = await fetch('/api/v1/video/source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_type: 'file',
        file_path: fileVal ? `media/${fileVal}` : null,
        loop: true
      })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to switch to video file' }));
      alert(`Video file error: ${err.detail}`);
    }
  } catch (e) {
    console.error('Failed to switch to file source', e);
  }
}

function triggerVideoUpload() {
  const fileInput = document.getElementById('input-upload-video');
  if (fileInput) {
    fileInput.click();
  }
}

async function handleVideoUpload(input) {
  if (!input.files || input.files.length === 0) return;
  const file = input.files[0];
  const uploadBtn = document.getElementById('btn-upload-video');
  const originalText = uploadBtn ? uploadBtn.innerHTML : '📤 Upload Video';

  if (uploadBtn) {
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '⏳ Uploading...';
  }

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/v1/video/upload', {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
      alert(`Upload failed: ${err.detail || 'Server error'}`);
      return;
    }

    const data = await res.json();
    console.log('Video uploaded successfully:', data);

    // Refresh dropdown options and select newly uploaded file
    await loadDiscoveredSources();

    const fileSel = document.getElementById('select-video-file');
    if (fileSel && data.filename) {
      fileSel.value = data.filename;
    }

    // Ensure tab is set to file
    selectSourceTab('file');
  } catch (err) {
    console.error('Error during video upload:', err);
    alert(`Error uploading video: ${err.message}`);
  } finally {
    if (uploadBtn) {
      uploadBtn.disabled = false;
      uploadBtn.innerHTML = originalText;
    }
    input.value = '';
  }
}

async function switchToUsbSource() {
  const devVal = document.getElementById('select-usb-device').value;
  try {
    await fetch('/api/v1/video/source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_type: 'usb',
        device: devVal,
        width: 640,
        height: 480,
        fps: 30
      })
    });
  } catch (e) {
    console.error('Failed to switch to USB source', e);
  }
}

async function switchToPiCamSource() {
  const btn = document.getElementById('btn-activate-picam');
  const originalText = btn ? btn.textContent : 'Activate CSI Camera';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Activating...';
  }
  try {
    const res = await fetch('/api/v1/video/source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_type: 'picamera',
        camera_num: 0,
        width: 640,
        height: 480,
        fps: 30
      })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to activate CSI camera' }));
      alert(`Pi Camera Notice: ${err.detail}`);
    } else {
      const data = await res.json();
      if (data.source_info && data.source_info.active_type !== 'picamera') {
        const msg = data.source_info.error_status || 'CSI Camera could not be activated.';
        alert(`Pi Camera Notice: ${msg}`);
      }
    }
  } catch (e) {
    console.error('Failed to activate CSI camera', e);
    alert(`Failed to activate CSI camera: ${e.message || e}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

// -----------------------------------------------------------------------------
// Client Web Browser Camera Streaming Coordination
// -----------------------------------------------------------------------------

let browserStream = null;
let browserWs = null;
let browserAnimFrameId = null;
let isBrowserCameraStreaming = false;

async function populateBrowserCameras() {
  const sel = document.getElementById('select-browser-camera');
  const notice = document.getElementById('browser-cam-security-notice');
  if (!sel) return;

  const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  const isSecure = window.isSecureContext || isLocalhost;

  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    if (!isSecure) {
      if (notice) notice.style.display = 'block';
      sel.innerHTML = '<option value="">🔒 Requires Secure Origin (localhost / flag)</option>';
    } else {
      sel.innerHTML = '<option value="">Camera API Not Supported</option>';
    }
    return;
  }

  if (notice && isSecure) {
    notice.style.display = 'none';
  }

  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const videoDevices = devices.filter((d) => d.kind === 'videoinput');
    const prevVal = sel.value;
    sel.innerHTML = '';
    if (videoDevices.length === 0) {
      sel.innerHTML = '<option value="">Default Camera</option>';
      return;
    }
    videoDevices.forEach((dev, idx) => {
      const opt = document.createElement('option');
      opt.value = dev.deviceId;
      opt.textContent = dev.label || `Camera ${idx + 1} (${dev.deviceId ? dev.deviceId.slice(0, 8) : 'Webcam'}...)`;
      sel.appendChild(opt);
    });
    if (prevVal && sel.querySelector(`option[value="${prevVal}"]`)) {
      sel.value = prevVal;
    }
  } catch (e) {
    console.debug('Failed to enumerate media devices:', e);
  }
}

async function onBrowserCameraDeviceChange() {
  if (isBrowserCameraStreaming) {
    await stopBrowserCamera();
    await startBrowserCamera();
  }
}

async function toggleBrowserCamera() {
  if (isBrowserCameraStreaming) {
    await stopBrowserCamera();
  } else {
    await startBrowserCamera();
  }
}

async function startBrowserCamera() {
  const btn = document.getElementById('btn-activate-browser-cam');
  const badge = document.getElementById('badge-browser-cam-status');
  const sel = document.getElementById('select-browser-camera');
  const notice = document.getElementById('browser-cam-security-notice');
  const selectedDeviceId = sel ? sel.value : null;

  const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  const isSecure = window.isSecureContext || isLocalhost;

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    if (!isSecure) {
      if (notice) notice.style.display = 'block';
      alert(
        `Browser Camera Security Restriction:\n\n` +
        `Web browsers disable camera hardware access when a website is loaded over non-secure HTTP on a LAN IP (${window.location.origin}).\n\n` +
        `Quick ways to enable your laptop camera:\n\n` +
        `Option 1 (Recommended): Run an SSH tunnel on your laptop:\n` +
        `  ssh -L 8000:localhost:8000 iotgwai@10.199.153.118\n` +
        `  Then open http://localhost:8000 (localhost is automatically trusted by browsers!)\n\n` +
        `Option 2 (Chrome/Edge):\n` +
        `  1. Navigate to: chrome://flags/#unsafely-treat-insecure-origin-as-secure\n` +
        `  2. Enter: ${window.location.origin}\n` +
        `  3. Select "Enabled" and relaunch your browser.`
      );
    } else {
      alert('Camera access is not supported or was blocked by your browser settings.');
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🎥 Activate My Camera';
    }
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Requesting Camera...';
  }

  try {
    const videoConstraints = {
      width: { ideal: 640 },
      height: { ideal: 480 },
      frameRate: { ideal: 20, max: 30 },
    };
    if (selectedDeviceId) {
      videoConstraints.deviceId = { exact: selectedDeviceId };
    }

    browserStream = await navigator.mediaDevices.getUserMedia({
      video: videoConstraints,
      audio: false,
    });

    const videoElem = document.getElementById('client-webcam-video');
    if (videoElem) {
      videoElem.srcObject = browserStream;
      await videoElem.play();
    }

    // Re-populate device labels now that camera permission has been granted by browser
    await populateBrowserCameras();
    if (selectedDeviceId && sel && sel.querySelector(`option[value="${selectedDeviceId}"]`)) {
      sel.value = selectedDeviceId;
    }

    // Inform backend of source transition to 'browser'
    try {
      await fetch('/api/v1/video/source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_type: 'browser',
          width: 640,
          height: 480,
          fps: 20,
        }),
      });
    } catch (apiErr) {
      console.warn('Backend source switch warning, proceeding with browser streaming:', apiErr);
    }

    // Connect WebSocket stream for low-latency frame ingestion
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${window.location.host}/api/v1/video/browser-stream`;
    browserWs = new WebSocket(wsUrl);
    browserWs.binaryType = 'blob';

    browserWs.onopen = () => {
      console.log('Browser camera streaming WebSocket established');
      isBrowserCameraStreaming = true;
      if (btn) {
        btn.disabled = false;
        btn.textContent = '⏹ Stop My Camera';
        btn.classList.add('btn-danger');
      }
      if (badge) {
        badge.style.display = 'inline-block';
        badge.textContent = 'Live (640x480)';
      }
      startBrowserFrameCaptureLoop();
    };

    browserWs.onerror = (err) => {
      console.warn('Browser camera WebSocket error, using HTTP frame post fallback:', err);
      if (!isBrowserCameraStreaming) {
        isBrowserCameraStreaming = true;
        if (btn) {
          btn.disabled = false;
          btn.textContent = '⏹ Stop My Camera';
          btn.classList.add('btn-danger');
        }
        if (badge) {
          badge.style.display = 'inline-block';
          badge.textContent = 'Live (HTTP)';
        }
        startBrowserFrameCaptureLoop();
      }
    };

    browserWs.onclose = () => {
      console.log('Browser camera streaming WebSocket closed');
    };

  } catch (err) {
    console.error('Failed to access client camera:', err);
    alert(`Could not start camera: ${err.message || err}\n\nPlease check camera permissions in your browser address bar.`);
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🎥 Activate My Camera';
      btn.classList.remove('btn-danger');
    }
    if (badge) badge.style.display = 'none';
    isBrowserCameraStreaming = false;
  }
}

function startBrowserFrameCaptureLoop() {
  const video = document.getElementById('client-webcam-video');
  const canvas = document.getElementById('client-webcam-canvas');
  const mirrorCheck = document.getElementById('check-browser-mirror');
  if (!video || !canvas) return;

  const ctx = canvas.getContext('2d');
  let lastSentTime = 0;
  const targetInterval = 1000 / 20; // 20 frames per second
  let isSending = false;

  function captureFrame(now) {
    if (!isBrowserCameraStreaming) return;

    if (now - lastSentTime >= targetInterval && !isSending && video.readyState >= 2) {
      lastSentTime = now;
      isSending = true;

      const w = 640;
      const h = 480;
      canvas.width = w;
      canvas.height = h;

      ctx.save();
      if (mirrorCheck && mirrorCheck.checked) {
        ctx.translate(w, 0);
        ctx.scale(-1, 1);
      }
      ctx.drawImage(video, 0, 0, w, h);
      ctx.restore();

      canvas.toBlob(
        async (blob) => {
          if (!blob || !isBrowserCameraStreaming) {
            isSending = false;
            return;
          }

          if (browserWs && browserWs.readyState === WebSocket.OPEN) {
            try {
              browserWs.send(blob);
            } catch (_) {}
            isSending = false;
          } else {
            try {
              await fetch('/api/v1/video/browser-frame', {
                method: 'POST',
                headers: { 'Content-Type': 'image/jpeg' },
                body: blob,
              });
            } catch (e) {
              console.debug('HTTP browser-frame send error:', e);
            } finally {
              isSending = false;
            }
          }
        },
        'image/jpeg',
        0.82
      );
    }

    browserAnimFrameId = requestAnimationFrame(captureFrame);
  }

  browserAnimFrameId = requestAnimationFrame(captureFrame);
}

async function stopBrowserCamera() {
  isBrowserCameraStreaming = false;
  if (browserAnimFrameId) {
    cancelAnimationFrame(browserAnimFrameId);
    browserAnimFrameId = null;
  }

  if (browserWs) {
    try {
      browserWs.close();
    } catch (_) {}
    browserWs = null;
  }

  if (browserStream) {
    try {
      browserStream.getTracks().forEach((t) => t.stop());
    } catch (_) {}
    browserStream = null;
  }

  const video = document.getElementById('client-webcam-video');
  if (video) video.srcObject = null;

  const btn = document.getElementById('btn-activate-browser-cam');
  const badge = document.getElementById('badge-browser-cam-status');
  if (btn) {
    btn.disabled = false;
    btn.textContent = '🎥 Activate My Camera';
    btn.classList.remove('btn-danger');
  }
  if (badge) badge.style.display = 'none';
}

async function controlPlayback(action) {
  try {
    await fetch('/api/v1/video/playback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });
  } catch (e) {
    console.error('Failed to control playback', e);
  }
}

function captureSnapshot() {
  window.open('/api/v1/video/frame', '_blank');
}

function toggleFullscreen() {
  const container = document.getElementById('video-container');
  if (!document.fullscreenElement) {
    container.requestFullscreen().catch(err => alert(`Fullscreen error: ${err.message}`));
  } else {
    document.exitFullscreen();
  }
}

// Diagnostics Modal & Interactive Sensor Plotter
let activeModalMetric = 'hwmon_pwmfan_fan1_rpm';
let activeModalUnit = 'rpm';
let modalMetricStats = { min: Infinity, max: -Infinity, sum: 0, count: 0 };
let cachedMetricsCatalog = [];

async function openDiagnosticsModal() {
  const modal = document.getElementById('modal-diagnostics');
  modal.style.display = 'flex';

  try {
    // 1. System Info
    const sysRes = await fetch('/api/v1/system/info');
    const sys = await sysRes.json();
    document.getElementById('diag-host').textContent = sys.hostname;
    document.getElementById('diag-os').textContent = `${sys.platform} (${sys.os_kernel})`;
    document.getElementById('diag-cpu').textContent = `${sys.cpu_model} (Python ${sys.python_version})`;
    document.getElementById('diag-hailo-dev').textContent = sys.hailo_device_present ? 'Present (/dev/hailo0)' : 'Not Found';
    document.getElementById('diag-hailo-pkg').textContent = sys.hailo_runtime_installed ? 'Installed (hailo_platform)' : 'Not Installed';

    // 2. Metrics Catalog
    const catRes = await fetch('/api/v1/metrics/catalog');
    cachedMetricsCatalog = await catRes.json();
    const tbody = document.getElementById('table-catalog-body');
    const select = document.getElementById('select-modal-sensor');

    if (cachedMetricsCatalog && cachedMetricsCatalog.length > 0) {
      // Populate select dropdown
      select.innerHTML = cachedMetricsCatalog.map(c => `
        <option value="${c.metric_name}" ${c.metric_name === activeModalMetric ? 'selected' : ''}>
          ${c.metric_name} (${c.unit}) &bull; [${c.source}]
        </option>
      `).join('');

      // Populate table with Live Value and Plot button
      tbody.innerHTML = cachedMetricsCatalog.map(c => `
        <tr id="row-cat-${c.metric_name}">
          <td>
            <a href="javascript:void(0)" onclick="plotMetricFromCatalogue('${c.metric_name}')" style="color: var(--accent-blue); text-decoration: none; font-weight: 600;">
              <code>${c.metric_name}</code>
            </a>
          </td>
          <td><span id="cat-val-${c.metric_name}" class="metric-live-pill">--</span></td>
          <td>${c.unit}</td>
          <td><span style="color: var(--text-muted); font-size: 0.75rem;">${c.source}</span></td>
          <td><span class="status-pill ${c.current_status.toLowerCase()}">${c.current_status}</span></td>
          <td style="text-align: right;">
            <button class="btn btn-ghost" onclick="plotMetricFromCatalogue('${c.metric_name}')" style="padding: 0.25rem 0.55rem; font-size: 0.72rem; border-radius: 4px;">
              📈 Plot
            </button>
          </td>
        </tr>
      `).join('');

      // Initialise selected metric plot
      await onModalSensorSelected(activeModalMetric || cachedMetricsCatalog[0].metric_name);
    }
  } catch (e) {
    console.error('Failed to load diagnostics', e);
  }
}

async function onModalSensorSelected(metricName) {
  if (!metricName) return;
  activeModalMetric = metricName;
  const select = document.getElementById('select-modal-sensor');
  if (select && select.value !== metricName) {
    select.value = metricName;
  }

  const metricInfo = cachedMetricsCatalog.find(c => c.metric_name === metricName);
  activeModalUnit = metricInfo ? metricInfo.unit : '';

  // Reset stats
  modalMetricStats = { min: Infinity, max: -Infinity, sum: 0, count: 0 };
  const valEl = document.getElementById('modal-sensor-val');
  const minEl = document.getElementById('modal-sensor-min');
  const maxEl = document.getElementById('modal-sensor-max');
  const avgEl = document.getElementById('modal-sensor-avg');
  if (valEl) valEl.textContent = '--';
  if (minEl) minEl.textContent = '--';
  if (maxEl) maxEl.textContent = '--';
  if (avgEl) avgEl.textContent = '--';

  // Fetch recent history
  try {
    const res = await fetch(`/api/v1/metrics/history?metric_name=${encodeURIComponent(metricName)}&limit=35`);
    const history = await res.json();
    if (Array.isArray(history) && history.length > 0) {
      history.forEach(h => {
        if (h.value !== null && typeof h.value === 'number') {
          modalMetricStats.min = Math.min(modalMetricStats.min, h.value);
          modalMetricStats.max = Math.max(modalMetricStats.max, h.value);
          modalMetricStats.sum += h.value;
          modalMetricStats.count += 1;
        }
      });
      const lastVal = history[history.length - 1].value;
      const fmt = (n) => Number.isInteger(n) ? n : n.toFixed(2);
      if (lastVal !== null && typeof lastVal === 'number') {
        if (valEl) valEl.textContent = `${fmt(lastVal)} ${activeModalUnit}`;
      }
      if (modalMetricStats.count > 0) {
        if (minEl) minEl.textContent = `${fmt(modalMetricStats.min)} ${activeModalUnit}`;
        if (maxEl) maxEl.textContent = `${fmt(modalMetricStats.max)} ${activeModalUnit}`;
        if (avgEl) avgEl.textContent = `${fmt(modalMetricStats.sum / modalMetricStats.count)} ${activeModalUnit}`;
      }
    }

    if (typeof initOrUpdateModalSensorChart === 'function') {
      initOrUpdateModalSensorChart(metricName, activeModalUnit, history);
    }
  } catch (err) {
    console.error('Failed to fetch sensor history', err);
  }
}

function plotMetricFromCatalogue(metricName) {
  const select = document.getElementById('select-modal-sensor');
  if (select) select.value = metricName;
  onModalSensorSelected(metricName);
  const plotter = document.querySelector('.modal-sensor-plotter-card');
  if (plotter) plotter.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function updateModalTelemetryLive(metrics, nowLabel) {
  const modal = document.getElementById('modal-diagnostics');
  if (!modal || modal.style.display !== 'flex') return;

  // 1. Update live cells in table
  for (const [name, entry] of Object.entries(metrics)) {
    const el = document.getElementById(`cat-val-${name}`);
    if (el) {
      if (entry.value !== null && entry.value !== undefined) {
        const valFormatted = typeof entry.value === 'number'
          ? (Number.isInteger(entry.value) ? entry.value : entry.value.toFixed(2))
          : entry.value;
        el.textContent = `${valFormatted} ${entry.unit || ''}`;
      } else {
        el.textContent = 'N/A';
      }
    }
  }

  // 2. Stream to active modal sensor chart
  if (activeModalMetric && metrics[activeModalMetric]) {
    const entry = metrics[activeModalMetric];
    if (entry.value !== null && entry.value !== undefined && typeof entry.value === 'number') {
      const val = entry.value;
      if (typeof appendModalSensorPoint === 'function') {
        appendModalSensorPoint(nowLabel, val);
      }
      modalMetricStats.min = Math.min(modalMetricStats.min, val);
      modalMetricStats.max = Math.max(modalMetricStats.max, val);
      modalMetricStats.sum += val;
      modalMetricStats.count += 1;
      const avg = modalMetricStats.sum / modalMetricStats.count;

      const unitStr = entry.unit || '';
      const fmt = (n) => Number.isInteger(n) ? n : n.toFixed(2);
      const valEl = document.getElementById('modal-sensor-val');
      const minEl = document.getElementById('modal-sensor-min');
      const maxEl = document.getElementById('modal-sensor-max');
      const avgEl = document.getElementById('modal-sensor-avg');
      if (valEl) valEl.textContent = `${fmt(val)} ${unitStr}`;
      if (minEl) minEl.textContent = `${fmt(modalMetricStats.min)} ${unitStr}`;
      if (maxEl) maxEl.textContent = `${fmt(modalMetricStats.max)} ${unitStr}`;
      if (avgEl) avgEl.textContent = `${fmt(avg)} ${unitStr}`;
    }
  }
}

function closeDiagnosticsModal() {
  document.getElementById('modal-diagnostics').style.display = 'none';
}

// Initial readiness check
async function checkInitialReadiness() {
  try {
    const res = await fetch('/api/v1/ready');
    const data = await res.json();
    const hailoBadge = document.getElementById('badge-hailo');
    const modelBadge = document.getElementById('badge-model');

    if (data.hailo_ready) {
      hailoBadge.className = 'badge active';
      document.getElementById('label-hailo').textContent = 'Hailo-8L: Online';
    } else if (data.is_mock) {
      hailoBadge.className = 'badge mock';
      document.getElementById('label-hailo').textContent = 'Hailo-8L: Mock Mode';
    } else {
      hailoBadge.className = 'badge warning';
      document.getElementById('label-hailo').textContent = 'Hailo-8L: Missing';
    }

    if (data.ready) {
      modelBadge.className = 'badge active';
      document.getElementById('label-model').textContent = `YOLO11: ${data.model_status}`;
    } else {
      modelBadge.className = 'badge warning';
      document.getElementById('label-model').textContent = `YOLO11: ${data.model_status}`;
    }
  } catch (e) {
    console.error('Failed readiness check', e);
  }
}

// Backend switching & availability
async function loadAvailableBackends() {
  try {
    const res = await fetch('/api/v1/inference/backends');
    if (!res.ok) return;
    const data = await res.json();
    const btnHailo = document.getElementById('btn-backend-hailo');
    const btnCpu = document.getElementById('btn-backend-cpu');
    const btnAuto = document.getElementById('btn-run-auto-benchmark');
    const btnAutoWb = document.getElementById('btn-run-auto-waveform-bench');

    if (btnHailo && data.backends?.hailo) {
      btnHailo.disabled = !data.backends.hailo.available;
      if (!data.backends.hailo.available) {
        btnHailo.title = 'Hailo-8L NPU unavailable (hardware node, driver, or HEF model missing)';
        if (btnAuto) btnAuto.title = 'Automated Dual Benchmark requires Hailo-8L NPU (currently unavailable on container runtime)';
        if (btnAutoWb) btnAutoWb.title = 'Automated Dual Benchmark requires Hailo-8L NPU (currently unavailable on container runtime)';
      } else {
        btnHailo.title = 'Hailo-8L NPU Accelerator';
        if (btnAuto) btnAuto.title = 'Run Automated Dual Benchmark (Hailo-8L vs Host CPU) based on Detection Time slider';
        if (btnAutoWb) btnAutoWb.title = 'Run Automated Dual Benchmark (Hailo-8L vs Host CPU) based on Detection Time slider';
      }
    }

    if (btnCpu && data.backends?.cpu) {
      btnCpu.disabled = !data.backends.cpu.available;
      if (!data.backends.cpu.available) {
        btnCpu.title = 'CPU ONNX model missing';
      } else {
        btnCpu.title = 'CPU Inference (ONNX Runtime)';
      }
    }

    if (!isSwitchingBackend) {
      syncWorkloadModeSelectorUI(getActiveRunningWorkload());
    }

    // Synchronise header Hailo badge
    const hailoBadge = document.getElementById('badge-hailo');
    const hailoLabel = document.getElementById('label-hailo');
    if (hailoBadge && hailoLabel) {
      if (data.backends?.hailo?.available) {
        hailoBadge.className = 'badge active';
        hailoLabel.textContent = (data.current_backend === 'hailo') ? 'Hailo-8L: Online' : 'Hailo-8L: Ready';
      } else {
        hailoBadge.className = 'badge warning';
        hailoLabel.textContent = 'Hailo-8L: Missing';
      }
    }
  } catch (e) {
    console.error('Failed to load available backends', e);
  }
}

async function switchBackend(backend) {
  if (isSwitchingBackend) return;
  const btnHailo = document.getElementById('btn-backend-hailo');
  const btnCpu = document.getElementById('btn-backend-cpu');
  const targetBtn = backend === 'cpu' ? btnCpu : btnHailo;

  if (targetBtn && targetBtn.classList.contains('active')) {
    console.log(`[INFERENCE] Backend '${backend}' is already active`);
    return;
  }

  const originalContent = targetBtn ? targetBtn.innerHTML : '';
  try {
    isSwitchingBackend = true;
    if (btnHailo) btnHailo.disabled = true;
    if (btnCpu) btnCpu.disabled = true;

    if (targetBtn) {
      targetBtn.innerHTML = '<span>⏳</span> Switching...';
    }

    const res = await fetch('/api/v1/inference/backend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backend })
    });

    if (!res.ok) {
      const err = await res.json();
      alert(`Backend switch failed: ${err.detail || 'Unknown error'}`);
    } else {
      console.log(`[INFERENCE] Switched backend to ${backend}`);
      currentActiveBackend = backend;
      if (activeWorkloadMode === 'hailo' || activeWorkloadMode === 'cpu') {
        activeWorkloadMode = backend;
      }
      updateMasterWorkloadButton();
      // Wait briefly for worker process to reconfigure pipeline
      await new Promise(r => setTimeout(r, 350));
    }
  } catch (e) {
    console.error('Failed to switch backend', e);
    alert(`Error switching backend: ${e.message}`);
  } finally {
    if (targetBtn && originalContent) {
      targetBtn.innerHTML = originalContent;
    }
    if (btnHailo) btnHailo.disabled = false;
    if (btnCpu) btnCpu.disabled = false;
    isSwitchingBackend = false;
    await loadAvailableBackends();
  }
}

/**
 * Pre-populate the Process Footprint & System Load chart with recent historical points
 */
async function seedProcFootprintHistory() {
  try {
    const [resCpu, resRss, resLoad] = await Promise.all([
      fetch('/api/v1/metrics/history?metric_name=process_cpu_percent&limit=30'),
      fetch('/api/v1/metrics/history?metric_name=process_memory_rss_mb&limit=30'),
      fetch('/api/v1/metrics/history?metric_name=load_average_1m&limit=30')
    ]);

    if (!resCpu.ok || !resRss.ok || !resLoad.ok) return;

    const [dataCpu, dataRss, dataLoad] = await Promise.all([
      resCpu.json(),
      resRss.json(),
      resLoad.json()
    ]);

    if (!procFootprintChart) return;
    if (procFootprintChart.data.labels.length > 5) return;

    const count = Math.max(dataCpu.length, dataRss.length, dataLoad.length);
    if (count === 0) return;

    const labels = [];
    const cpuVals = [];
    const rssVals = [];
    const loadVals = [];

    for (let i = 0; i < count; i++) {
      const c = dataCpu[i];
      const r = dataRss[i];
      const l = dataLoad[i];
      const ts = c?.timestamp_utc || r?.timestamp_utc || l?.timestamp_utc;
      const label = ts ? new Date(ts).toLocaleTimeString() : '';
      labels.push(label);
      cpuVals.push(c?.value !== null && c?.value !== undefined ? c.value : 0);
      rssVals.push(r?.value !== null && r?.value !== undefined ? r.value : 0);
      loadVals.push(l?.value !== null && l?.value !== undefined ? l.value : 0);
    }

    procFootprintChart.data.labels = labels;
    if (procFootprintChart.data.datasets[0]) procFootprintChart.data.datasets[0].data = cpuVals;
    if (procFootprintChart.data.datasets[1]) procFootprintChart.data.datasets[1].data = rssVals;
    if (procFootprintChart.data.datasets[2]) procFootprintChart.data.datasets[2].data = loadVals;
    procFootprintChart.update('none');

    const lastCpu = cpuVals[cpuVals.length - 1];
    const lastRss = rssVals[rssVals.length - 1];
    const lastLoad = loadVals[loadVals.length - 1];
    const lblProc = document.getElementById('lbl-proc-footprint');
    if (lblProc && count > 0) {
      lblProc.textContent = `${Math.round(lastCpu)}% CPU | ${Math.round(lastRss)} MB RSS | Load ${lastLoad.toFixed(2)}`;
    }
  } catch (err) {
    console.debug('[TELEMETRY] Note on seeding proc footprint history:', err);
  }
}

/**
 * Pre-populate RP1 rail voltages with recent historical points
 */
async function seedVoltageHistory() {
  try {
    const [r1, r2, r3, r4] = await Promise.all([
      fetch('/api/v1/metrics/history?metric_name=hwmon_rp1_adc_in1_voltage&limit=30'),
      fetch('/api/v1/metrics/history?metric_name=hwmon_rp1_adc_in2_voltage&limit=30'),
      fetch('/api/v1/metrics/history?metric_name=hwmon_rp1_adc_in3_voltage&limit=30'),
      fetch('/api/v1/metrics/history?metric_name=hwmon_rp1_adc_in4_voltage&limit=30')
    ]);

    if (!r1.ok) return;

    const [d1, d2, d3, d4] = await Promise.all([
      r1.json(),
      r2.ok ? r2.json() : [],
      r3.ok ? r3.json() : [],
      r4.ok ? r4.json() : []
    ]);

    if (!voltageChart || voltageChart.data.labels.length > 5) return;
    const count = d1.length;
    if (count === 0) return;

    const labels = [];
    const v1 = [], v2 = [], v3 = [], v4 = [];
    for (let i = 0; i < count; i++) {
      labels.push(d1[i]?.timestamp_utc ? new Date(d1[i].timestamp_utc).toLocaleTimeString() : '');
      v1.push(d1[i]?.value !== null && d1[i]?.value !== undefined ? d1[i].value : 0);
      v2.push(d2[i]?.value !== null && d2[i]?.value !== undefined ? d2[i].value : 0);
      v3.push(d3[i]?.value !== null && d3[i]?.value !== undefined ? d3[i].value : 0);
      v4.push(d4[i]?.value !== null && d4[i]?.value !== undefined ? d4[i].value : 0);
    }

    voltageChart.data.labels = labels;
    if (voltageChart.data.datasets[0]) voltageChart.data.datasets[0].data = v1;
    if (voltageChart.data.datasets[1]) voltageChart.data.datasets[1].data = v2;
    if (voltageChart.data.datasets[2]) voltageChart.data.datasets[2].data = v3;
    if (voltageChart.data.datasets[3]) voltageChart.data.datasets[3].data = v4;
    voltageChart.update('none');
  } catch (err) {
    console.debug('[TELEMETRY] Note on seeding voltage history:', err);
  }
}

/**
 * Pre-populate CPU Quad-Core frequencies with recent historical points
 */
async function seedCpuFreqHistory() {
  try {
    const [r0, r1, r2, r3] = await Promise.all([
      fetch('/api/v1/metrics/history?metric_name=cpu_freq_cpu0_mhz&limit=30'),
      fetch('/api/v1/metrics/history?metric_name=cpu_freq_cpu1_mhz&limit=30'),
      fetch('/api/v1/metrics/history?metric_name=cpu_freq_cpu2_mhz&limit=30'),
      fetch('/api/v1/metrics/history?metric_name=cpu_freq_cpu3_mhz&limit=30')
    ]);

    if (!r0.ok) return;

    const [d0, d1, d2, d3] = await Promise.all([
      r0.json(),
      r1.ok ? r1.json() : [],
      r2.ok ? r2.json() : [],
      r3.ok ? r3.json() : []
    ]);

    if (!cpuFreqChart || cpuFreqChart.data.labels.length > 5) return;
    const count = d0.length;
    if (count === 0) return;

    const labels = [];
    const f0 = [], f1 = [], f2 = [], f3 = [];
    for (let i = 0; i < count; i++) {
      labels.push(d0[i]?.timestamp_utc ? new Date(d0[i].timestamp_utc).toLocaleTimeString() : '');
      const v0 = d0[i]?.value ?? 0;
      f0.push(v0);
      f1.push(d1[i]?.value ?? v0);
      f2.push(d2[i]?.value ?? v0);
      f3.push(d3[i]?.value ?? v0);
    }

    cpuFreqChart.data.labels = labels;
    if (cpuFreqChart.data.datasets[0]) cpuFreqChart.data.datasets[0].data = f0;
    if (cpuFreqChart.data.datasets[1]) cpuFreqChart.data.datasets[1].data = f1;
    if (cpuFreqChart.data.datasets[2]) cpuFreqChart.data.datasets[2].data = f2;
    if (cpuFreqChart.data.datasets[3]) cpuFreqChart.data.datasets[3].data = f3;
    cpuFreqChart.update('none');
  } catch (err) {
    console.debug('[TELEMETRY] Note on seeding CPU freq history:', err);
  }
}

/**
 * Pre-populate Disk Utilisation chart with recent historical points
 */
async function seedDiskHistory() {
  try {
    const res = await fetch('/api/v1/metrics/history?metric_name=disk_utilisation&limit=30');
    if (!res.ok) return;
    const data = await res.json();
    if (!diskChart || diskChart.data.labels.length > 5) return;
    if (data.length === 0) return;

    const labels = [];
    const values = [];
    data.forEach(item => {
      labels.push(item?.timestamp_utc ? new Date(item.timestamp_utc).toLocaleTimeString() : '');
      values.push(item?.value !== null && item?.value !== undefined ? item.value : 0);
    });

    diskChart.data.labels = labels;
    if (diskChart.data.datasets[0]) diskChart.data.datasets[0].data = values;
    diskChart.update('none');

    const lastVal = values[values.length - 1];
    const lblDisk = document.getElementById('lbl-disk-utilisation');
    if (lblDisk && lastVal !== undefined) {
      lblDisk.textContent = `${lastVal.toFixed(1)}% Used`;
    }
  } catch (err) {
    console.debug('[TELEMETRY] Note on seeding disk history:', err);
  }
}

/**
 * Pre-populate Inference (Inter-frame, FPS, Detections count) and Confidence Histogram from historical SQLite records
 */
async function seedInferenceAndDetectionHistory() {
  try {
    const [resFrames, resDets] = await Promise.all([
      fetch('/api/v1/inference/history?limit=30'),
      fetch('/api/v1/detections/history?limit=500')
    ]);

    if (resFrames.ok) {
      const frames = await resFrames.json();
      if (frames.length > 0) {
        const labels = [];
        const intervals = [];
        const detCounts = [];

        for (let i = 0; i < frames.length; i++) {
          const f = frames[i];
          const label = f.timestamp_utc ? new Date(f.timestamp_utc).toLocaleTimeString() : '';
          labels.push(label);
          detCounts.push(f.detections_count !== undefined ? f.detections_count : 0);

          if (i > 0 && frames[i - 1].timestamp_utc && f.timestamp_utc) {
            const dt = (new Date(f.timestamp_utc).getTime() - new Date(frames[i - 1].timestamp_utc).getTime());
            intervals.push(Math.max(1, dt));
          } else {
            intervals.push(35.0);
          }
        }

        function applySeededFrames() {
          if (!interFrameChart || !detectionsCountChart) {
            setTimeout(applySeededFrames, 80);
            return;
          }
          if (interFrameChart.data.labels.length <= 5) {
            interFrameChart.data.labels = labels;
            if (interFrameChart.data.datasets[0]) interFrameChart.data.datasets[0].data = intervals;
            interFrameChart.update('none');
            const lastInterval = intervals[intervals.length - 1];
            const lblInter = document.getElementById('lbl-inter-frame');
            if (lblInter && lastInterval !== undefined) lblInter.textContent = `${lastInterval.toFixed(1)} ms`;
          }

          if (detectionsCountChart.data.labels.length <= 5) {
            detectionsCountChart.data.labels = labels;
            if (detectionsCountChart.data.datasets[0]) detectionsCountChart.data.datasets[0].data = detCounts;
            detectionsCountChart.update('none');
            const lastCount = detCounts[detCounts.length - 1];
            const lblDet = document.getElementById('lbl-detections-per-frame');
            if (lblDet && lastCount !== undefined) lblDet.textContent = `${lastCount} object${lastCount === 1 ? '' : 's'}`;
          }
        }
        applySeededFrames();
      }
    }

    if (resDets.ok) {
      const dets = await resDets.json();
        dets.forEach(d => {
          if (typeof d.confidence === 'number' && !isNaN(d.confidence)) {
            let idx = Math.floor(d.confidence * 10);
            if (idx >= 10) idx = 9;
            if (idx < 0) idx = 0;
            sessionConfBins[idx]++;
            sessionConfTotal++;
            sessionConfSum += d.confidence;
          }
        });
        updateConfidenceHistogramUI();
    }
  } catch (err) {
    console.debug('[INFERENCE] Note on seeding inference history:', err);
  }
}

function onAppInit() {
  checkInitialReadiness();
  loadAvailableBackends();
  loadDiscoveredSources();
  initDetectionDurationSlider();
  initWorkloadTrajectoryChart();
  connectWebSocket();
  seedCpuFreqHistory();
  seedVoltageHistory();
  seedProcFootprintHistory();
  seedDiskHistory();
  seedInferenceAndDetectionHistory();
  fetch('/api/v1/workload/status')
    .then(r => r.json())
    .then(st => {
      if (st) updateWorkloadUI(st);
      updateMasterWorkloadButton();
    })
    .catch(err => {
      console.debug('[WORKLOAD] Initial status check:', err);
      updateMasterWorkloadButton();
    });
}

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', onAppInit);
} else {
  onAppInit();
}

/* ==========================================================================
   CPU vs Hailo-8L NPU Benchmark Coordination Suite
   (Plots overlaid directly on the 12 Live Telemetry Waveforms)
   ========================================================================== */

let benchmarkData = {
  hailo: [],
  cpu: []
};

let benchmarkConfList = {
  hailo: [],
  cpu: []
};

isBenchmarkRunning = false;
let isBenchmarkCancelled = false;
let currentBenchmarkPhase = null; // 'hailo' | 'cpu' | null
let benchmarkPhaseStartTime = null;
let benchmarkPhaseTargetSec = 30;
let benchmarkTimerHandle = null;
let waveformViewMode = 'live'; // 'live' | 'benchmark'

function benchmarkSleep(ms) {
  return new Promise((resolve) => {
    const start = Date.now();
    const interval = setInterval(() => {
      if (isBenchmarkCancelled || (Date.now() - start >= ms)) {
        clearInterval(interval);
        resolve(!isBenchmarkCancelled);
      }
    }, 100);
  });
}

function stopBenchmarkOperations(reason = 'Inference Stopped') {
  if (!isBenchmarkRunning && !currentBenchmarkPhase) return;
  console.log(`[BENCHMARK] Aborting benchmark operations: ${reason}`);
  isBenchmarkCancelled = true;
  if (benchmarkTimerHandle) {
    clearInterval(benchmarkTimerHandle);
    benchmarkTimerHandle = null;
  }
  isBenchmarkRunning = false;
  currentBenchmarkPhase = null;

  // Re-enable benchmark buttons
  const btnAuto = document.getElementById('btn-run-auto-benchmark');
  const btnAutoWb = document.getElementById('btn-run-auto-waveform-bench');
  if (btnAuto) btnAuto.disabled = false;
  if (btnAutoWb) btnAutoWb.disabled = false;

  // Update progress banners with cancellation notice
  const statusMsg = document.getElementById('benchmark-status-msg');
  const wbBanner = document.getElementById('wb-progress-banner');
  const statusText = document.getElementById('benchmark-status-text');
  const wbText = document.getElementById('wb-progress-text');
  const statusPill = document.getElementById('benchmark-countdown-pill');
  const wbPill = document.getElementById('wb-progress-pill');

  if (statusText) statusText.textContent = `Benchmark Halted: ${reason}`;
  if (wbText) wbText.textContent = `Benchmark Halted: ${reason}`;
  if (statusPill) statusPill.textContent = 'Stopped ⏹';
  if (wbPill) wbPill.textContent = 'Stopped ⏹';

  setTimeout(() => {
    if (statusMsg) statusMsg.style.display = 'none';
    if (wbBanner) wbBanner.style.display = 'none';
  }, 2200);

  updateBenchmarkStepperUI();
  updateMasterWorkloadButton();
}

async function cleanupCancelledBenchmark() {
  isBenchmarkRunning = false;
  currentBenchmarkPhase = null;
  try {
    await fetch('/api/v1/inference/backend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backend: 'hailo' })
    });
    if (typeof loadAvailableBackends === 'function') {
      await loadAvailableBackends();
    }
  } catch (e) {
    console.warn('[BENCHMARK] Error restoring backend after cancel:', e);
  }
}

function setWaveformViewMode(mode) {
  waveformViewMode = mode;
  const btnLive = document.getElementById('btn-view-live');
  const btnBench = document.getElementById('btn-view-benchmark');

  if (mode === 'benchmark') {
    btnLive?.classList.remove('active');
    btnBench?.classList.add('active');

    const hLen = benchmarkData.hailo ? benchmarkData.hailo.length : 0;
    const cLen = benchmarkData.cpu ? benchmarkData.cpu.length : 0;
    if (hLen > 0 || cLen > 0) {
      if (typeof renderDualBenchmarkOnLiveWaveforms === 'function') {
        renderDualBenchmarkOnLiveWaveforms(benchmarkData.hailo, benchmarkData.cpu, benchmarkConfList.hailo, benchmarkConfList.cpu);
      }
    } else {
      alert('No benchmark data buffered yet. Click "Run Automated Dual Benchmark" or record Hailo-8L and CPU steps to generate comparison curves.');
    }
  } else {
    btnLive?.classList.add('active');
    btnBench?.classList.remove('active');
    if (typeof restoreLiveWaveforms === 'function') {
      restoreLiveWaveforms();
    }
  }
}

function openBenchmarkModal() {
  const modal = document.getElementById('modal-benchmark-suite');
  if (modal) modal.style.display = 'flex';
  if (typeof initBenchmarkCharts === 'function') {
    initBenchmarkCharts();
  }
  // If we already have buffered data, render overlay immediately
  if ((benchmarkData.hailo && benchmarkData.hailo.length > 0) || (benchmarkData.cpu && benchmarkData.cpu.length > 0)) {
    if (typeof renderBenchmarkOverlay === 'function') {
      renderBenchmarkOverlay(benchmarkData.hailo, benchmarkData.cpu);
    }
  }
  updateBenchmarkStepperUI();
}

function closeBenchmarkModal() {
  const modal = document.getElementById('modal-benchmark-suite');
  if (modal) modal.style.display = 'none';
}

function handleBenchmarkModalBackdrop(event) {
  if (event.target && event.target.id === 'modal-benchmark-suite') {
    closeBenchmarkModal();
  }
}

function updateBenchmarkStepperUI() {
  // Modal Stepper
  const stepHailo = document.getElementById('step-hailo');
  const stepStateHailo = document.getElementById('step-state-hailo');
  const stepHold = document.getElementById('step-hold');
  const stepStateHold = document.getElementById('step-state-hold');
  const stepCpu = document.getElementById('step-cpu');
  const stepStateCpu = document.getElementById('step-state-cpu');
  const stepOverlay = document.getElementById('step-overlay');
  const stepStateOverlay = document.getElementById('step-state-overlay');

  // Waveforms Panel Stepper
  const wbStepHailo = document.getElementById('wb-step-hailo');
  const wbStateHailo = document.getElementById('wb-state-hailo');
  const wbStepHold = document.getElementById('wb-step-hold');
  const wbStateHold = document.getElementById('wb-state-hold');
  const wbStepCpu = document.getElementById('wb-step-cpu');
  const wbStateCpu = document.getElementById('wb-state-cpu');
  const wbStepOverlay = document.getElementById('wb-step-overlay');
  const wbStateOverlay = document.getElementById('wb-state-overlay');

  const hLen = benchmarkData.hailo ? benchmarkData.hailo.length : 0;
  const cLen = benchmarkData.cpu ? benchmarkData.cpu.length : 0;

  // 1. Hailo state
  if (currentBenchmarkPhase === 'hailo') {
    stepHailo?.classList.add('active');
    stepHailo?.classList.remove('completed');
    wbStepHailo?.classList.add('active');
    wbStepHailo?.classList.remove('completed');
    if (stepStateHailo) stepStateHailo.textContent = `Running (${hLen}s)...`;
    if (wbStateHailo) wbStateHailo.textContent = `Running (${hLen}s)...`;
  } else if (hLen > 0) {
    stepHailo?.classList.remove('active');
    stepHailo?.classList.add('completed');
    wbStepHailo?.classList.remove('active');
    wbStepHailo?.classList.add('completed');
    if (stepStateHailo) stepStateHailo.textContent = `${hLen}s Done ✅`;
    if (wbStateHailo) wbStateHailo.textContent = `${hLen}s Done ✅`;
  } else {
    stepHailo?.classList.remove('active', 'completed');
    wbStepHailo?.classList.remove('active', 'completed');
    if (stepStateHailo) stepStateHailo.textContent = 'Ready';
    if (wbStateHailo) wbStateHailo.textContent = 'Ready';
  }

  // 2. Hold buffer state
  if (hLen > 0) {
    stepHold?.classList.add('completed');
    wbStepHold?.classList.add('completed');
    if (stepStateHold) stepStateHold.textContent = `${hLen} pts Held 📌`;
    if (wbStateHold) wbStateHold.textContent = `${hLen} pts Held 📌`;
  } else {
    stepHold?.classList.remove('completed');
    wbStepHold?.classList.remove('completed');
    if (stepStateHold) stepStateHold.textContent = 'Empty';
    if (wbStateHold) wbStateHold.textContent = 'Empty';
  }

  // 3. CPU state
  if (currentBenchmarkPhase === 'cpu') {
    stepCpu?.classList.add('active');
    stepCpu?.classList.remove('completed');
    wbStepCpu?.classList.add('active');
    wbStepCpu?.classList.remove('completed');
    if (stepStateCpu) stepStateCpu.textContent = `Running (${cLen}s)...`;
    if (wbStateCpu) wbStateCpu.textContent = `Running (${cLen}s)...`;
  } else if (cLen > 0) {
    stepCpu?.classList.remove('active');
    stepCpu?.classList.add('completed');
    wbStepCpu?.classList.remove('active');
    wbStepCpu?.classList.add('completed');
    if (stepStateCpu) stepStateCpu.textContent = `${cLen}s Done ✅`;
    if (wbStateCpu) wbStateCpu.textContent = `${cLen}s Done ✅`;
  } else {
    stepCpu?.classList.remove('active', 'completed');
    wbStepCpu?.classList.remove('active', 'completed');
    if (stepStateCpu) stepStateCpu.textContent = 'Ready';
    if (wbStateCpu) wbStateCpu.textContent = 'Ready';
  }

  // 4. Overlay state
  if (hLen > 0 && cLen > 0) {
    stepOverlay?.classList.add('completed');
    wbStepOverlay?.classList.add('completed');
    if (stepStateOverlay) stepStateOverlay.textContent = 'Overlaid 📈';
    if (wbStateOverlay) wbStateOverlay.textContent = 'Overlaid on 15 Waveforms 📈';
  } else {
    stepOverlay?.classList.remove('completed');
    wbStepOverlay?.classList.remove('completed');
    if (stepStateOverlay) stepStateOverlay.textContent = 'Awaiting Data';
    if (wbStateOverlay) wbStateOverlay.textContent = 'Awaiting Data';
  }
}

function clearBenchmarkData() {
  benchmarkData = { hailo: [], cpu: [] };
  benchmarkConfList = { hailo: [], cpu: [] };
  isBenchmarkRunning = false;
  currentBenchmarkPhase = null;
  benchmarkPhaseStartTime = null;
  if (benchmarkTimerHandle) {
    clearInterval(benchmarkTimerHandle);
    benchmarkTimerHandle = null;
  }
  const statusMsg = document.getElementById('benchmark-status-msg');
  if (statusMsg) statusMsg.style.display = 'none';
  const wbBanner = document.getElementById('wb-progress-banner');
  if (wbBanner) wbBanner.style.display = 'none';

  updateBenchmarkStepperUI();
  if (typeof renderBenchmarkOverlay === 'function') {
    renderBenchmarkOverlay([], []);
  }
  waveformViewMode = 'live';
  const btnLive = document.getElementById('btn-view-live');
  const btnBench = document.getElementById('btn-view-benchmark');
  btnLive?.classList.add('active');
  btnBench?.classList.remove('active');

  if (typeof resetAllCharts === 'function') {
    resetAllCharts();
  }
  console.log('[BENCHMARK] Buffer cleared');
}

function clearWaveformBenchmark() {
  clearBenchmarkData();
}

function manualHoldBenchmarkData() {
  const hLen = benchmarkData.hailo ? benchmarkData.hailo.length : 0;
  if (hLen === 0) {
    alert('Please record Hailo-8L baseline data first before holding.');
    return;
  }
  updateBenchmarkStepperUI();
  alert(`Hailo-8L Baseline data held successfully (${hLen} relative-time seconds buffered). Now switch and record CPU inference!`);
}

function manualWaveformHoldHailo() {
  manualHoldBenchmarkData();
}

function manualWaveformBenchmarkPhase(phase) {
  manualRecordBenchmarkPhase(phase);
}

function getBenchmarkTargetDuration() {
  if (typeof detectionDurationSec === 'number' && detectionDurationSec > 0) {
    return detectionDurationSec;
  }
  const saved = parseInt(localStorage.getItem('evm_detection_duration_sec'), 10);
  if (saved > 0) return saved;
  return 30; // Fallback duration if detection timer is set to Continuous (0)
}

function startAutomatedWaveformBenchmark() {
  startAutomatedBenchmark();
}

async function startAutomatedBenchmark() {
  if (isBenchmarkRunning) return;

  const btnHailo = document.getElementById('btn-backend-hailo');
  if (btnHailo && btnHailo.disabled) {
    alert('Automated Dual Benchmark requires the Hailo-8L NPU accelerator, which is currently unavailable on this runtime environment. For Hailo-8L hardware acceleration, please run Native Deployment on the Raspberry Pi 5.');
    return;
  }

  const durSec = getBenchmarkTargetDuration();

  // Cancel any manual detection countdown timer so it does not stop inference prematurely
  clearDetectionCountdown();
  isBenchmarkCancelled = false;

  // Reset view mode explicitly to live waveforms
  waveformViewMode = 'live';
  const btnLive = document.getElementById('btn-view-live');
  const btnBench = document.getElementById('btn-view-benchmark');
  btnLive?.classList.add('active');
  btnBench?.classList.remove('active');

  // Like "Start Inference", unpause waveforms and perform a full reset before continuation
  setWaveformsPaused(false, 'Benchmark Started');
  await resetTelemetryAndDetectionData();

  clearBenchmarkData();
  activeWorkloadMode = 'benchmark';
  isBenchmarkRunning = true;
  isBenchmarkCancelled = false;
  benchmarkPhaseTargetSec = durSec;
  updateMasterWorkloadButton();

  const btnAuto = document.getElementById('btn-run-auto-benchmark');
  const btnAutoWb = document.getElementById('btn-run-auto-waveform-bench');
  if (btnAuto) btnAuto.disabled = true;
  if (btnAutoWb) btnAutoWb.disabled = true;

  // Ensure waveforms benchmark panel is visible
  const benchPanel = document.getElementById('benchmark-waveforms-panel');
  if (benchPanel) {
    benchPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Modal Banner Elements
  const statusMsg = document.getElementById('benchmark-status-msg');
  const statusText = document.getElementById('benchmark-status-text');
  const statusPill = document.getElementById('benchmark-countdown-pill');
  if (statusMsg) statusMsg.style.display = 'flex';

  // Waveforms Banner Elements
  const wbBanner = document.getElementById('wb-progress-banner');
  const wbText = document.getElementById('wb-progress-text');
  const wbPill = document.getElementById('wb-progress-pill');
  if (wbBanner) wbBanner.style.display = 'flex';

  const setProgressMsg = (msg, pill) => {
    if (statusText) statusText.textContent = msg;
    if (statusPill) statusPill.textContent = pill;
    if (wbText) wbText.textContent = msg;
    if (wbPill) wbPill.textContent = pill;
  };

  const runPhaseTimer = (phaseName, targetSec) => {
    return new Promise(resolve => {
      benchmarkTimerHandle = setInterval(() => {
        if (isBenchmarkCancelled) {
          clearInterval(benchmarkTimerHandle);
          benchmarkTimerHandle = null;
          resolve(false);
          return;
        }
        const elapsed = Math.floor(Date.now() / 1000) - benchmarkPhaseStartTime;
        const remaining = Math.max(0, targetSec - elapsed);
        setProgressMsg(`${phaseName}... (${elapsed}s / ${targetSec}s)`, `${remaining}s remaining`);

        if (elapsed >= targetSec) {
          clearInterval(benchmarkTimerHandle);
          benchmarkTimerHandle = null;
          resolve(true);
        }
      }, 500);
    });
  };

  try {
    // -----------------------------------------------------------------------
    // PHASE 1: Hailo-8L NPU Run
    // -----------------------------------------------------------------------
    if (isBenchmarkCancelled) { await cleanupCancelledBenchmark(); return; }
    setProgressMsg('Phase 1/2: Initialising Hailo-8L NPU Accelerator...', 'Initialising');
    await fetch('/api/v1/inference/backend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backend: 'hailo' })
    });
    if (isBenchmarkCancelled) { await cleanupCancelledBenchmark(); return; }
    await fetch('/api/v1/inference/start', { method: 'POST' });

    currentBenchmarkPhase = 'hailo';
    benchmarkData.hailo = [];
    benchmarkConfList.hailo = [];
    benchmarkPhaseStartTime = Math.floor(Date.now() / 1000);
    updateBenchmarkStepperUI();

    const phase1Ok = await runPhaseTimer('Phase 1/2: Recording Hailo-8L NPU Baseline', benchmarkPhaseTargetSec);
    if (!phase1Ok || isBenchmarkCancelled) {
      await cleanupCancelledBenchmark();
      return;
    }

    // Stop inference and hold Hailo-8L data
    await fetch('/api/v1/inference/stop', { method: 'POST' });
    currentBenchmarkPhase = null;
    updateBenchmarkStepperUI();
    console.log(`[BENCHMARK] Phase 1 complete: Held ${benchmarkData.hailo.length} Hailo-8L data points.`);

    if (isBenchmarkCancelled) { await cleanupCancelledBenchmark(); return; }

    // -----------------------------------------------------------------------
    // TRANSITION: Hold Hailo data & Switch to CPU Inference
    // -----------------------------------------------------------------------
    setProgressMsg('Transitioning: Holding Hailo-8L data & Switching backend to CPU (ONNX)...', 'Switching...');
    if (!await benchmarkSleep(1500) || isBenchmarkCancelled) {
      await cleanupCancelledBenchmark();
      return;
    }

    await fetch('/api/v1/inference/backend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backend: 'cpu' })
    });
    if (!await benchmarkSleep(1000) || isBenchmarkCancelled) {
      await cleanupCancelledBenchmark();
      return;
    }
    await fetch('/api/v1/inference/start', { method: 'POST' });

    // -----------------------------------------------------------------------
    // PHASE 2: CPU Inference Run
    // -----------------------------------------------------------------------
    currentBenchmarkPhase = 'cpu';
    benchmarkData.cpu = [];
    benchmarkConfList.cpu = [];
    benchmarkPhaseStartTime = Math.floor(Date.now() / 1000);
    updateBenchmarkStepperUI();

    const phase2Ok = await runPhaseTimer('Phase 2/2: Recording CPU ONNX Inference', benchmarkPhaseTargetSec);
    if (!phase2Ok || isBenchmarkCancelled) {
      await cleanupCancelledBenchmark();
      return;
    }

    // Stop CPU inference
    await fetch('/api/v1/inference/stop', { method: 'POST' });
    currentBenchmarkPhase = null;
    updateBenchmarkStepperUI();
    console.log(`[BENCHMARK] Phase 2 complete: Collected ${benchmarkData.cpu.length} CPU data points.`);

    if (isBenchmarkCancelled) { await cleanupCancelledBenchmark(); return; }

    // -----------------------------------------------------------------------
    // OVERLAY: Render Relative-Time Overlays on the 15 Live Waveforms & Reset to Hailo default
    // -----------------------------------------------------------------------
    setProgressMsg('Benchmark Finished! Rendering relative-time comparison directly on the 15 waveforms below...', 'Complete ✅');

    // Switch backend back to Hailo-8L default
    await fetch('/api/v1/inference/backend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backend: 'hailo' })
    });
    if (typeof loadAvailableBackends === 'function') {
      await loadAvailableBackends();
    }

    // Set waveform mode to benchmark and render directly onto the 15 waveforms
    setWaveformViewMode('benchmark');
    if (typeof renderDualBenchmarkOnLiveWaveforms === 'function') {
      renderDualBenchmarkOnLiveWaveforms(benchmarkData.hailo, benchmarkData.cpu, benchmarkConfList.hailo, benchmarkConfList.cpu);
    }
    updateBenchmarkStepperUI();

    setTimeout(() => {
      if (statusMsg) statusMsg.style.display = 'none';
      if (wbBanner) wbBanner.style.display = 'none';
    }, 4500);

  } catch (err) {
    console.error('[BENCHMARK] Error during automated benchmark execution:', err);
    if (!isBenchmarkCancelled) {
      alert(`Benchmark execution error: ${err.message}`);
    }
  } finally {
    isBenchmarkRunning = false;
    currentBenchmarkPhase = null;
    if (btnAuto) btnAuto.disabled = false;
    if (btnAutoWb) btnAutoWb.disabled = false;
    updateMasterWorkloadButton();
  }
}

async function manualRecordBenchmarkPhase(backend) {
  if (isBenchmarkRunning) return;
  const durSec = getBenchmarkTargetDuration();

  if (backend === 'hailo') {
    setWaveformsPaused(false, 'Benchmark Started');
    await resetTelemetryAndDetectionData();
  }

  isBenchmarkRunning = true;
  currentBenchmarkPhase = backend;
  benchmarkPhaseTargetSec = durSec;
  benchmarkData[backend] = [];
  benchmarkConfList[backend] = [];

  const statusMsg = document.getElementById('benchmark-status-msg');
  const statusText = document.getElementById('benchmark-status-text');
  const statusPill = document.getElementById('benchmark-countdown-pill');
  if (statusMsg) statusMsg.style.display = 'flex';

  const wbBanner = document.getElementById('wb-progress-banner');
  const wbText = document.getElementById('wb-progress-text');
  const wbPill = document.getElementById('wb-progress-pill');
  if (wbBanner) wbBanner.style.display = 'flex';

  const setProgressMsg = (msg, pill) => {
    if (statusText) statusText.textContent = msg;
    if (statusPill) statusPill.textContent = pill;
    if (wbText) wbText.textContent = msg;
    if (wbPill) wbPill.textContent = pill;
  };

  try {
    setProgressMsg(`Manual Recording: Setting backend to ${backend.toUpperCase()}...`, 'Configuring');
    await fetch('/api/v1/inference/backend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backend })
    });
    await new Promise(r => setTimeout(r, 800));
    await fetch('/api/v1/inference/start', { method: 'POST' });

    benchmarkPhaseStartTime = Math.floor(Date.now() / 1000);
    updateBenchmarkStepperUI();

    await new Promise(resolve => {
      benchmarkTimerHandle = setInterval(() => {
        if (isBenchmarkCancelled) {
          clearInterval(benchmarkTimerHandle);
          benchmarkTimerHandle = null;
          resolve();
          return;
        }
        const elapsed = Math.floor(Date.now() / 1000) - benchmarkPhaseStartTime;
        const remaining = Math.max(0, benchmarkPhaseTargetSec - elapsed);
        setProgressMsg(`Recording ${backend.toUpperCase()} Inference (${elapsed}s / ${benchmarkPhaseTargetSec}s)...`, `${remaining}s remaining`);

        if (elapsed >= benchmarkPhaseTargetSec) {
          clearInterval(benchmarkTimerHandle);
          benchmarkTimerHandle = null;
          resolve();
        }
      }, 500);
    });

    await fetch('/api/v1/inference/stop', { method: 'POST' });
    currentBenchmarkPhase = null;
    updateBenchmarkStepperUI();

    if (isBenchmarkCancelled) {
      await cleanupCancelledBenchmark();
      return;
    }

    if (benchmarkData.hailo.length > 0 && benchmarkData.cpu.length > 0) {
      setWaveformViewMode('benchmark');
      if (typeof renderDualBenchmarkOnLiveWaveforms === 'function') {
        renderDualBenchmarkOnLiveWaveforms(benchmarkData.hailo, benchmarkData.cpu, benchmarkConfList.hailo, benchmarkConfList.cpu);
      }
    }

    setProgressMsg(`${backend.toUpperCase()} run finished (${benchmarkData[backend].length}s buffered).`, 'Done ✅');
    setTimeout(() => {
      if (statusMsg) statusMsg.style.display = 'none';
      if (wbBanner) wbBanner.style.display = 'none';
    }, 3500);
  } catch (err) {
    console.error(`[BENCHMARK] Manual record error for ${backend}:`, err);
    alert(`Error: ${err.message}`);
  } finally {
    isBenchmarkRunning = false;
    currentBenchmarkPhase = null;
  }
}

/* ==========================================================================
   Phase 4: Hailo-8L Workload Suite & Thermal Stress Interactive Controllers
   ========================================================================== */

selectedWorkloadType = selectedWorkloadType || 'A';
let workloadTrajectoryChart = null;
let lastWorkloadSessionId = null;
let isWorkloadModalOpen = false;

function scrollToWorkloadSuite() {
  const el = document.getElementById('section-workload-suite');
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.classList.add('suite-focus-highlight');
    setTimeout(() => el.classList.remove('suite-focus-highlight'), 1800);
  }
}
window.scrollToWorkloadSuite = scrollToWorkloadSuite;
window.openWorkloadModal = scrollToWorkloadSuite;

function closeWorkloadModal() {
  // Modal deprecated, workload suite is embedded directly on the main page
}
window.closeWorkloadModal = closeWorkloadModal;

function selectWorkloadCard(type) {
  selectedWorkloadType = type;
  document.querySelectorAll('.workload-option-card').forEach(c => c.classList.remove('active'));
  const targetCard = document.getElementById(`card-workload-${type}`);
  if (targetCard) targetCard.classList.add('active');

  const wrapperTargetTemp = document.getElementById('wrapper-param-target-temp');
  const wrapperStreams = document.getElementById('wrapper-param-streams');

  if (wrapperTargetTemp) {
    wrapperTargetTemp.style.display = (type === 'C') ? 'block' : 'none';
  }
  if (wrapperStreams) {
    wrapperStreams.style.display = (type === 'B' || type === 'C' || type === 'D') ? 'block' : 'none';
  }

  activeWorkloadMode = 'workload_suite';
  updateMasterWorkloadButton();
}
window.selectWorkloadCard = selectWorkloadCard;

function initWorkloadTrajectoryChart() {
  const ctx = document.getElementById('chart-workload-trajectory');
  if (!ctx || typeof Chart === 'undefined') return;
  if (workloadTrajectoryChart) return;

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    elements: {
      point: { radius: 0 },
      line: { tension: 0.2, borderWidth: 2 }
    },
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: '#475569',
          font: { family: 'Inter', size: 10, weight: '500' },
          boxWidth: 8
        }
      }
    },
    scales: {
      x: {
        grid: { color: 'rgba(0, 0, 0, 0.04)' },
        ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 9 }, maxRotation: 0 }
      },
      y: {
        type: 'linear',
        position: 'left',
        min: 40,
        max: 110,
        grid: { color: 'rgba(0, 0, 0, 0.05)' },
        ticks: {
          color: '#ef4444',
          font: { family: 'JetBrains Mono', size: 9 },
          callback: (v) => `${v}°C`
        }
      },
      y1: {
        type: 'linear',
        position: 'right',
        min: 150,
        max: 450,
        grid: { display: false },
        ticks: {
          color: '#6366f1',
          font: { family: 'JetBrains Mono', size: 9 },
          callback: (v) => `${v}MHz`
        }
      }
    }
  };

  workloadTrajectoryChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Silicon Tj (°C)',
          data: [],
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239, 68, 68, 0.08)',
          yAxisID: 'y',
          fill: false
        },
        {
          label: 'Diode TS0 (°C)',
          data: [],
          borderColor: '#f59e0b',
          borderDash: [3, 2],
          yAxisID: 'y',
          fill: false
        },
        {
          label: 'Diode TS1 (°C)',
          data: [],
          borderColor: '#ea580c',
          borderDash: [3, 2],
          yAxisID: 'y',
          fill: false
        },
        {
          label: 'Clock Frequency (MHz)',
          data: [],
          borderColor: '#6366f1',
          backgroundColor: 'rgba(99, 102, 241, 0.05)',
          yAxisID: 'y1',
          fill: false
        }
      ]
    },
    options: chartOptions
  });
}

function updateWorkloadUI(workload) {
  if (!workload) return;

  const isActive = !!workload.active;
  isWorkloadSuiteActive = isActive;
  if (workload.session_id) {
    lastWorkloadSessionId = workload.session_id;
  }

  // 1. Update Top Active Banner
  const banner = document.getElementById('workload-active-banner');
  if (banner) {
    if (isActive) {
      banner.style.display = 'flex';
      const titleEl = document.getElementById('banner-workload-title');
      if (titleEl) titleEl.textContent = workload.workload_title || `Workload ${workload.workload_type}`;

      const stateBadge = document.getElementById('banner-workload-state');
      if (stateBadge) {
        stateBadge.textContent = (workload.state || 'RUNNING').toUpperCase();
        stateBadge.className = workload.state === 'running' ? 'badge-tag-amber' : 'badge-tag-cyan';
      }

      const tjEl = document.getElementById('banner-tj');
      if (tjEl) tjEl.textContent = workload.current_tj_c !== null ? Number(workload.current_tj_c).toFixed(1) : '--';

      const ts0El = document.getElementById('banner-ts0');
      if (ts0El) ts0El.textContent = workload.ts0_c !== null ? Number(workload.ts0_c).toFixed(0) : '--';

      const ts1El = document.getElementById('banner-ts1');
      if (ts1El) ts1El.textContent = workload.ts1_c !== null ? Number(workload.ts1_c).toFixed(0) : '--';

      const clkEl = document.getElementById('banner-clock');
      if (clkEl) clkEl.textContent = workload.clock_frequency_mhz !== null ? Number(workload.clock_frequency_mhz).toFixed(0) : '--';

      const fpsEl = document.getElementById('banner-fps');
      if (fpsEl) fpsEl.textContent = workload.current_fps !== null ? Number(workload.current_fps).toFixed(1) : '--';

      const elEl = document.getElementById('banner-elapsed');
      if (elEl) elEl.textContent = Number(workload.elapsed_seconds || 0).toFixed(1);

      const durEl = document.getElementById('banner-duration');
      if (durEl) durEl.textContent = Number(workload.duration_seconds || 60).toFixed(0);

      const progBar = document.getElementById('banner-progress-bar');
      if (progBar) progBar.style.width = `${Math.min(100, workload.progress_percent || 0)}%`;
    } else {
      banner.style.display = 'none';
    }
  }

  // Update Hardware Thermals card from active workload if telemetry is streaming
  if (workload.current_tj_c !== null && workload.current_tj_c !== undefined) {
    const elTj = document.getElementById('val-hailo-tj-temp');
    if (elTj) {
      elTj.textContent = `${Number(workload.current_tj_c).toFixed(1)}°C`;
      if (workload.current_tj_c >= 100.0) elTj.className = 'metric-val red';
      else if (workload.current_tj_c >= 85.0) elTj.className = 'metric-val amber';
      else elTj.className = 'metric-val green';
    }
    const barTj = document.getElementById('bar-hailo-tj-temp');
    if (barTj) {
      const pct = Math.max(0, Math.min(100, (workload.current_tj_c / 105.0) * 100.0));
      barTj.style.width = `${pct}%`;
      if (workload.current_tj_c >= 100.0) barTj.style.background = 'var(--accent-rose, #ef4444)';
      else if (workload.current_tj_c >= 85.0) barTj.style.background = 'var(--accent-amber, #f59e0b)';
      else barTj.style.background = 'var(--accent-emerald, #10b981)';
    }
  }
  if (workload.ts0_c !== null && workload.ts1_c !== null && workload.ts0_c !== undefined) {
    const elDie = document.getElementById('val-hailo-die-temp');
    if (elDie) elDie.textContent = `${Number(workload.ts0_c).toFixed(0)} / ${Number(workload.ts1_c).toFixed(0)} °C`;
  }

  // 2. Update Modal Controls and Metrics HUD if open
  const btnStart = document.getElementById('btn-workload-start');
  const btnAbort = document.getElementById('btn-workload-abort');
  if (btnStart) btnStart.disabled = isActive;
  if (btnAbort) btnAbort.disabled = !isActive;

  const stateBadgeHud = document.getElementById('hud-workload-state-badge');
  if (stateBadgeHud) {
    const stStr = (workload.state || 'IDLE').toUpperCase();
    stateBadgeHud.textContent = stStr;
    if (stStr === 'RUNNING') stateBadgeHud.className = 'badge-tag-amber';
    else if (stStr === 'COMPLETED') stateBadgeHud.className = 'badge-tag-cyan';
    else if (stStr === 'ABORTED') stateBadgeHud.className = 'badge-tag-red';
    else stateBadgeHud.className = 'badge-tag-gray';
  }

  const progTxt = document.getElementById('hud-workload-prog-text');
  if (progTxt) progTxt.textContent = `${Number(workload.progress_percent || 0).toFixed(1)}%`;

  const timeTxt = document.getElementById('hud-workload-time-text');
  if (timeTxt) {
    timeTxt.textContent = `${Number(workload.elapsed_seconds || 0).toFixed(1)}s / ${Number(workload.duration_seconds || 60).toFixed(0)}s`;
  }

  const progBarHud = document.getElementById('hud-workload-progress-bar');
  if (progBarHud) progBarHud.style.width = `${Math.min(100, workload.progress_percent || 0)}%`;

  const hudTj = document.getElementById('hud-workload-tj');
  if (hudTj) {
    const val = workload.current_tj_c;
    hudTj.textContent = val !== null ? Number(val).toFixed(1) : '--';
    if (val !== null && val >= 100.0) hudTj.style.color = 'var(--accent-rose, #ef4444)';
    else if (val !== null && val >= 85.0) hudTj.style.color = 'var(--accent-amber, #f59e0b)';
    else hudTj.style.color = 'var(--text-primary, #0f172a)';
  }

  const hudTs = document.getElementById('hud-workload-ts');
  if (hudTs) {
    const ts0 = workload.ts0_c !== null ? Number(workload.ts0_c).toFixed(1) : '--';
    const ts1 = workload.ts1_c !== null ? Number(workload.ts1_c).toFixed(1) : '--';
    hudTs.textContent = `${ts0} / ${ts1}`;
  }

  const hudClk = document.getElementById('hud-workload-clock');
  if (hudClk) {
    hudClk.textContent = workload.clock_frequency_mhz !== null ? Number(workload.clock_frequency_mhz).toFixed(0) : '--';
  }

  const hudTh = document.getElementById('hud-workload-throttling');
  if (hudTh) {
    if (workload.throttling_active) {
      hudTh.textContent = 'ACTIVE';
      hudTh.style.color = 'var(--accent-rose, #ef4444)';
    } else if (workload.throttling_level && workload.throttling_level > 0) {
      hudTh.textContent = `Level ${workload.throttling_level}`;
      hudTh.style.color = 'var(--accent-amber, #f59e0b)';
    } else {
      hudTh.textContent = 'Nominal';
      hudTh.style.color = 'var(--accent-emerald, #16a34a)';
    }
  }

  const hudFps = document.getElementById('hud-workload-fps');
  if (hudFps) {
    hudFps.textContent = workload.current_fps !== null ? Number(workload.current_fps).toFixed(1) : '--';
  }

  const hudMeanFps = document.getElementById('hud-workload-fps-mean');
  if (hudMeanFps) {
    hudMeanFps.textContent = workload.mean_fps !== null ? Number(workload.mean_fps).toFixed(1) : '--';
  }

  // 3. Update Trajectory Real-Time Chart
  if (workloadTrajectoryChart && isActive && workload.current_tj_c !== null) {
    const nowTime = new Date().toLocaleTimeString();
    const labels = workloadTrajectoryChart.data.labels;
    labels.push(nowTime);

    workloadTrajectoryChart.data.datasets[0].data.push(workload.current_tj_c);
    workloadTrajectoryChart.data.datasets[1].data.push(workload.ts0_c);
    workloadTrajectoryChart.data.datasets[2].data.push(workload.ts1_c);
    workloadTrajectoryChart.data.datasets[3].data.push(workload.clock_frequency_mhz);

    if (labels.length > 180) {
      labels.shift();
      workloadTrajectoryChart.data.datasets.forEach(d => d.data.shift());
    }
    workloadTrajectoryChart.update('none');
  }

  // 4. Update Result Callout Box when finished or aborted
  const resultBox = document.getElementById('workload-result-box');
  if (resultBox) {
    if (workload.state === 'completed' || workload.state === 'aborted') {
      resultBox.style.display = 'block';
      resultBox.className = `workload-result-box ${workload.state}`;
      const isAbort = workload.state === 'aborted';
      const icon = isAbort ? '⚠️' : '✅';
      const summary = workload.session_summary || {};
      const evalInfo = summary.workload_evaluation || {};

      let html = `<strong>${icon} Workload Run ${workload.state.toUpperCase()}</strong> &bull; `;
      html += `Peak Tj: <strong>${workload.peak_tj_c !== null ? Number(workload.peak_tj_c).toFixed(1) : 'N/A'}°C</strong> | `;
      html += `Mean FPS: <strong>${workload.mean_fps !== null ? Number(workload.mean_fps).toFixed(1) : 'N/A'}</strong> | `;
      html += `Samples: <strong>${workload.samples_count || 0}</strong><br>`;

      if (isAbort && workload.abort_reason) {
        html += `<span style="color: #b91c1c; font-weight: 600;">Abort Notice: ${workload.abort_reason}</span><br>`;
      }
      if (evalInfo.throttling_observed) {
        html += `<span style="color: #b45309;">Governor Throttling was engaged during run. </span>`;
      }
      if (evalInfo.hysteresis_recovered) {
        html += `<span style="color: #15803d; font-weight: 600;">Silicon temperature successfully returned below 99.0°C hysteresis threshold.</span>`;
      }
      resultBox.innerHTML = html;
    } else if (isActive) {
      resultBox.style.display = 'none';
    }
  }
}

async function startWorkloadFromUI() {
  activeWorkloadMode = 'workload_suite';
  // If regular continuous inference is active, halt it so workload suite has direct exclusive hardware access
  if (isInferenceRunning) {
    try {
      await fetch('/api/v1/inference/stop', { method: 'POST' });
      isInferenceRunning = false;
    } catch (e) {
      console.warn('Failed to stop background inference prior to workload run:', e);
    }
  }

  isWorkloadSuiteActive = true;
  updateMasterWorkloadButton();

  const durVal = parseFloat(document.getElementById('input-workload-duration')?.value || '60');
  const targetTempVal = parseFloat(document.getElementById('input-workload-target-temp')?.value || '100');
  const streamsVal = parseInt(document.getElementById('select-workload-streams')?.value || '4', 10);
  const simulateVal = !!document.getElementById('chk-workload-simulate')?.checked;

  const payload = {
    workload_type: selectedWorkloadType,
    duration_seconds: durVal,
    target_temp_c: targetTempVal,
    safety_temp_limit_c: 102.0,
    simulate: simulateVal,
    stream_count: streamsVal,
    buffer_size: 120
  };

  const btnStart = document.getElementById('btn-workload-start');
  if (btnStart) btnStart.disabled = true;

  // Clear previous trajectory chart data for fresh run
  if (workloadTrajectoryChart) {
    workloadTrajectoryChart.data.labels = [];
    workloadTrajectoryChart.data.datasets.forEach(d => { d.data = []; });
    workloadTrajectoryChart.update();
  }

  const resultBox = document.getElementById('workload-result-box');
  if (resultBox) resultBox.style.display = 'none';

  try {
    const res = await fetch('/api/v1/workload/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `Server error HTTP ${res.status}`);
    }
    const data = await res.json();
    lastWorkloadSessionId = data.session_id;
    updateWorkloadUI(data);
  } catch (err) {
    console.error('[WORKLOAD] Start failed:', err);
    alert(`Could not start workload: ${err.message}`);
    isWorkloadSuiteActive = false;
    updateMasterWorkloadButton();
    if (btnStart) btnStart.disabled = false;
  }
}
window.startWorkloadFromUI = startWorkloadFromUI;

async function emergencyAbortWorkload() {
  try {
    const res = await fetch('/api/v1/workload/stop?reason=Web+Dashboard+Safety+Abort', { method: 'POST' });
    const data = await res.json();
    console.log('[WORKLOAD] Abort response:', data);
    isWorkloadSuiteActive = false;
    updateWorkloadUI(data.summary || { active: false, state: 'aborted' });
    updateMasterWorkloadButton();
  } catch (err) {
    console.error('[WORKLOAD] Abort request failed:', err);
    alert(`Failed to abort workload: ${err.message}`);
    isWorkloadSuiteActive = false;
    updateMasterWorkloadButton();
  }
}
window.emergencyAbortWorkload = emergencyAbortWorkload;

function exportWorkloadFromUI(fmt) {
  const sess = lastWorkloadSessionId || '';
  const url = `/api/v1/workload/export?format=${encodeURIComponent(fmt)}&session_id=${encodeURIComponent(sess)}`;
  window.open(url, '_blank');
}
window.exportWorkloadFromUI = exportWorkloadFromUI;

