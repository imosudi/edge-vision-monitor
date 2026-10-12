/**
 * Real-time Chart.js telemetry charts initialisation and streaming updates.
 * Theme: Modern Edge-AI Suite (mioemi.com palette)
 */

const MAX_CHART_POINTS = 30;
const MAX_MODAL_POINTS = 50;

const chartOptionsBase = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 300 },
  elements: {
    point: { radius: 0 },
    line: { tension: 0.25, borderWidth: 2 }
  },
  plugins: {
    legend: {
      labels: {
        color: '#475569',
        font: { family: 'Inter', size: 11, weight: '500' },
        boxWidth: 10
      }
    }
  },
  scales: {
    x: {
      grid: { color: 'rgba(0, 0, 0, 0.04)' },
      ticks: { display: false }
    },
    y: {
      grid: { color: 'rgba(0, 0, 0, 0.05)' },
      ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 } }
    }
  }
};

let latencyChart = null;
let fpsChart = null;
let thermalChart = null;
let resourceChart = null;
let fanChart = null;
let cpuFreqChart = null;
let voltageChart = null;
let procFootprintChart = null;
let modalSensorChart = null;

function initCharts() {
  // 1. Latency Breakdown History
  const ctxLatency = document.getElementById('chart-latency');
  if (ctxLatency) {
    latencyChart = new Chart(ctxLatency, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'Accelerator Exec (ms)', data: [], borderColor: '#7c3aed', backgroundColor: 'rgba(124, 58, 237, 0.08)', fill: false },
          { label: 'Preprocess (ms)', data: [], borderColor: '#2563eb', backgroundColor: 'rgba(37, 99, 235, 0.08)', fill: false },
          { label: 'Postprocess (ms)', data: [], borderColor: '#ec4899', backgroundColor: 'rgba(236, 72, 153, 0.08)', fill: false }
        ]
      },
      options: chartOptionsBase
    });
  }

  // 2. Inference FPS History
  const ctxFps = document.getElementById('chart-fps');
  if (ctxFps) {
    fpsChart = new Chart(ctxFps, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'Inference FPS', data: [], borderColor: '#16a34a', backgroundColor: 'rgba(22, 163, 74, 0.12)', fill: true }
        ]
      },
      options: chartOptionsBase
    });
  }

  // 3. Thermal Profile History
  const ctxThermal = document.getElementById('chart-thermal');
  if (ctxThermal) {
    thermalChart = new Chart(ctxThermal, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'CPU Temp (°C)', data: [], borderColor: '#f59e0b', backgroundColor: 'transparent' },
          { label: 'RP1 Temp (°C)', data: [], borderColor: '#2563eb', backgroundColor: 'transparent' },
          { label: 'Hailo NPU (°C)', data: [], borderColor: '#16a34a', backgroundColor: 'transparent' }
        ]
      },
      options: chartOptionsBase
    });
  }

  // 4. System Utilisation History
  const ctxResources = document.getElementById('chart-resources');
  if (ctxResources) {
    resourceChart = new Chart(ctxResources, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'CPU Util (%)', data: [], borderColor: '#7c3aed', backgroundColor: 'transparent' },
          { label: 'RAM Util (%)', data: [], borderColor: '#2563eb', backgroundColor: 'transparent' }
        ]
      },
      options: {
        ...chartOptionsBase,
        scales: {
          ...chartOptionsBase.scales,
          y: { ...chartOptionsBase.scales.y, min: 0, max: 100 }
        }
      }
    });
  }

  // 5. Active Cooling & PWM Fan Speed
  const ctxFan = document.getElementById('chart-fan');
  if (ctxFan) {
    fanChart = new Chart(ctxFan, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'PWM Fan Speed (RPM)', data: [], borderColor: '#059669', backgroundColor: 'rgba(5, 150, 105, 0.12)', fill: true }
        ]
      },
      options: chartOptionsBase
    });
  }

  // 6. Quad-Core CPU Clock Frequencies
  const ctxCpuFreq = document.getElementById('chart-cpufreq');
  if (ctxCpuFreq) {
    cpuFreqChart = new Chart(ctxCpuFreq, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'Core 0 (MHz)', data: [], borderColor: '#2563eb', backgroundColor: 'transparent' },
          { label: 'Core 1 (MHz)', data: [], borderColor: '#7c3aed', backgroundColor: 'transparent' },
          { label: 'Core 2 (MHz)', data: [], borderColor: '#c026d3', backgroundColor: 'transparent' },
          { label: 'Core 3 (MHz)', data: [], borderColor: '#f59e0b', backgroundColor: 'transparent' }
        ]
      },
      options: chartOptionsBase
    });
  }

  // 7. RP1 Southbridge Rail Voltages
  const ctxVoltages = document.getElementById('chart-voltages');
  if (ctxVoltages) {
    voltageChart = new Chart(ctxVoltages, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'In1 Rail (V)', data: [], borderColor: '#2563eb', backgroundColor: 'transparent' },
          { label: 'In2 Rail (V)', data: [], borderColor: '#f59e0b', backgroundColor: 'transparent' },
          { label: 'In3 Rail (V)', data: [], borderColor: '#10b981', backgroundColor: 'transparent' },
          { label: 'In4 Rail (V)', data: [], borderColor: '#7c3aed', backgroundColor: 'transparent' }
        ]
      },
      options: chartOptionsBase
    });
  }

  // 8. Process Footprint & System Load
  const ctxProcFootprint = document.getElementById('chart-procfootprint');
  if (ctxProcFootprint) {
    procFootprintChart = new Chart(ctxProcFootprint, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'Process CPU (%)', data: [], borderColor: '#ef4444', backgroundColor: 'transparent' },
          { label: 'Process RAM (MB)', data: [], borderColor: '#2563eb', backgroundColor: 'transparent' },
          { label: 'System Load (1m)', data: [], borderColor: '#f59e0b', backgroundColor: 'transparent' }
        ]
      },
      options: chartOptionsBase
    });
  }
}

function updateChartSeries(chart, label, values) {
  if (!chart) return;
  chart.data.labels.push(label);
  if (chart.data.labels.length > MAX_CHART_POINTS) {
    chart.data.labels.shift();
  }

  values.forEach((val, idx) => {
    if (chart.data.datasets[idx]) {
      chart.data.datasets[idx].data.push(val);
      if (chart.data.datasets[idx].data.length > MAX_CHART_POINTS) {
        chart.data.datasets[idx].data.shift();
      }
    }
  });

  chart.update('none');
}

/**
 * Filter dashboard charts by category tab
 */
function filterCharts(category, btn) {
  if (btn) {
    document.querySelectorAll('.chart-filter-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }
  const cards = document.querySelectorAll('.charts-section .chart-card');
  cards.forEach(card => {
    if (category === 'all' || card.getAttribute('data-cat') === category) {
      card.style.display = 'flex';
    } else {
      card.style.display = 'none';
    }
  });
}

/**
 * Initialize or update the interactive sensor chart inside the diagnostics modal.
 */
function initOrUpdateModalSensorChart(metricName, unit, initialHistory = []) {
  const ctx = document.getElementById('chart-modal-sensor');
  if (!ctx) return;

  const labels = initialHistory.map(h => {
    try {
      return new Date(h.timestamp_utc).toLocaleTimeString();
    } catch {
      return '';
    }
  });
  const dataPoints = initialHistory.map(h => h.value !== null ? h.value : 0);

  if (modalSensorChart) {
    modalSensorChart.data.labels = labels;
    modalSensorChart.data.datasets[0].label = `${metricName} (${unit})`;
    modalSensorChart.data.datasets[0].data = dataPoints;
    modalSensorChart.update();
  } else {
    modalSensorChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: `${metricName} (${unit})`,
            data: dataPoints,
            borderColor: '#2563eb',
            backgroundColor: 'rgba(37, 99, 235, 0.08)',
            fill: true,
            borderWidth: 2
          }
        ]
      },
      options: {
        ...chartOptionsBase,
        elements: {
          point: { radius: 2, hoverRadius: 5 },
          line: { tension: 0.25, borderWidth: 2 }
        }
      }
    });
  }
}

/**
 * Push streaming point to the active sensor in the diagnostics modal.
 */
function appendModalSensorPoint(label, value) {
  if (!modalSensorChart) return;
  modalSensorChart.data.labels.push(label);
  if (modalSensorChart.data.labels.length > MAX_MODAL_POINTS) {
    modalSensorChart.data.labels.shift();
  }
  modalSensorChart.data.datasets[0].data.push(value);
  if (modalSensorChart.data.datasets[0].data.length > MAX_MODAL_POINTS) {
    modalSensorChart.data.datasets[0].data.shift();
  }
  modalSensorChart.update('none');
}

window.addEventListener('DOMContentLoaded', initCharts);
