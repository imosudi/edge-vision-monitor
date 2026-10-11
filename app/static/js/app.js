/**
 * Edge Vision Monitor - Live Dashboard Client & WebSocket Coordination
 */

let ws = null;
let reconnectTimer = null;
let currentSourceType = 'file';
let isInferenceRunning = true;
let isSwitchingBackend = false;

// Class colour palette matching backend
const CLASS_COLORS = [
  '#00f0ff', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444',
  '#3b82f6', '#ec4899', '#0ea5e9', '#22c55e', '#f97316'
];

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
  const { status, inference, detections, metrics } = data;

  // 1. Update Header & Badges
  isInferenceRunning = status.inference_running;
  const btnInf = document.getElementById('btn-inference-toggle');
  const txtInf = document.getElementById('text-inference');
  const icoInf = document.getElementById('icon-inference');
  if (isInferenceRunning) {
    btnInf.className = 'btn btn-danger';
    txtInf.textContent = 'Stop Inference';
    icoInf.textContent = '⏹';
  } else {
    btnInf.className = 'btn btn-primary';
    txtInf.textContent = 'Start Inference';
    icoInf.textContent = '▶';
  }

  document.getElementById('label-source').textContent = `Source: ${status.active_source}`;
  const badgeSource = document.getElementById('badge-source');
  badgeSource.className = 'badge active';

  // Synchronise backend buttons & labels
  const activeBackend = inference.active_backend || status.active_backend || 'hailo';
  if (!isSwitchingBackend) {
    const btnHailo = document.getElementById('btn-backend-hailo');
    const btnCpu = document.getElementById('btn-backend-cpu');
    if (btnHailo && btnCpu) {
      if (activeBackend === 'cpu') {
        btnHailo.classList.remove('active');
        btnCpu.classList.add('active');
      } else {
        btnHailo.classList.add('active');
        btnCpu.classList.remove('active');
      }
    }
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
  let cpuUtil = null;
  let memUtil = null;

  if (metrics) {
    // Find CPU Temp
    for (const [k, v] of Object.entries(metrics)) {
      if (k.includes('cpu') && v.unit === 'celsius' && v.value !== null) {
        cpuTemp = v.value;
      }
      if (k.includes('rp1') && v.unit === 'celsius' && v.value !== null) {
        rp1Temp = v.value;
      }
      if (k.includes('hailo_temp') && v.value !== null) {
        hailoTemp = v.value;
      }
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

    // Undervoltage / Throttling
    const isThrottled = metrics.rpi_is_throttled && metrics.rpi_is_throttled.value > 0;
    const isUndervolt = metrics.rpi_undervoltage_now && metrics.rpi_undervoltage_now.value > 0;
    const banner = document.getElementById('alert-banner');
    if (isThrottled || isUndervolt) {
      banner.style.display = 'flex';
    } else {
      banner.style.display = 'none';
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
    else cpuBar.style.background = 'var(--accent-cyan)';
  }
  if (rp1Temp !== null) {
    document.getElementById('val-rp1-temp').textContent = `${rp1Temp}°C`;
  }
  if (hailoTemp !== null) {
    document.getElementById('val-hailo-temp').textContent = `${hailoTemp}°C`;
  } else {
    document.getElementById('val-hailo-temp').textContent = 'N/A';
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

  // 5. Update Charts
  const nowLabel = new Date().toLocaleTimeString();
  if (typeof updateChartSeries === 'function') {
    if (latencyChart) updateChartSeries(latencyChart, nowLabel, [npuLat, prepLat, postLat]);
    if (fpsChart) updateChartSeries(fpsChart, nowLabel, [fps]);
    if (thermalChart) updateChartSeries(thermalChart, nowLabel, [cpuTemp || 0, rp1Temp || 0, hailoTemp || 0]);
    if (resourceChart) updateChartSeries(resourceChart, nowLabel, [cpuUtil || 0, memUtil || 0]);
  }

  // 6. Render Detections List
  renderDetections(detections);
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
// Interactive UI Handlers
// -----------------------------------------------------------------------------

async function toggleInference() {
  const endpoint = isInferenceRunning ? '/api/v1/inference/stop' : '/api/v1/inference/start';
  try {
    const res = await fetch(endpoint, { method: 'POST' });
    const data = await res.json();
    console.log('Inference toggle response:', data);
  } catch (e) {
    console.error('Failed to toggle inference', e);
  }
}

function selectSourceTab(type) {
  currentSourceType = type;
  document.getElementById('tab-source-file').className = `tab-btn ${type === 'file' ? 'active' : ''}`;
  document.getElementById('tab-source-usb').className = `tab-btn ${type === 'usb' ? 'active' : ''}`;
  document.getElementById('tab-source-picam').className = `tab-btn ${type === 'picamera' ? 'active' : ''}`;

  document.getElementById('controls-file').style.display = type === 'file' ? 'flex' : 'none';
  document.getElementById('controls-usb').style.display = type === 'usb' ? 'flex' : 'none';
  document.getElementById('controls-picam').style.display = type === 'picamera' ? 'flex' : 'none';
}

async function loadDiscoveredSources() {
  try {
    const res = await fetch('/api/v1/video/sources');
    const data = await res.json();

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
  } catch (e) {
    console.error('Failed to load video sources', e);
  }
}

async function switchToFileSource() {
  const fileVal = document.getElementById('select-video-file').value;
  try {
    await fetch('/api/v1/video/source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_type: 'file',
        file_path: fileVal ? `media/${fileVal}` : null,
        loop: true
      })
    });
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
      const err = await res.json();
      alert(`Pi Camera error: ${err.detail}`);
    }
  } catch (e) {
    console.error('Failed to activate CSI camera', e);
  }
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

// Diagnostics Modal
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
    const catalog = await catRes.json();
    const tbody = document.getElementById('table-catalog-body');
    if (catalog && catalog.length > 0) {
      tbody.innerHTML = catalog.map(c => `
        <tr>
          <td><code>${c.metric_name}</code></td>
          <td>${c.unit}</td>
          <td>${c.source}</td>
          <td><span class="status-pill ${c.current_status.toLowerCase()}">${c.current_status}</span></td>
        </tr>
      `).join('');
    }
  } catch (e) {
    console.error('Failed to load diagnostics', e);
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

    if (btnHailo && data.backends?.hailo) {
      btnHailo.disabled = !data.backends.hailo.available;
      if (!data.backends.hailo.available) {
        btnHailo.title = 'Hailo-8L NPU unavailable (hardware node or HEF model missing)';
      } else {
        btnHailo.title = 'Hailo-8L NPU Accelerator';
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
      if (data.current_backend === 'cpu') {
        btnHailo?.classList.remove('active');
        btnCpu?.classList.add('active');
      } else {
        btnHailo?.classList.add('active');
        btnCpu?.classList.remove('active');
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
      if (backend === 'cpu') {
        btnHailo?.classList.remove('active');
        btnCpu?.classList.add('active');
      } else {
        btnHailo?.classList.add('active');
        btnCpu?.classList.remove('active');
      }
    }
  } catch (e) {
    console.error('Failed to switch backend', e);
    alert(`Error switching backend: ${e.message}`);
  } finally {
    if (targetBtn) {
      targetBtn.innerHTML = originalContent;
    }
    isSwitchingBackend = false;
    await loadAvailableBackends();
  }
}

// Initialise on page load
window.addEventListener('DOMContentLoaded', () => {
  checkInitialReadiness();
  loadAvailableBackends();
  loadDiscoveredSources();
  connectWebSocket();
});
