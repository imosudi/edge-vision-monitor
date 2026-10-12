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
  '#2563eb', '#7c3aed', '#16a34a', '#f59e0b', '#ef4444',
  '#ec4899', '#0891b2', '#6366f1', '#f97316', '#84cc16'
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

    // Undervoltage / Thermal Throttling / Frequency Drop
    const isThermalThrottling = metrics.cpu_thermal_throttle_active && metrics.cpu_thermal_throttle_active.value > 0;
    const isFreqCapped = metrics.rpi_arm_freq_capped_now && metrics.rpi_arm_freq_capped_now.value > 0;
    const isThrottled = metrics.rpi_is_throttled && metrics.rpi_is_throttled.value > 0;
    const isUndervolt = metrics.rpi_undervoltage_now && metrics.rpi_undervoltage_now.value > 0;
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
    const curFreq = metrics.cpu_freq_cur_mhz && metrics.cpu_freq_cur_mhz.value !== null ? metrics.cpu_freq_cur_mhz.value : (metrics.cpu_freq_cpu0_mhz?.value || baseFreq);
    const isFullBase = (metrics.cpu_is_full_base_freq && metrics.cpu_is_full_base_freq.value > 0) || curFreq >= 2385.0;
    const throttleDrop = metrics.cpu_freq_throttle_drop_mhz && metrics.cpu_freq_throttle_drop_mhz.value !== null ? metrics.cpu_freq_throttle_drop_mhz.value : 0.0;

    const elClock = document.getElementById('val-cpu-clock');
    if (elClock) {
      elClock.textContent = `${Math.round(curFreq)} MHz (${(curFreq / 1000).toFixed(2)} GHz)`;
    }

    const elState = document.getElementById('val-clock-state');
    if (elState) {
      if (isThermalThrottling) {
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
      if (isThermalThrottling && throttleDrop > 0) {
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

    // Active Cooling & Fan Speed
    const fanRpm = metrics.hwmon_pwmfan_fan1_rpm && metrics.hwmon_pwmfan_fan1_rpm.value !== null ? metrics.hwmon_pwmfan_fan1_rpm.value : null;
    const fanState = metrics.cooling_pwm_fan_cur_state && metrics.cooling_pwm_fan_cur_state.value !== null ? metrics.cooling_pwm_fan_cur_state.value : null;
    if (fanChart && fanRpm !== null) {
      updateChartSeries(fanChart, nowLabel, [fanRpm]);
      const fanBadge = document.getElementById('lbl-fan-speed');
      if (fanBadge) {
        fanBadge.textContent = `${Math.round(fanRpm)} RPM${fanState !== null ? ' (Lvl ' + fanState + ')' : ''}`;
      }
    }

    // CPU Quad-Core Clock Frequencies
    const cpu0Freq = metrics.cpu_freq_cpu0_mhz && metrics.cpu_freq_cpu0_mhz.value !== null ? metrics.cpu_freq_cpu0_mhz.value : null;
    const cpu1Freq = metrics.cpu_freq_cpu1_mhz && metrics.cpu_freq_cpu1_mhz.value !== null ? metrics.cpu_freq_cpu1_mhz.value : null;
    const cpu2Freq = metrics.cpu_freq_cpu2_mhz && metrics.cpu_freq_cpu2_mhz.value !== null ? metrics.cpu_freq_cpu2_mhz.value : null;
    const cpu3Freq = metrics.cpu_freq_cpu3_mhz && metrics.cpu_freq_cpu3_mhz.value !== null ? metrics.cpu_freq_cpu3_mhz.value : null;
    if (cpuFreqChart && cpu0Freq !== null) {
      updateChartSeries(cpuFreqChart, nowLabel, [
        cpu0Freq,
        cpu1Freq !== null ? cpu1Freq : cpu0Freq,
        cpu2Freq !== null ? cpu2Freq : cpu0Freq,
        cpu3Freq !== null ? cpu3Freq : cpu0Freq
      ]);

      const baseTag = document.getElementById('lbl-cpu-base-tag');
      if (baseTag) {
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
    }

    // RP1 Southbridge Rail Voltages
    const vIn1 = metrics.hwmon_rp1_adc_in1_voltage && metrics.hwmon_rp1_adc_in1_voltage.value !== null ? metrics.hwmon_rp1_adc_in1_voltage.value : null;
    const vIn2 = metrics.hwmon_rp1_adc_in2_voltage && metrics.hwmon_rp1_adc_in2_voltage.value !== null ? metrics.hwmon_rp1_adc_in2_voltage.value : null;
    const vIn3 = metrics.hwmon_rp1_adc_in3_voltage && metrics.hwmon_rp1_adc_in3_voltage.value !== null ? metrics.hwmon_rp1_adc_in3_voltage.value : null;
    const vIn4 = metrics.hwmon_rp1_adc_in4_voltage && metrics.hwmon_rp1_adc_in4_voltage.value !== null ? metrics.hwmon_rp1_adc_in4_voltage.value : null;
    if (voltageChart && vIn1 !== null) {
      updateChartSeries(voltageChart, nowLabel, [
        vIn1,
        vIn2 !== null ? vIn2 : 0,
        vIn3 !== null ? vIn3 : 0,
        vIn4 !== null ? vIn4 : 0
      ]);
    }

    // Process Footprint & System Load
    const procCpu = metrics.process_cpu_percent && metrics.process_cpu_percent.value !== null ? metrics.process_cpu_percent.value : null;
    const procRss = metrics.process_memory_rss_mb && metrics.process_memory_rss_mb.value !== null ? metrics.process_memory_rss_mb.value : null;
    const sysLoad = metrics.load_average_1m && metrics.load_average_1m.value !== null ? metrics.load_average_1m.value : null;
    if (procFootprintChart && (procCpu !== null || procRss !== null || sysLoad !== null)) {
      updateChartSeries(procFootprintChart, nowLabel, [
        procCpu !== null ? procCpu : 0,
        procRss !== null ? procRss : 0,
        sysLoad !== null ? sysLoad : 0
      ]);
    }
  }

  // Update live values in Diagnostics modal if open
  updateModalTelemetryLive(metrics, nowLabel);

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

      // Initialize selected metric plot
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
