/**
 * Real-time Chart.js telemetry charts initialisation and streaming updates.
 * Theme: Modern Edge-AI Suite (mioemi.com palette)
 */

const DEFAULT_SESSION_MAX_POINTS = 1800; // 30 minutes @ 1 Hz
const MAX_MODAL_POINTS = 1800;

/**
 * Retain waveforms for the whole detection session duration.
 * For configured timers (e.g. 300s, 600s, 1800s), hold the full duration.
 * For Continuous mode (0), retain a rolling 30-minute window (1800 points @ 1Hz).
 */
function getSessionMaxChartPoints() {
  const dur = (typeof detectionDurationSec !== 'undefined' && detectionDurationSec > 0)
    ? detectionDurationSec
    : (parseInt(localStorage.getItem('evm_detection_duration_sec'), 10) || 0);
  return Math.max(DEFAULT_SESSION_MAX_POINTS, dur);
}

const chartOptionsBase = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  normalized: true,
  elements: {
    point: { radius: 0 },
    line: { tension: 0.2, borderWidth: 1.8 }
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
let interFrameChart = null;
let detectionsCountChart = null;
let confHistChart = null;
let thermalChart = null;
let resourceChart = null;
let diskChart = null;
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

  // 2. Processed Frames Per Second History (Matches screenshot: sky blue with prominent point markers)
  const ctxFps = document.getElementById('chart-fps');
  if (ctxFps) {
    fpsChart = new Chart(ctxFps, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Processed FPS',
            data: [],
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56, 189, 248, 0.08)',
            fill: true,
            pointRadius: 3,
            pointHoverRadius: 5,
            pointBackgroundColor: '#38bdf8',
            pointBorderColor: '#38bdf8',
            borderWidth: 2,
            tension: 0.2
          }
        ]
      },
      options: {
        ...chartOptionsBase,
        scales: {
          ...chartOptionsBase.scales,
          y: {
            ...chartOptionsBase.scales.y,
            min: 0,
            suggestedMax: 30,
            ticks: {
              ...chartOptionsBase.scales.y.ticks,
              callback: (val) => `${val}`
            }
          }
        }
      }
    });
  }

  // 3. Inter-Frame Interval (ms) (Matches screenshot: pure scatter points around 35-40ms with jitter spikes)
  const ctxInterframe = document.getElementById('chart-interframe');
  if (ctxInterframe) {
    interFrameChart = new Chart(ctxInterframe, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Interval (ms)',
            data: [],
            showLine: false,
            pointRadius: 3.5,
            pointHoverRadius: 6,
            pointBackgroundColor: '#a78bfa',
            pointBorderColor: '#a78bfa',
            backgroundColor: '#a78bfa'
          }
        ]
      },
      options: {
        ...chartOptionsBase,
        elements: {
          point: { radius: 3.5, hoverRadius: 6 }
        },
        scales: {
          ...chartOptionsBase.scales,
          y: {
            ...chartOptionsBase.scales.y,
            min: 0,
            suggestedMax: 80,
            ticks: {
              ...chartOptionsBase.scales.y.ticks,
              callback: (val) => `${val} ms`
            }
          }
        },
        plugins: {
          ...chartOptionsBase.plugins,
          tooltip: {
            callbacks: {
              label: (ctx) => ` Inter-frame: ${ctx.parsed.y} ms`
            }
          }
        }
      }
    });
  }

  // 4. Detections Per Frame (Matches screenshot: stepped teal curve)
  const ctxDetectionsCount = document.getElementById('chart-detections-count');
  if (ctxDetectionsCount) {
    detectionsCountChart = new Chart(ctxDetectionsCount, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Detections / Frame',
            data: [],
            borderColor: '#2dd4bf',
            backgroundColor: 'rgba(45, 212, 191, 0.08)',
            fill: false,
            borderWidth: 1.8,
            stepped: 'middle',
            pointRadius: 0
          }
        ]
      },
      options: {
        ...chartOptionsBase,
        scales: {
          ...chartOptionsBase.scales,
          y: {
            ...chartOptionsBase.scales.y,
            min: 0,
            suggestedMax: 3,
            ticks: {
              ...chartOptionsBase.scales.y.ticks,
              precision: 0,
              callback: (val) => `${val}`
            }
          }
        },
        plugins: {
          ...chartOptionsBase.plugins,
          tooltip: {
            callbacks: {
              label: (ctx) => ` Detected: ${ctx.parsed.y} object${ctx.parsed.y === 1 ? '' : 's'}`
            }
          }
        }
      }
    });
  }

  // 5. Confidence Distribution Histogram (Matches screenshot: sky blue binned bars)
  const ctxConfHist = document.getElementById('chart-conf-hist');
  if (ctxConfHist) {
    confHistChart = new Chart(ctxConfHist, {
      type: 'bar',
      data: {
        labels: ['0.0-0.1', '0.1-0.2', '0.2-0.3', '0.3-0.4', '0.4-0.5', '0.5-0.6', '0.6-0.7', '0.7-0.8', '0.8-0.9', '0.9-1.0'],
        datasets: [
          {
            label: 'Bounding Boxes',
            data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            backgroundColor: '#38bdf8',
            borderRadius: 3,
            borderWidth: 0,
            barPercentage: 0.95,
            categoryPercentage: 0.95
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => `Confidence Range: ${items[0]?.label || ''}`,
              label: (ctx) => ` Count: ${ctx.parsed.y} boxes`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#64748b',
              font: { family: 'JetBrains Mono', size: 9 },
              maxRotation: 45,
              minRotation: 0
            }
          },
          y: {
            beginAtZero: true,
            suggestedMax: 10,
            grid: { color: 'rgba(0, 0, 0, 0.05)' },
            ticks: {
              color: '#64748b',
              font: { family: 'JetBrains Mono', size: 10 },
              precision: 0
            }
          }
        }
      }
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

  // 4b. Disk Utilisation History (Matches screenshot: amber line for disk usage %)
  const ctxDisk = document.getElementById('chart-disk');
  if (ctxDisk) {
    diskChart = new Chart(ctxDisk, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Disk Utilisation (%)',
            data: [],
            borderColor: '#fbbf24',
            backgroundColor: 'rgba(251, 191, 36, 0.08)',
            fill: false,
            borderWidth: 2,
            tension: 0.1
          }
        ]
      },
      options: {
        ...chartOptionsBase,
        scales: {
          ...chartOptionsBase.scales,
          y: {
            ...chartOptionsBase.scales.y,
            min: 0,
            max: 100,
            ticks: {
              ...chartOptionsBase.scales.y.ticks,
              callback: (val) => `${val}%`
            }
          }
        },
        plugins: {
          ...chartOptionsBase.plugins,
          tooltip: {
            callbacks: {
              label: (ctx) => ` Disk: ${ctx.parsed.y.toFixed(1)}%`
            }
          }
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

  // 6. Quad-Core CPU Clock Frequencies (Distinct point styles and dash patterns for overlapping curves)
  const ctxCpuFreq = document.getElementById('chart-cpufreq');
  if (ctxCpuFreq) {
    cpuFreqChart = new Chart(ctxCpuFreq, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Core 0 (MHz)',
            data: [],
            borderColor: '#2563eb',
            backgroundColor: '#2563eb',
            borderWidth: 2.5,
            borderDash: [],
            pointStyle: 'circle',
            pointRadius: 4,
            pointHoverRadius: 6,
            tension: 0.25
          },
          {
            label: 'Core 1 (MHz)',
            data: [],
            borderColor: '#7c3aed',
            backgroundColor: '#7c3aed',
            borderWidth: 2,
            borderDash: [6, 4],
            pointStyle: 'triangle',
            pointRadius: 5,
            pointHoverRadius: 7,
            tension: 0.25
          },
          {
            label: 'Core 2 (MHz)',
            data: [],
            borderColor: '#c026d3',
            backgroundColor: '#c026d3',
            borderWidth: 2,
            borderDash: [2, 3],
            pointStyle: 'rectRot',
            pointRadius: 5,
            pointHoverRadius: 7,
            tension: 0.25
          },
          {
            label: 'Core 3 (MHz)',
            data: [],
            borderColor: '#f59e0b',
            backgroundColor: '#f59e0b',
            borderWidth: 2,
            borderDash: [8, 3, 2, 3],
            pointStyle: 'rect',
            pointRadius: 4.5,
            pointHoverRadius: 6.5,
            tension: 0.25
          }
        ]
      },
      options: {
        ...chartOptionsBase,
        elements: {
          line: { tension: 0.25 }
        },
        plugins: {
          ...chartOptionsBase.plugins,
          legend: {
            labels: {
              color: '#475569',
              font: { family: 'Inter', size: 11, weight: '500' },
              usePointStyle: true,
              pointStyleWidth: 11
            }
          },
          tooltip: {
            callbacks: {
              label: (context) => ` ${context.dataset.label}: ${context.parsed.y} MHz`
            }
          }
        }
      }
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

  // 8. Process Footprint & System Load (Dual Y-Axis: Left for MB/%, Right for 1m Load)
  const ctxProcFootprint = document.getElementById('chart-procfootprint');
  if (ctxProcFootprint) {
    procFootprintChart = new Chart(ctxProcFootprint, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Process CPU (%)',
            data: [],
            borderColor: '#ef4444',
            backgroundColor: 'rgba(239, 68, 68, 0.05)',
            borderWidth: 2,
            tension: 0.25,
            pointRadius: 0,
            yAxisID: 'y'
          },
          {
            label: 'Process RAM (MB)',
            data: [],
            borderColor: '#2563eb',
            backgroundColor: 'rgba(37, 99, 235, 0.05)',
            borderWidth: 2,
            tension: 0.25,
            pointRadius: 0,
            yAxisID: 'y'
          },
          {
            label: 'System Load (1m)',
            data: [],
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.08)',
            borderWidth: 2,
            tension: 0.25,
            pointRadius: 0,
            yAxisID: 'y1'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        interaction: {
          mode: 'index',
          intersect: false
        },
        plugins: {
          legend: {
            labels: {
              color: '#475569',
              font: { family: 'Inter', size: 11, weight: '500' },
              boxWidth: 10
            }
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                let label = context.dataset.label || '';
                if (label) label += ': ';
                if (context.parsed.y !== null && context.parsed.y !== undefined) {
                  if (context.datasetIndex === 0) label += `${context.parsed.y}%`;
                  else if (context.datasetIndex === 1) label += `${context.parsed.y} MB`;
                  else label += `${context.parsed.y}`;
                }
                return label;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { color: 'rgba(0, 0, 0, 0.04)' },
            ticks: { display: false }
          },
          y: {
            type: 'linear',
            display: true,
            position: 'left',
            min: 0,
            grid: { color: 'rgba(0, 0, 0, 0.05)' },
            ticks: {
              color: '#64748b',
              font: { family: 'JetBrains Mono', size: 10 }
            },
            title: {
              display: true,
              text: 'RAM (MB) / CPU (%)',
              color: '#64748b',
              font: { family: 'Inter', size: 9, weight: '600' }
            }
          },
          y1: {
            type: 'linear',
            display: true,
            position: 'right',
            min: 0,
            grid: { drawOnChartArea: false },
            ticks: {
              color: '#f59e0b',
              font: { family: 'JetBrains Mono', size: 10 }
            },
            title: {
              display: true,
              text: 'System Load (1m)',
              color: '#f59e0b',
              font: { family: 'Inter', size: 9, weight: '600' }
            }
          }
        }
      }
    });
  }

  // Initialise benchmark comparison charts
  initBenchmarkCharts();

  // Capture initial clean live chart templates for reset operations
  initialLiveChartTemplates = captureLiveChartStates();
}

let initialLiveChartTemplates = null;
let isBenchmarkWaveformsMode = false;
let savedLiveChartStates = null;

function updateChartSeries(chart, label, values) {
  if (!chart) return;
  if (isBenchmarkWaveformsMode) return; // Retain dual benchmark curves on live waveforms
  if (typeof isWaveformsPaused !== 'undefined' && isWaveformsPaused) return;
  const maxPts = getSessionMaxChartPoints();
  chart.data.labels.push(label);
  if (chart.data.labels.length > maxPts) {
    chart.data.labels.shift();
  }

  values.forEach((val, idx) => {
    if (chart.data.datasets[idx]) {
      chart.data.datasets[idx].data.push(val);
      if (chart.data.datasets[idx].data.length > maxPts) {
        chart.data.datasets[idx].data.shift();
      }
    }
  });

  chart.update('none');

  // If this chart is currently open in the Enlarge View modal, mirror points in real-time
  if (typeof activeEnlargedChartId !== 'undefined' && activeEnlargedChartId && typeof enlargedChart !== 'undefined' && enlargedChart && CHART_REGISTRY[activeEnlargedChartId]?.getChart() === chart) {
    enlargedChart.data.labels.push(label);
    if (enlargedChart.data.labels.length > maxPts) {
      enlargedChart.data.labels.shift();
    }
    values.forEach((val, idx) => {
      if (enlargedChart.data.datasets[idx]) {
        enlargedChart.data.datasets[idx].data.push(val);
        if (enlargedChart.data.datasets[idx].data.length > maxPts) {
          enlargedChart.data.datasets[idx].data.shift();
        }
      }
    });
    enlargedChart.update('none');
  }
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
 * Initialise or update the interactive sensor chart inside the diagnostics modal.
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
  if (typeof isWaveformsPaused !== 'undefined' && isWaveformsPaused) return;
  const maxPts = getSessionMaxChartPoints();
  modalSensorChart.data.labels.push(label);
  if (modalSensorChart.data.labels.length > maxPts) {
    modalSensorChart.data.labels.shift();
  }
  modalSensorChart.data.datasets[0].data.push(value);
  if (modalSensorChart.data.datasets[0].data.length > maxPts) {
    modalSensorChart.data.datasets[0].data.shift();
  }
  modalSensorChart.update('none');
}

/**
 * Reset all real-time dashboard and modal charts datasets and labels.
 */
function resetAllCharts() {
  isBenchmarkWaveformsMode = false;
  savedLiveChartStates = null;

  if (initialLiveChartTemplates) {
    const applyCleanTemplate = (chart, template) => {
      if (!chart || !template) return;
      chart.data.labels = (chart === confHistChart) ? ['0.0-0.1', '0.1-0.2', '0.2-0.3', '0.3-0.4', '0.4-0.5', '0.5-0.6', '0.6-0.7', '0.7-0.8', '0.8-0.9', '0.9-1.0'] : [];
      chart.data.datasets = template.datasets.map(ds => ({
        ...ds,
        data: (chart === confHistChart) ? [0, 0, 0, 0, 0, 0, 0, 0, 0, 0] : []
      }));
      if (chart.options && chart.options.scales && chart.options.scales.x) {
        if (chart.options.scales.x.ticks) chart.options.scales.x.ticks.display = (chart === confHistChart);
        if (chart.options.scales.x.title) chart.options.scales.x.title.display = false;
      }
      chart.update('none');
    };

    applyCleanTemplate(latencyChart, initialLiveChartTemplates.latency);
    applyCleanTemplate(fpsChart, initialLiveChartTemplates.fps);
    applyCleanTemplate(interFrameChart, initialLiveChartTemplates.interframe);
    applyCleanTemplate(detectionsCountChart, initialLiveChartTemplates.detCount);
    applyCleanTemplate(confHistChart, initialLiveChartTemplates.confHist);
    applyCleanTemplate(thermalChart, initialLiveChartTemplates.thermal);
    applyCleanTemplate(resourceChart, initialLiveChartTemplates.resources);
    applyCleanTemplate(diskChart, initialLiveChartTemplates.disk);
    applyCleanTemplate(fanChart, initialLiveChartTemplates.fan);
    applyCleanTemplate(cpuFreqChart, initialLiveChartTemplates.cpuFreq);
    applyCleanTemplate(voltageChart, initialLiveChartTemplates.voltage);
    applyCleanTemplate(procFootprintChart, initialLiveChartTemplates.procFootprint);
  } else {
    const lineCharts = [
      latencyChart,
      fpsChart,
      interFrameChart,
      detectionsCountChart,
      thermalChart,
      resourceChart,
      diskChart,
      fanChart,
      cpuFreqChart,
      voltageChart,
      procFootprintChart,
      modalSensorChart
    ];

    lineCharts.forEach(chart => {
      if (chart && chart.data) {
        chart.data.labels = [];
        if (Array.isArray(chart.data.datasets)) {
          chart.data.datasets.forEach(ds => {
            ds.data = [];
          });
        }
        if (chart.options && chart.options.scales && chart.options.scales.x) {
          if (chart.options.scales.x.ticks) chart.options.scales.x.ticks.display = (chart === confHistChart);
          if (chart.options.scales.x.title) chart.options.scales.x.title.display = false;
        }
        chart.update('none');
      }
    });

    if (confHistChart && confHistChart.data && Array.isArray(confHistChart.data.datasets)) {
      if (confHistChart.data.datasets[0]) {
        confHistChart.data.datasets[0].data = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
      }
      confHistChart.update('none');
    }
  }

  if (typeof enlargedChart !== 'undefined' && enlargedChart && enlargedChart.data) {
    enlargedChart.data.labels = [];
    if (Array.isArray(enlargedChart.data.datasets)) {
      enlargedChart.data.datasets.forEach(ds => {
        ds.data = [];
      });
    }
    enlargedChart.update('none');
  }

  const kpiBar = document.getElementById('wb-kpi-bar');
  if (kpiBar) kpiBar.style.display = 'none';

  const resetText = (id, def = '--') => {
    const el = document.getElementById(id);
    if (el) el.textContent = def;
  };
  resetText('lbl-latency-val', '-- ms');
  resetText('lbl-fps-val', '-- FPS');
  resetText('lbl-fps-stat', '-- FPS');
  resetText('lbl-inter-frame', '-- ms');
  resetText('lbl-detections-per-frame', '-- Objects');
  resetText('lbl-conf-summary', '--');
  resetText('lbl-thermal-cpu', '-- °C');
  resetText('lbl-disk-utilisation', '--%');
  resetText('lbl-fan-speed', '-- RPM');
  resetText('lbl-cpu-base-tag', '2.4 GHz Base Target');
  resetText('lbl-proc-footprint', '--');
}

/* ==========================================================================
   Waveform Enlarge View & High-Resolution Image/CSV Export (Snapshots)
   ========================================================================== */

let enlargedChart = null;
let activeEnlargedChartId = null;

const CHART_REGISTRY = {
  'chart-latency': {
    getChart: () => latencyChart,
    title: 'Latency Breakdown History (ms)',
    icon: '📈',
    badge: 'INFERENCE PIPELINE',
    desc: 'High-resolution visualisation of preprocessing, Hailo-8L neural processing unit (NPU) accelerator execution, and postprocessing pipeline latencies over time.',
    yUnit: 'ms',
    defaultFilename: 'latency_breakdown_history'
  },
  'chart-fps': {
    getChart: () => fpsChart,
    title: 'Processed Frames Per Second (FPS)',
    icon: '🚀',
    badge: 'THROUGHPUT',
    desc: 'Real-time pipeline throughput tracking processed frames per second across camera ingestion, neural inference, and tracking passes.',
    yUnit: 'FPS',
    defaultFilename: 'processed_fps_history'
  },
  'chart-interframe': {
    getChart: () => interFrameChart,
    title: 'Inter-Frame Interval (ms)',
    icon: '⏱️',
    badge: 'TEMPORAL JITTER',
    desc: 'Delta timestamp between consecutive inference completions measuring temporal jitter and camera pipeline continuity.',
    yUnit: 'ms',
    defaultFilename: 'inter_frame_interval_history'
  },
  'chart-detections-count': {
    getChart: () => detectionsCountChart,
    title: 'Detections Per Frame',
    icon: '🎯',
    badge: 'OBJECT DENSITY',
    desc: 'Per-frame detected object count progression providing real-time scene complexity and multi-target density tracking.',
    yUnit: 'objects',
    defaultFilename: 'detections_per_frame_history'
  },
  'chart-conf-hist': {
    getChart: () => confHistChart,
    title: 'Confidence Histogram',
    icon: '📊',
    badge: 'CONFIDENCE DISTRIBUTION',
    desc: 'Binned confidence distribution (0.0 to 1.0) of all object detections identified across the detection session.',
    yUnit: 'detections',
    isHistogram: true,
    defaultFilename: 'confidence_histogram'
  },
  'chart-thermal': {
    getChart: () => thermalChart,
    title: 'Thermal Profile History (°C)',
    icon: '🌡️',
    badge: 'THERMALS',
    desc: 'Multi-zone temperature telemetry tracking Raspberry Pi 5 BCM2712 CPU, RP1 Southbridge I/O Controller, and Hailo-8L M.2 AI accelerator.',
    yUnit: '°C',
    defaultFilename: 'thermal_profile_history'
  },
  'chart-resources': {
    getChart: () => resourceChart,
    title: 'System Utilisation History (%)',
    icon: '💻',
    badge: 'SYSTEM LOAD',
    desc: 'Host system resource telemetry monitoring quad-core Cortex-A76 CPU overall utilisation percentage and active RAM consumption.',
    yUnit: '%',
    defaultFilename: 'system_utilisation_history'
  },
  'chart-disk': {
    getChart: () => diskChart,
    title: 'Disk Utilisation (%)',
    icon: '💾',
    badge: 'STORAGE',
    desc: 'Real-time root filesystem storage utilisation percentage tracking onboard NVMe/microSD capacity.',
    yUnit: '%',
    defaultFilename: 'disk_utilisation_history'
  },
  'chart-fan': {
    getChart: () => fanChart,
    title: 'Active Cooling & Fan Speed',
    icon: '🌀',
    badge: 'ACTIVE COOLING',
    desc: 'Raspberry Pi Active Cooler tachometer and PWM speed curve monitoring rotational fan RPM under dynamic inference workload.',
    yUnit: 'RPM',
    defaultFilename: 'fan_speed_history'
  },
  'chart-cpufreq': {
    getChart: () => cpuFreqChart,
    title: 'CPU Quad-Core Frequencies (MHz)',
    icon: '⚡',
    badge: 'FREQUENCY GOVERNOR',
    desc: 'Per-core instantaneous clock frequencies for Cortex-A76 Core 0, Core 1, Core 2, and Core 3 with throttle capped indicators.',
    yUnit: 'MHz',
    defaultFilename: 'cpu_quad_frequencies_history'
  },
  'chart-voltages': {
    getChart: () => voltageChart,
    title: 'RP1 I/O Controller Rail Voltages (V)',
    icon: '🔋',
    badge: 'POWER RAILS',
    desc: 'RP1 Southbridge ADC power supply rail telemetry monitoring core 0.8V, 1.1V, 1.8V, and 3.3V DC voltage rails.',
    yUnit: 'V',
    defaultFilename: 'rp1_rail_voltages_history'
  },
  'chart-procfootprint': {
    getChart: () => procFootprintChart,
    title: 'Process Footprint & System Load',
    icon: '⚙️',
    badge: 'PROCESS METRICS',
    desc: 'Edge Vision Monitor application process CPU utilisation (%), Resident Set Size (RSS MB), and Linux 1-minute system load average.',
    yUnit: 'mixed',
    defaultFilename: 'process_footprint_system_load_history'
  }
};

function getTimestampStr() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function downloadBlob(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 250);
}

function exportCanvasWithBranding(srcCanvas, title, defaultFilename) {
  if (!srcCanvas) return;
  const offscreen = document.createElement('canvas');
  const paddingX = 24;
  const headerHeight = 70;
  const footerHeight = 35;

  offscreen.width = Math.max(srcCanvas.width, 1000) + (paddingX * 2);
  offscreen.height = srcCanvas.height + headerHeight + footerHeight;
  const ctx = offscreen.getContext('2d');

  // Solid clean white background (prevents transparent black in photo viewers)
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, offscreen.width, offscreen.height);

  // Title
  ctx.fillStyle = '#0f172a';
  ctx.font = 'bold 16px Inter, system-ui, sans-serif';
  ctx.fillText(title, paddingX, 32);

  // Subtitle / Provenance
  ctx.fillStyle = '#64748b';
  ctx.font = '12px Inter, system-ui, sans-serif';
  ctx.fillText(`Edge Vision Monitor • Raspberry Pi 5 & Hailo-8L Edge AI • ${new Date().toLocaleString()}`, paddingX, 52);

  // Subtle separator line
  ctx.strokeStyle = '#e2e8f0';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(paddingX, 62);
  ctx.lineTo(offscreen.width - paddingX, 62);
  ctx.stroke();

  // Draw chart canvas
  const drawWidth = offscreen.width - (paddingX * 2);
  const drawHeight = srcCanvas.height;
  ctx.drawImage(srcCanvas, paddingX, headerHeight, drawWidth, drawHeight);

  // Footer metadata
  ctx.fillStyle = '#94a3b8';
  ctx.font = '11px JetBrains Mono, monospace';
  ctx.fillText('Live System & Hardware Telemetry Waveforms • High-Resolution Export', paddingX, offscreen.height - 14);

  // Trigger download
  const dataUrl = offscreen.toDataURL('image/png');
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = `${defaultFilename}_${getTimestampStr()}.png`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
  }, 250);
}

function exportChartImage(chartId) {
  const reg = CHART_REGISTRY[chartId];
  if (!reg) return;
  const chart = reg.getChart();
  if (!chart || !chart.canvas) {
    alert('Chart canvas is not available to export.');
    return;
  }
  exportCanvasWithBranding(chart.canvas, reg.title, reg.defaultFilename);
}

function exportChartCSV(chartId) {
  const reg = CHART_REGISTRY[chartId];
  if (!reg) return;
  const chart = reg.getChart();
  if (!chart || !chart.data || !chart.data.labels || chart.data.labels.length === 0) {
    alert('No telemetry waveform points available to export yet.');
    return;
  }

  const labels = chart.data.labels;
  const datasets = chart.data.datasets || [];

  if (reg.isHistogram) {
    let csv = 'Confidence Bin Range,Bin Lower,Bin Upper,Detection Count\r\n';
    const bins = datasets[0]?.data || [];
    for (let i = 0; i < 10; i++) {
      const lower = (i * 0.1).toFixed(1);
      const upper = ((i + 1) * 0.1).toFixed(1);
      const count = bins[i] || 0;
      csv += `"${lower} - ${upper}",${lower},${upper},${count}\r\n`;
    }
    downloadBlob(csv, `${reg.defaultFilename}_${getTimestampStr()}.csv`, 'text/csv;charset=utf-8;');
    return;
  }

  const header = ['Timestamp', ...datasets.map(ds => `"${(ds.label || 'Value').replace(/"/g, '""')}"`)].join(',');
  const rows = [];
  for (let i = 0; i < labels.length; i++) {
    const timeVal = `"${(labels[i] || '').toString().replace(/"/g, '""')}"`;
    const colVals = datasets.map(ds => {
      const v = ds.data[i];
      return (v !== null && v !== undefined && !isNaN(v)) ? v : '';
    });
    rows.push([timeVal, ...colVals].join(','));
  }

  const csv = [header, ...rows].join('\r\n');
  downloadBlob(csv, `${reg.defaultFilename}_${getTimestampStr()}.csv`, 'text/csv;charset=utf-8;');
}

/**
 * Single complete CSV export covering all 12 Live System & Hardware Telemetry Waveforms.
 * Intelligently exports:
 * - Full multi-channel Live Telemetry session waveforms when in Live mode
 * - Side-by-side Hailo-8L vs CPU comparative curves when in Dual Benchmark Overlay mode
 * Includes time alignment across all channels and session Confidence Histogram distribution summary.
 */
function exportCompleteWaveformsCSV() {
  const isBench = (typeof waveformViewMode !== 'undefined' && waveformViewMode === 'benchmark') ||
                  (typeof isBenchmarkWaveformsMode !== 'undefined' && isBenchmarkWaveformsMode);

  if (isBench) {
    exportCompleteBenchmarkWaveformsCSV();
  } else {
    exportCompleteLiveWaveformsCSV();
  }
}

function exportCompleteLiveWaveformsCSV() {
  const lineChartKeys = [
    'chart-latency',
    'chart-fps',
    'chart-interframe',
    'chart-detections-count',
    'chart-thermal',
    'chart-resources',
    'chart-disk',
    'chart-fan',
    'chart-cpufreq',
    'chart-voltages',
    'chart-procfootprint'
  ];

  // 1. Identify master timeline labels
  let masterLabels = [];
  for (const key of lineChartKeys) {
    const chart = CHART_REGISTRY[key]?.getChart();
    if (chart && chart.data && Array.isArray(chart.data.labels) && chart.data.labels.length > masterLabels.length) {
      masterLabels = chart.data.labels;
    }
  }

  // If no points in memory, offer backend historical waveforms fallback
  if (!masterLabels || masterLabels.length === 0) {
    if (confirm('No active in-memory telemetry waveform points found for this live session yet. Would you like to export persisted historical waveform records from the database?')) {
      window.location.href = '/api/v1/history/export/waveforms';
    }
    return;
  }

  // Helper to extract a scalar from chart with length offset compensation
  const getChartDataVal = (chart, datasetIdx, targetIdx, masterLen) => {
    if (!chart || !chart.data || !chart.data.datasets || !chart.data.datasets[datasetIdx]) return '';
    const ds = chart.data.datasets[datasetIdx];
    const offset = masterLen - (chart.data.labels ? chart.data.labels.length : 0);
    const actualIdx = targetIdx - offset;
    if (actualIdx < 0 || actualIdx >= ds.data.length) return '';
    const v = ds.data[actualIdx];
    return (v !== null && v !== undefined && !isNaN(v)) ? v : '';
  };

  // 2. Define the exact columns for each of the 12 Live Waveforms
  const colDefs = [
    {
      header: 'Timestamp',
      getVal: (i) => `"${(masterLabels[i] || '').toString().replace(/"/g, '""')}"`
    },
    {
      header: 'Elapsed_Seconds',
      getVal: (i) => i
    },
    // 1. Latency Breakdown History (ms) (chart-latency: ds[0]=exec, ds[1]=prep, ds[2]=post)
    {
      header: 'Latency_Preprocess_ms',
      getVal: (i) => getChartDataVal(latencyChart, 1, i, masterLabels.length)
    },
    {
      header: 'Latency_Accelerator_Exec_ms',
      getVal: (i) => getChartDataVal(latencyChart, 0, i, masterLabels.length)
    },
    {
      header: 'Latency_Postprocess_ms',
      getVal: (i) => getChartDataVal(latencyChart, 2, i, masterLabels.length)
    },
    {
      header: 'Latency_Total_Pipeline_ms',
      getVal: (i) => {
        const prep = getChartDataVal(latencyChart, 1, i, masterLabels.length);
        const exec = getChartDataVal(latencyChart, 0, i, masterLabels.length);
        const post = getChartDataVal(latencyChart, 2, i, masterLabels.length);
        if (prep === '' && exec === '' && post === '') return '';
        const sum = (Number(prep) || 0) + (Number(exec) || 0) + (Number(post) || 0);
        return sum > 0 ? sum.toFixed(2) : '';
      }
    },
    // 2. Processed Frames Per Second (FPS) (chart-fps: ds[0]=fps)
    {
      header: 'Processed_FPS',
      getVal: (i) => getChartDataVal(fpsChart, 0, i, masterLabels.length)
    },
    // 3. Inter-Frame Interval (ms) (chart-interframe: ds[0]=interval)
    {
      header: 'InterFrame_Interval_ms',
      getVal: (i) => getChartDataVal(interFrameChart, 0, i, masterLabels.length)
    },
    // 4. Detections Per Frame (chart-detections-count: ds[0]=count)
    {
      header: 'Detections_Per_Frame',
      getVal: (i) => getChartDataVal(detectionsCountChart, 0, i, masterLabels.length)
    },
    // 5. Thermal Profile History (°C) (chart-thermal: ds[0]=cpu, ds[1]=rp1, ds[2]=hailo)
    {
      header: 'Thermal_CPU_degC',
      getVal: (i) => getChartDataVal(thermalChart, 0, i, masterLabels.length)
    },
    {
      header: 'Thermal_RP1_degC',
      getVal: (i) => getChartDataVal(thermalChart, 1, i, masterLabels.length)
    },
    {
      header: 'Thermal_Hailo8L_NPU_degC',
      getVal: (i) => getChartDataVal(thermalChart, 2, i, masterLabels.length)
    },
    // 6. System Utilisation History (%) (chart-resources: ds[0]=cpu, ds[1]=ram)
    {
      header: 'System_CPU_Utilisation_pct',
      getVal: (i) => getChartDataVal(resourceChart, 0, i, masterLabels.length)
    },
    {
      header: 'System_RAM_Utilisation_pct',
      getVal: (i) => getChartDataVal(resourceChart, 1, i, masterLabels.length)
    },
    // 7. Disk Utilisation (%) (chart-disk: ds[0]=disk)
    {
      header: 'Disk_Utilisation_pct',
      getVal: (i) => getChartDataVal(diskChart, 0, i, masterLabels.length)
    },
    // 8. Active Cooling & Fan Speed (chart-fan: ds[0]=rpm)
    {
      header: 'Active_Cooler_Fan_Speed_RPM',
      getVal: (i) => getChartDataVal(fanChart, 0, i, masterLabels.length)
    },
    // 9. CPU Quad-Core Frequencies (MHz) (chart-cpufreq: ds[0]=c0, ds[1]=c1, ds[2]=c2, ds[3]=c3)
    {
      header: 'CPU_Freq_Core0_MHz',
      getVal: (i) => getChartDataVal(cpuFreqChart, 0, i, masterLabels.length)
    },
    {
      header: 'CPU_Freq_Core1_MHz',
      getVal: (i) => getChartDataVal(cpuFreqChart, 1, i, masterLabels.length)
    },
    {
      header: 'CPU_Freq_Core2_MHz',
      getVal: (i) => getChartDataVal(cpuFreqChart, 2, i, masterLabels.length)
    },
    {
      header: 'CPU_Freq_Core3_MHz',
      getVal: (i) => getChartDataVal(cpuFreqChart, 3, i, masterLabels.length)
    },
    // 10. RP1 Southbridge Rail Voltages (V) (chart-voltages: ds[0]=0.8V, ds[1]=1.1V, ds[2]=1.8V, ds[3]=3.3V)
    {
      header: 'RP1_Rail_0v8_Voltage_V',
      getVal: (i) => getChartDataVal(voltageChart, 0, i, masterLabels.length)
    },
    {
      header: 'RP1_Rail_1v1_Voltage_V',
      getVal: (i) => getChartDataVal(voltageChart, 1, i, masterLabels.length)
    },
    {
      header: 'RP1_Rail_1v8_Voltage_V',
      getVal: (i) => getChartDataVal(voltageChart, 2, i, masterLabels.length)
    },
    {
      header: 'RP1_Rail_3v3_Voltage_V',
      getVal: (i) => getChartDataVal(voltageChart, 3, i, masterLabels.length)
    },
    // 11. Process Footprint & System Load (chart-procfootprint: ds[0]=cpu, ds[1]=rss, ds[2]=load)
    {
      header: 'Process_CPU_pct',
      getVal: (i) => getChartDataVal(procFootprintChart, 0, i, masterLabels.length)
    },
    {
      header: 'Process_Memory_RSS_MB',
      getVal: (i) => getChartDataVal(procFootprintChart, 1, i, masterLabels.length)
    },
    {
      header: 'System_Load_Average_1m',
      getVal: (i) => getChartDataVal(procFootprintChart, 2, i, masterLabels.length)
    }
  ];

  // 3. Assemble data rows
  const headerRow = colDefs.map(c => `"${c.header.replace(/"/g, '""')}"`).join(',');
  const dataRows = [];
  for (let i = 0; i < masterLabels.length; i++) {
    const rowVals = colDefs.map(c => c.getVal(i));
    dataRows.push(rowVals.join(','));
  }

  // 4. Append Confidence Distribution Histogram summary (Chart #5)
  const confBins = (confHistChart && confHistChart.data && confHistChart.data.datasets && confHistChart.data.datasets[0])
    ? confHistChart.data.datasets[0].data
    : [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];

  const exportRows = [
    headerRow,
    ...dataRows,
    '',
    '# ==============================================================================',
    '# CONFIDENCE DISTRIBUTION HISTOGRAM (Session Cumulative Binned Detections)',
    '# ==============================================================================',
    'Confidence Bin Range,Bin Lower,Bin Upper,Detection Count'
  ];

  for (let b = 0; b < 10; b++) {
    const lower = (b * 0.1).toFixed(1);
    const upper = ((b + 1) * 0.1).toFixed(1);
    const count = confBins[b] || 0;
    exportRows.push(`"${lower} - ${upper}",${lower},${upper},${count}`);
  }

  const csvContent = exportRows.join('\r\n');
  downloadBlob(csvContent, `live_system_hardware_telemetry_waveforms_${getTimestampStr()}.csv`, 'text/csv;charset=utf-8;');
}

function exportCompleteBenchmarkWaveformsCSV() {
  const hailoPts = (typeof benchmarkData !== 'undefined' && benchmarkData.hailo) ? benchmarkData.hailo : [];
  const cpuPts = (typeof benchmarkData !== 'undefined' && benchmarkData.cpu) ? benchmarkData.cpu : [];
  const maxLen = Math.max(hailoPts.length, cpuPts.length);

  if (maxLen === 0) {
    alert('No dual benchmark comparison data points available to export yet. Please execute a benchmark run first.');
    return;
  }

  const header = [
    'Relative_Time_s',
    'Elapsed_Seconds',
    // 1. Latency Breakdown
    'Hailo8L_Latency_Exec_ms',
    'CPU_Latency_Exec_ms',
    'Hailo8L_Latency_Prep_ms',
    'CPU_Latency_Prep_ms',
    'Hailo8L_Latency_Post_ms',
    'CPU_Latency_Post_ms',
    'Hailo8L_Latency_Total_ms',
    'CPU_Latency_Total_ms',
    // 2. Processed FPS
    'Hailo8L_Processed_FPS',
    'CPU_Processed_FPS',
    // 3. Inter-Frame Interval
    'Hailo8L_InterFrame_Interval_ms',
    'CPU_InterFrame_Interval_ms',
    // 4. Detections Per Frame
    'Hailo8L_Detections_Per_Frame',
    'CPU_Detections_Per_Frame',
    // 5. Thermals
    'Hailo8L_CPU_Temp_degC',
    'CPU_CPU_Temp_degC',
    'Hailo8L_RP1_Temp_degC',
    'CPU_RP1_Temp_degC',
    'Hailo8L_NPU_Temp_degC',
    'CPU_NPU_Temp_degC',
    // 6. System Utilisation
    'Hailo8L_Host_CPU_pct',
    'CPU_Host_CPU_pct',
    'Hailo8L_Host_RAM_pct',
    'CPU_Host_RAM_pct',
    // 7. Root Disk
    'Hailo8L_Disk_Util_pct',
    'CPU_Disk_Util_pct',
    // 8. Active Cooling
    'Hailo8L_Fan_Speed_RPM',
    'CPU_Fan_Speed_RPM',
    // 9. CPU Frequencies
    'Hailo8L_CPU0_Freq_MHz',
    'CPU_CPU0_Freq_MHz',
    // 10. RP1 Southbridge Voltages
    'Hailo8L_RP1_0v8_Rail_V',
    'CPU_RP1_0v8_Rail_V',
    // 11. Process Footprint
    'Hailo8L_Process_CPU_pct',
    'CPU_Process_CPU_pct',
    'Hailo8L_Process_RSS_MB',
    'CPU_Process_RSS_MB',
    'Hailo8L_System_Load_1m',
    'CPU_System_Load_1m'
  ].map(h => `"${h}"`).join(',');

  const rows = [];
  const fmt = v => (v !== null && v !== undefined && !isNaN(v)) ? v : '';
  for (let i = 0; i < maxLen; i++) {
    const h = hailoPts[i] || {};
    const c = cpuPts[i] || {};
    rows.push([
      `"${i}s"`,
      i,
      fmt(h.latency_exec), fmt(c.latency_exec),
      fmt(h.latency_prep), fmt(c.latency_prep),
      fmt(h.latency_post), fmt(c.latency_post),
      fmt(h.latency_total), fmt(c.latency_total),
      fmt(h.fps), fmt(c.fps),
      fmt(h.interframe), fmt(c.interframe),
      fmt(h.det_count), fmt(c.det_count),
      fmt(h.cpu_temp), fmt(c.cpu_temp),
      fmt(h.rp1_temp), fmt(c.rp1_temp),
      fmt(h.hailo_temp), fmt(c.hailo_temp),
      fmt(h.cpu_util), fmt(c.cpu_util),
      fmt(h.mem_util), fmt(c.mem_util),
      fmt(h.disk_util), fmt(c.disk_util),
      fmt(h.fan_rpm), fmt(c.fan_rpm),
      fmt(h.cpu0_freq), fmt(c.cpu0_freq),
      fmt(h.v_in1), fmt(c.v_in1),
      fmt(h.proc_cpu), fmt(c.proc_cpu),
      fmt(h.proc_rss), fmt(c.proc_rss),
      fmt(h.sys_load), fmt(c.sys_load)
    ].join(','));
  }

  // Comparative Confidence Distribution
  const hConfs = (typeof benchmarkConfList !== 'undefined' && benchmarkConfList.hailo) ? benchmarkConfList.hailo : [];
  const cConfs = (typeof benchmarkConfList !== 'undefined' && benchmarkConfList.cpu) ? benchmarkConfList.cpu : [];
  const computeBins = (confs) => {
    const bins = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    if (Array.isArray(confs)) {
      confs.forEach(c => {
        if (typeof c === 'number' && !isNaN(c)) {
          let idx = Math.floor(c * 10);
          if (idx >= 10) idx = 9;
          if (idx < 0) idx = 0;
          bins[idx]++;
        }
      });
    }
    return bins;
  };
  const hBins = computeBins(hConfs);
  const cBins = computeBins(cConfs);

  const exportRows = [
    header,
    ...rows,
    '',
    '# ==============================================================================',
    '# DUAL BENCHMARK CONFIDENCE HISTOGRAM COMPARISON (Hailo-8L vs Host CPU)',
    '# ==============================================================================',
    'Confidence Bin Range,Bin Lower,Bin Upper,Hailo-8L Detections,CPU Detections'
  ];

  for (let b = 0; b < 10; b++) {
    const lower = (b * 0.1).toFixed(1);
    const upper = ((b + 1) * 0.1).toFixed(1);
    exportRows.push(`"${lower} - ${upper}",${lower},${upper},${hBins[b] || 0},${cBins[b] || 0}`);
  }

  const csv = exportRows.join('\r\n');
  downloadBlob(csv, `dual_benchmark_telemetry_waveforms_${getTimestampStr()}.csv`, 'text/csv;charset=utf-8;');
}

function openEnlargeChart(chartId) {
  const reg = CHART_REGISTRY[chartId];
  if (!reg) return;
  const srcChart = reg.getChart();
  if (!srcChart) return;

  activeEnlargedChartId = chartId;

  const modal = document.getElementById('modal-enlarge-waveform');
  const modalHeading = document.getElementById('enlarge-modal-heading');
  const modalIcon = document.getElementById('enlarge-modal-icon');
  const modalBadge = document.getElementById('enlarge-modal-badge');
  const modalDesc = document.getElementById('enlarge-modal-desc');

  if (modalHeading) modalHeading.textContent = reg.title;
  if (modalIcon) modalIcon.textContent = reg.icon || '📈';
  if (modalBadge) modalBadge.textContent = reg.badge || 'LIVE WAVEFORM';
  if (modalDesc) {
    modalDesc.innerHTML = `<span>🔍</span> <span>Large Interactive View: ${reg.desc}</span>`;
  }

  if (modal) modal.style.display = 'flex';

  const canvas = document.getElementById('chart-enlarged-canvas');
  if (!canvas) return;

  if (enlargedChart) {
    enlargedChart.destroy();
    enlargedChart = null;
  }

  const clonedDatasets = srcChart.data.datasets.map(ds => ({
    ...ds,
    data: [...ds.data],
    borderWidth: 2.4,
    pointRadius: (ds.pointRadius !== undefined && ds.pointRadius > 0) ? ds.pointRadius + 1 : (ds.data.length < 80 ? 2 : 0),
    pointHoverRadius: 6
  }));

  const chartType = srcChart.config.type || 'line';

  enlargedChart = new Chart(canvas, {
    type: chartType,
    data: {
      labels: [...srcChart.data.labels],
      datasets: clonedDatasets
    },
    options: {
      ...chartOptionsBase,
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: {
            color: '#1e293b',
            font: { family: 'Inter', size: 12, weight: '600' },
            boxWidth: 14,
            padding: 12
          }
        },
        tooltip: {
          enabled: true,
          mode: 'index',
          intersect: false,
          padding: 10,
          titleFont: { family: 'Inter', size: 12, weight: '700' },
          bodyFont: { family: 'JetBrains Mono', size: 12 }
        }
      },
      scales: {
        x: {
          display: true,
          grid: { color: 'rgba(0, 0, 0, 0.05)' },
          ticks: {
            color: '#64748b',
            font: { family: 'JetBrains Mono', size: 10 },
            maxTicksLimit: 16
          }
        },
        y: {
          ...srcChart.options.scales?.y,
          display: true,
          grid: { color: 'rgba(0, 0, 0, 0.06)' },
          ticks: {
            color: '#475569',
            font: { family: 'JetBrains Mono', size: 11 }
          }
        },
        ...(srcChart.options.scales?.y1 ? {
          y1: {
            ...srcChart.options.scales.y1,
            display: true,
            ticks: {
              color: '#f59e0b',
              font: { family: 'JetBrains Mono', size: 11 }
            }
          }
        } : {})
      }
    }
  });
}

function closeEnlargeChartModal() {
  const modal = document.getElementById('modal-enlarge-waveform');
  if (modal) modal.style.display = 'none';
  if (enlargedChart) {
    enlargedChart.destroy();
    enlargedChart = null;
  }
  activeEnlargedChartId = null;
}

function handleEnlargeModalBackdrop(event) {
  if (event.target && event.target.id === 'modal-enlarge-waveform') {
    closeEnlargeChartModal();
  }
}

function exportEnlargedChartPNG() {
  if (!activeEnlargedChartId || !enlargedChart) return;
  const reg = CHART_REGISTRY[activeEnlargedChartId];
  const title = reg ? `${reg.title} (Enlarged High-Res)` : 'Telemetry Waveform';
  const fname = reg ? `${reg.defaultFilename}_enlarged` : 'enlarged_waveform';
  exportCanvasWithBranding(enlargedChart.canvas, title, fname);
}

function exportEnlargedChartCSV() {
  if (!activeEnlargedChartId) return;
  exportChartCSV(activeEnlargedChartId);
}

// Window Escape listener to close modals
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeEnlargeChartModal();
    if (typeof closeDiagnosticsModal === 'function') closeDiagnosticsModal();
    if (typeof closeBenchmarkModal === 'function') closeBenchmarkModal();
  }
});

/* ==========================================================================
   CPU vs Hailo-8L NPU Benchmark Comparison Charts & Overlays
   ========================================================================== */

let benchFpsChart = null;
let benchLatencyChart = null;
let benchCpuChart = null;
let benchThermalChart = null;

const benchChartOptionsBase = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  elements: {
    point: { radius: 2, hoverRadius: 5 },
    line: { tension: 0.25, borderWidth: 2 }
  },
  plugins: {
    legend: {
      display: true,
      position: 'top',
      labels: {
        color: '#1e293b',
        font: { family: 'Inter', size: 11, weight: '600' },
        boxWidth: 14,
        padding: 10
      }
    },
    tooltip: {
      enabled: true,
      mode: 'index',
      intersect: false,
      titleFont: { family: 'Inter', size: 12, weight: '700' },
      bodyFont: { family: 'JetBrains Mono', size: 11 }
    }
  },
  scales: {
    x: {
      display: true,
      grid: { color: 'rgba(0, 0, 0, 0.05)' },
      ticks: {
        color: '#64748b',
        font: { family: 'JetBrains Mono', size: 10 },
        maxTicksLimit: 15
      },
      title: {
        display: true,
        text: 'Elapsed Time in Seconds (t = 0s...Ts)',
        color: '#64748b',
        font: { family: 'Inter', size: 10, weight: '600' }
      }
    },
    y: {
      display: true,
      grid: { color: 'rgba(0, 0, 0, 0.05)' },
      ticks: {
        color: '#475569',
        font: { family: 'JetBrains Mono', size: 10 }
      }
    }
  }
};

function initBenchmarkCharts() {
  const ctxFps = document.getElementById('chart-bench-fps');
  if (ctxFps && !benchFpsChart) {
    benchFpsChart = new Chart(ctxFps, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'Hailo-8L NPU (FPS)', data: [], borderColor: '#7c3aed', backgroundColor: 'rgba(124, 58, 237, 0.08)', fill: false },
          { label: 'CPU (ONNX) (FPS)', data: [], borderColor: '#ef4444', backgroundColor: 'rgba(239, 68, 68, 0.08)', borderDash: [4, 4], fill: false }
        ]
      },
      options: benchChartOptionsBase
    });
  }

  const ctxLat = document.getElementById('chart-bench-latency');
  if (ctxLat && !benchLatencyChart) {
    benchLatencyChart = new Chart(ctxLat, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'Hailo-8L Exec Latency (ms)', data: [], borderColor: '#2563eb', fill: false },
          { label: 'CPU Exec Latency (ms)', data: [], borderColor: '#dc2626', borderDash: [4, 4], fill: false }
        ]
      },
      options: benchChartOptionsBase
    });
  }

  const ctxCpu = document.getElementById('chart-bench-cpu');
  if (ctxCpu && !benchCpuChart) {
    benchCpuChart = new Chart(ctxCpu, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'Host CPU (Hailo-8L Offload) (%)', data: [], borderColor: '#16a34a', fill: false },
          { label: 'Host CPU (CPU Inference) (%)', data: [], borderColor: '#f97316', borderDash: [4, 4], fill: false }
        ]
      },
      options: benchChartOptionsBase
    });
  }

  const ctxTherm = document.getElementById('chart-bench-thermal');
  if (ctxTherm && !benchThermalChart) {
    benchThermalChart = new Chart(ctxTherm, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          { label: 'BCM2712 Temp (Hailo-8L Run) (°C)', data: [], borderColor: '#06b6d4', fill: false },
          { label: 'BCM2712 Temp (CPU Run) (°C)', data: [], borderColor: '#ec4899', borderDash: [4, 4], fill: false }
        ]
      },
      options: benchChartOptionsBase
    });
  }
}

function renderBenchmarkOverlay(hailoPts, cpuPts) {
  initBenchmarkCharts();

  const maxLen = Math.max((hailoPts ? hailoPts.length : 0), (cpuPts ? cpuPts.length : 0));
  const labels = [];
  for (let i = 0; i < maxLen; i++) {
    labels.push(`${i}s`);
  }

  const padSeries = (pts, key) => {
    if (!pts || pts.length === 0) return [];
    return pts.map(p => (p && typeof p[key] === 'number') ? p[key] : null);
  };

  // 1. Throughput (FPS)
  if (benchFpsChart) {
    benchFpsChart.data.labels = labels;
    benchFpsChart.data.datasets[0].data = padSeries(hailoPts, 'fps');
    benchFpsChart.data.datasets[1].data = padSeries(cpuPts, 'fps');
    benchFpsChart.update('none');
  }

  // 2. Latency (ms)
  if (benchLatencyChart) {
    benchLatencyChart.data.labels = labels;
    benchLatencyChart.data.datasets[0].data = padSeries(hailoPts, 'latency_exec');
    benchLatencyChart.data.datasets[1].data = padSeries(cpuPts, 'latency_exec');
    benchLatencyChart.update('none');
  }

  // 3. CPU Utilisation (%)
  if (benchCpuChart) {
    benchCpuChart.data.labels = labels;
    benchCpuChart.data.datasets[0].data = padSeries(hailoPts, 'cpu_util');
    benchCpuChart.data.datasets[1].data = padSeries(cpuPts, 'cpu_util');
    benchCpuChart.update('none');
  }

  // 4. Thermals (°C)
  if (benchThermalChart) {
    benchThermalChart.data.labels = labels;
    benchThermalChart.data.datasets[0].data = padSeries(hailoPts, 'cpu_temp');
    benchThermalChart.data.datasets[1].data = padSeries(cpuPts, 'cpu_temp');
    benchThermalChart.update('none');
  }

  // Compute KPI comparison metrics
  const avg = (arr, key) => {
    if (!arr || arr.length === 0) return 0;
    const valid = arr.map(p => p[key]).filter(v => typeof v === 'number' && !isNaN(v));
    if (valid.length === 0) return 0;
    return valid.reduce((a, b) => a + b, 0) / valid.length;
  };
  const max = (arr, key) => {
    if (!arr || arr.length === 0) return 0;
    const valid = arr.map(p => p[key]).filter(v => typeof v === 'number' && !isNaN(v));
    if (valid.length === 0) return 0;
    return Math.max(...valid);
  };

  const hFps = avg(hailoPts, 'fps');
  const cFps = avg(cpuPts, 'fps');
  const hLat = avg(hailoPts, 'latency_exec');
  const cLat = avg(cpuPts, 'latency_exec');
  const hCpu = avg(hailoPts, 'cpu_util');
  const cCpu = avg(cpuPts, 'cpu_util');
  const hTemp = max(hailoPts, 'cpu_temp');
  const cTemp = max(cpuPts, 'cpu_temp');

  const elHFps = document.getElementById('kpi-hailo-fps');
  const elCFps = document.getElementById('kpi-cpu-fps');
  const elDFps = document.getElementById('kpi-delta-fps');
  if (elHFps) elHFps.textContent = hFps > 0 ? `${hFps.toFixed(1)} FPS` : '--';
  if (elCFps) elCFps.textContent = cFps > 0 ? `${cFps.toFixed(1)} FPS` : '--';
  if (elDFps) {
    if (hFps > 0 && cFps > 0) {
      const mult = (hFps / (cFps || 1)).toFixed(1);
      elDFps.className = 'kpi-footer-badge win-hailo';
      elDFps.textContent = `⚡ ${mult}x Speedup on Hailo-8L NPU`;
    } else {
      elDFps.className = 'kpi-footer-badge';
      elDFps.textContent = '⚡ Awaiting Benchmark';
    }
  }

  const elHLat = document.getElementById('kpi-hailo-lat');
  const elCLat = document.getElementById('kpi-cpu-lat');
  const elDLat = document.getElementById('kpi-delta-lat');
  if (elHLat) elHLat.textContent = hLat > 0 ? `${hLat.toFixed(1)} ms` : '--';
  if (elCLat) elCLat.textContent = cLat > 0 ? `${cLat.toFixed(1)} ms` : '--';
  if (elDLat) {
    if (hLat > 0 && cLat > 0) {
      const red = (((cLat - hLat) / (cLat || 1)) * 100).toFixed(1);
      elDLat.className = 'kpi-footer-badge win-hailo';
      elDLat.textContent = `📉 -${red}% Lower Latency on NPU`;
    } else {
      elDLat.className = 'kpi-footer-badge';
      elDLat.textContent = '📉 Awaiting Benchmark';
    }
  }

  const elHCpu = document.getElementById('kpi-hailo-cpu');
  const elCCpu = document.getElementById('kpi-cpu-cpu');
  const elDCpu = document.getElementById('kpi-delta-cpu');
  if (elHCpu) elHCpu.textContent = hCpu > 0 ? `${hCpu.toFixed(1)}%` : '--';
  if (elCCpu) elCCpu.textContent = cCpu > 0 ? `${cCpu.toFixed(1)}%` : '--';
  if (elDCpu) {
    if (hCpu > 0 && cCpu > 0) {
      const saved = (cCpu - hCpu).toFixed(1);
      elDCpu.className = 'kpi-footer-badge win-hailo';
      elDCpu.textContent = `❄️ -${saved}% Host CPU Relieved`;
    } else {
      elDCpu.className = 'kpi-footer-badge';
      elDCpu.textContent = '❄️ Awaiting Benchmark';
    }
  }

  const elHTemp = document.getElementById('kpi-hailo-temp');
  const elCTemp = document.getElementById('kpi-cpu-temp');
  const elDTemp = document.getElementById('kpi-delta-temp');
  if (elHTemp) elHTemp.textContent = hTemp > 0 ? `${hTemp.toFixed(1)}°C` : '--';
  if (elCTemp) elCTemp.textContent = cTemp > 0 ? `${cTemp.toFixed(1)}°C` : '--';
  if (elDTemp) {
    if (hTemp > 0 && cTemp > 0) {
      const delta = (cTemp - hTemp).toFixed(1);
      elDTemp.className = 'kpi-footer-badge win-hailo';
      elDTemp.textContent = `🌡️ ${delta}°C Cooler with Offload`;
    } else {
      elDTemp.className = 'kpi-footer-badge';
      elDTemp.textContent = '🌡️ Awaiting Benchmark';
    }
  }
}

function exportBenchmarkCSV() {
  const hailoPts = (typeof benchmarkData !== 'undefined' && benchmarkData.hailo) ? benchmarkData.hailo : [];
  const cpuPts = (typeof benchmarkData !== 'undefined' && benchmarkData.cpu) ? benchmarkData.cpu : [];
  const maxLen = Math.max(hailoPts.length, cpuPts.length);

  if (maxLen === 0) {
    alert('No benchmark comparison data recorded yet. Please run the benchmark first.');
    return;
  }

  const header = [
    'Relative Time (s)',
    'Hailo-8L FPS',
    'CPU (ONNX) FPS',
    'Hailo-8L Exec Latency (ms)',
    'CPU Exec Latency (ms)',
    'Hailo-8L Total Latency (ms)',
    'CPU Total Latency (ms)',
    'Hailo-8L Host CPU (%)',
    'CPU Host CPU (%)',
    'Hailo-8L SoC Temp (C)',
    'CPU SoC Temp (C)',
    'Hailo-8L Fan RPM',
    'CPU Fan RPM',
    'Hailo-8L Process RSS (MB)',
    'CPU Process RSS (MB)'
  ].join(',');

  const rows = [];
  for (let i = 0; i < maxLen; i++) {
    const h = hailoPts[i] || {};
    const c = cpuPts[i] || {};
    const fmt = v => (v !== null && v !== undefined && !isNaN(v)) ? v : '';
    rows.push([
      `"${i}s"`,
      fmt(h.fps), fmt(c.fps),
      fmt(h.latency_exec), fmt(c.latency_exec),
      fmt(h.latency_total), fmt(c.latency_total),
      fmt(h.cpu_util), fmt(c.cpu_util),
      fmt(h.cpu_temp), fmt(c.cpu_temp),
      fmt(h.fan_rpm), fmt(c.fan_rpm),
      fmt(h.proc_rss), fmt(c.proc_rss)
    ].join(','));
  }

  const csv = [header, ...rows].join('\r\n');
  downloadBlob(csv, `hailo_vs_cpu_benchmark_comparison_${getTimestampStr()}.csv`, 'text/csv;charset=utf-8;');
}

function exportBenchmarkChartsPNG() {
  const charts = [benchFpsChart, benchLatencyChart, benchCpuChart, benchThermalChart].filter(Boolean);
  if (charts.length === 0 || !charts[0].canvas) {
    alert('Benchmark charts are not initialised yet.');
    return;
  }

  const offscreen = document.createElement('canvas');
  const cardW = 600;
  const cardH = 280;
  const padding = 20;
  const headerH = 80;
  const footerH = 35;

  offscreen.width = (cardW * 2) + (padding * 3);
  offscreen.height = headerH + (cardH * 2) + (padding * 3) + footerH;
  const ctx = offscreen.getContext('2d');

  // Background
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, offscreen.width, offscreen.height);

  // Title
  ctx.fillStyle = '#0f172a';
  ctx.font = 'bold 20px Inter, system-ui, sans-serif';
  ctx.fillText('CPU vs Hailo-8L NPU Benchmark Comparison Suite', padding, 35);

  ctx.fillStyle = '#64748b';
  ctx.font = '13px Inter, system-ui, sans-serif';
  ctx.fillText(`Edge Vision Monitor • Raspberry Pi 5 & Hailo-8L Edge AI • Aligned Relative-Time (0s...Ts) • ${new Date().toLocaleString()}`, padding, 58);

  ctx.strokeStyle = '#e2e8f0';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding, 70);
  ctx.lineTo(offscreen.width - padding, 70);
  ctx.stroke();

  // Draw 2x2 grid of charts
  const positions = [
    { x: padding, y: headerH + padding, title: 'Pipeline Throughput (FPS)' },
    { x: padding * 2 + cardW, y: headerH + padding, title: 'Execution Latency (ms)' },
    { x: padding, y: headerH + padding * 2 + cardH, title: 'Host CPU Utilisation (%)' },
    { x: padding * 2 + cardW, y: headerH + padding * 2 + cardH, title: 'SoC Temperature Profile (°C)' }
  ];

  charts.forEach((ch, idx) => {
    if (idx < positions.length && ch.canvas) {
      const pos = positions[idx];
      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(pos.x, pos.y, cardW, cardH);
      ctx.strokeStyle = '#e2e8f0';
      ctx.strokeRect(pos.x, pos.y, cardW, cardH);
      ctx.drawImage(ch.canvas, pos.x + 10, pos.y + 10, cardW - 20, cardH - 20);
    }
  });

  // Footer
  ctx.fillStyle = '#94a3b8';
  ctx.font = '11px JetBrains Mono, monospace';
  ctx.fillText('Overlaid Benchmark Telemetry Waveforms • High-Resolution Export', padding, offscreen.height - 14);

  const dataUrl = offscreen.toDataURL('image/png');
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = `hailo_vs_cpu_benchmark_overlay_${getTimestampStr()}.png`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { document.body.removeChild(a); }, 250);
}

/* ==========================================================================
   Dual Benchmark Rendering on the SAME Live Telemetry Waveforms
   ========================================================================== */

function captureLiveChartStates() {
  const chartList = [
    { id: 'latency', chart: latencyChart },
    { id: 'fps', chart: fpsChart },
    { id: 'interframe', chart: interFrameChart },
    { id: 'detCount', chart: detectionsCountChart },
    { id: 'confHist', chart: confHistChart },
    { id: 'thermal', chart: thermalChart },
    { id: 'resources', chart: resourceChart },
    { id: 'disk', chart: diskChart },
    { id: 'fan', chart: fanChart },
    { id: 'cpuFreq', chart: cpuFreqChart },
    { id: 'voltage', chart: voltageChart },
    { id: 'procFootprint', chart: procFootprintChart }
  ];

  const states = {};
  chartList.forEach(({ id, chart }) => {
    if (chart && chart.data) {
      states[id] = {
        labels: [...(chart.data.labels || [])],
        datasets: chart.data.datasets.map(ds => ({
          label: ds.label,
          data: [...(ds.data || [])],
          borderColor: ds.borderColor,
          backgroundColor: ds.backgroundColor,
          borderDash: ds.borderDash ? [...ds.borderDash] : [],
          fill: ds.fill,
          borderWidth: ds.borderWidth,
          pointRadius: ds.pointRadius,
          yAxisID: ds.yAxisID
        }))
      };
    }
  });
  return states;
}

function restoreLiveWaveforms() {
  isBenchmarkWaveformsMode = false;

  // 1. Restore chart datasets
  if (savedLiveChartStates) {
    const applyState = (chart, saved) => {
      if (!chart || !saved) return;
      chart.data.labels = [...saved.labels];
      chart.data.datasets = saved.datasets.map(ds => ({ ...ds, data: [...ds.data] }));
      if (chart.options && chart.options.scales && chart.options.scales.x) {
        if (chart.options.scales.x.ticks) chart.options.scales.x.ticks.display = (chart === confHistChart);
        if (chart.options.scales.x.title) chart.options.scales.x.title.display = false;
      }
      chart.update('none');
    };

    applyState(latencyChart, savedLiveChartStates.latency);
    applyState(fpsChart, savedLiveChartStates.fps);
    applyState(interFrameChart, savedLiveChartStates.interframe);
    applyState(detectionsCountChart, savedLiveChartStates.detCount);
    applyState(confHistChart, savedLiveChartStates.confHist);
    applyState(thermalChart, savedLiveChartStates.thermal);
    applyState(resourceChart, savedLiveChartStates.resources);
    applyState(diskChart, savedLiveChartStates.disk);
    applyState(fanChart, savedLiveChartStates.fan);
    applyState(cpuFreqChart, savedLiveChartStates.cpuFreq);
    applyState(voltageChart, savedLiveChartStates.voltage);
    applyState(procFootprintChart, savedLiveChartStates.procFootprint);
  } else {
    resetAllCharts();
  }

  // 2. Reset waveform card stat labels
  const resetText = (id, def = '--') => {
    const el = document.getElementById(id);
    if (el) el.textContent = def;
  };
  resetText('lbl-fps-stat', '-- FPS');
  resetText('lbl-inter-frame', '-- ms');
  resetText('lbl-detections-per-frame', '-- Objects');
  resetText('lbl-conf-summary', '--');
  resetText('lbl-disk-utilisation', '--%');
  resetText('lbl-fan-speed', '-- RPM');
  resetText('lbl-cpu-base-tag', '2.4 GHz Base Target');
  resetText('lbl-proc-footprint', '--');

  // 3. Hide benchmark KPI bar
  const kpiBar = document.getElementById('wb-kpi-bar');
  if (kpiBar) kpiBar.style.display = 'none';

  console.log('[WAVEFORMS] Restored live telemetry waveform streaming.');
}

function renderDualBenchmarkOnLiveWaveforms(hailoPts, cpuPts, hailoConfs = [], cpuConfs = []) {
  if (!savedLiveChartStates) {
    savedLiveChartStates = captureLiveChartStates();
  }
  isBenchmarkWaveformsMode = true;

  const hLen = hailoPts ? hailoPts.length : 0;
  const cLen = cpuPts ? cpuPts.length : 0;
  const maxLen = Math.max(hLen, cLen);

  const labels = [];
  for (let i = 0; i < maxLen; i++) {
    labels.push(`${i}s`);
  }

  const getSeries = (pts, key) => {
    if (!pts || pts.length === 0) return [];
    return pts.map(p => (p && typeof p[key] === 'number') ? p[key] : null);
  };

  const setXAxis = (chart) => {
    if (chart && chart.options && chart.options.scales && chart.options.scales.x) {
      if (!chart.options.scales.x.ticks) chart.options.scales.x.ticks = {};
      chart.options.scales.x.ticks.display = true;
      chart.options.scales.x.ticks.color = '#64748b';
      chart.options.scales.x.ticks.font = { family: 'JetBrains Mono', size: 10 };
      chart.options.scales.x.ticks.maxTicksLimit = 15;
      chart.options.scales.x.title = {
        display: true,
        text: 'Elapsed Time in Seconds (t = 0s...Ts)',
        color: '#64748b',
        font: { family: 'Inter', size: 10, weight: '600' }
      };
    }
  };

  // 1. Latency Breakdown History (ms)
  if (latencyChart) {
    latencyChart.data.labels = labels;
    latencyChart.data.datasets = [
      { label: 'Hailo-8L Exec Latency (ms)', data: getSeries(hailoPts, 'latency_exec'), borderColor: '#7c3aed', backgroundColor: 'transparent', borderWidth: 2.2, fill: false },
      { label: 'CPU Exec Latency (ms)', data: getSeries(cpuPts, 'latency_exec'), borderColor: '#ef4444', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false },
      { label: 'Hailo Total Latency (ms)', data: getSeries(hailoPts, 'latency_total'), borderColor: '#2563eb', backgroundColor: 'transparent', borderWidth: 1.5, fill: false },
      { label: 'CPU Total Latency (ms)', data: getSeries(cpuPts, 'latency_total'), borderColor: '#f97316', backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [4, 4], fill: false }
    ];
    setXAxis(latencyChart);
    latencyChart.update('none');
  }

  // 2. Processed Frames Per Second (FPS)
  if (fpsChart) {
    fpsChart.data.labels = labels;
    fpsChart.data.datasets = [
      {
        label: 'Hailo-8L NPU (FPS)',
        data: getSeries(hailoPts, 'fps'),
        borderColor: '#38bdf8',
        backgroundColor: 'rgba(56, 189, 248, 0.12)',
        fill: true,
        borderWidth: 2.2,
        tension: 0.2,
        pointRadius: 2.5,
        pointBackgroundColor: '#38bdf8'
      },
      {
        label: 'CPU (ONNX) (FPS)',
        data: getSeries(cpuPts, 'fps'),
        borderColor: '#ef4444',
        backgroundColor: 'rgba(239, 68, 68, 0.08)',
        fill: true,
        borderWidth: 2,
        borderDash: [5, 4],
        tension: 0.2,
        pointRadius: 2.5,
        pointBackgroundColor: '#ef4444'
      }
    ];
    setXAxis(fpsChart);
    fpsChart.update('none');
  }

  // 3. Inter-Frame Interval (ms)
  if (interFrameChart) {
    interFrameChart.data.labels = labels;
    interFrameChart.data.datasets = [
      { label: 'Hailo-8L Inter-Frame (ms)', data: getSeries(hailoPts, 'interframe'), borderColor: '#a78bfa', backgroundColor: 'rgba(167, 139, 250, 0.2)', borderWidth: 2, fill: false, pointRadius: 2.5 },
      { label: 'CPU Inter-Frame (ms)', data: getSeries(cpuPts, 'interframe'), borderColor: '#f43f5e', backgroundColor: 'rgba(244, 63, 94, 0.2)', borderWidth: 2, borderDash: [5, 4], fill: false, pointRadius: 2.5 }
    ];
    setXAxis(interFrameChart);
    interFrameChart.update('none');
  }

  // 4. Detections Per Frame
  if (detectionsCountChart) {
    detectionsCountChart.data.labels = labels;
    detectionsCountChart.data.datasets = [
      { label: 'Hailo-8L Detections / Frame', data: getSeries(hailoPts, 'det_count'), borderColor: '#2dd4bf', backgroundColor: 'transparent', borderWidth: 2, stepped: 'middle', fill: false },
      { label: 'CPU Detections / Frame', data: getSeries(cpuPts, 'det_count'), borderColor: '#f59e0b', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], stepped: 'middle', fill: false }
    ];
    setXAxis(detectionsCountChart);
    detectionsCountChart.update('none');
  }

  // 5. Confidence Distribution Histogram
  if (confHistChart) {
    const computeBins = (confs) => {
      const bins = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
      if (Array.isArray(confs)) {
        confs.forEach(c => {
          if (typeof c === 'number' && !isNaN(c)) {
            let idx = Math.floor(c * 10);
            if (idx >= 10) idx = 9;
            if (idx < 0) idx = 0;
            bins[idx]++;
          }
        });
      }
      return bins;
    };
    confHistChart.data.labels = ['0.0-0.1', '0.1-0.2', '0.2-0.3', '0.3-0.4', '0.4-0.5', '0.5-0.6', '0.6-0.7', '0.7-0.8', '0.8-0.9', '0.9-1.0'];
    confHistChart.data.datasets = [
      { label: 'Hailo-8L Detections', data: computeBins(hailoConfs), backgroundColor: '#38bdf8', borderRadius: 3, borderWidth: 0, barPercentage: 0.9, categoryPercentage: 0.8 },
      { label: 'CPU Detections', data: computeBins(cpuConfs), backgroundColor: '#f97316', borderRadius: 3, borderWidth: 0, barPercentage: 0.9, categoryPercentage: 0.8 }
    ];
    confHistChart.update('none');
  }

  // 6. Thermal Profile History (°C)
  if (thermalChart) {
    thermalChart.data.labels = labels;
    thermalChart.data.datasets = [
      { label: 'Hailo Run - CPU Temp (°C)', data: getSeries(hailoPts, 'cpu_temp'), borderColor: '#f59e0b', backgroundColor: 'transparent', borderWidth: 2, fill: false },
      { label: 'CPU Run - CPU Temp (°C)', data: getSeries(cpuPts, 'cpu_temp'), borderColor: '#ef4444', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false },
      { label: 'Hailo Run - RP1 Temp (°C)', data: getSeries(hailoPts, 'rp1_temp'), borderColor: '#2563eb', backgroundColor: 'transparent', borderWidth: 1.5, fill: false },
      { label: 'CPU Run - RP1 Temp (°C)', data: getSeries(cpuPts, 'rp1_temp'), borderColor: '#6366f1', backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [4, 4], fill: false },
      { label: 'Hailo-8L NPU ASIC Temp (°C)', data: getSeries(hailoPts, 'hailo_temp'), borderColor: '#10b981', backgroundColor: 'transparent', borderWidth: 2, fill: false }
    ];
    setXAxis(thermalChart);
    thermalChart.update('none');
  }

  // 7. System Utilisation History (%)
  if (resourceChart) {
    resourceChart.data.labels = labels;
    resourceChart.data.datasets = [
      { label: 'Hailo Host CPU Util (%)', data: getSeries(hailoPts, 'cpu_util'), borderColor: '#7c3aed', backgroundColor: 'transparent', borderWidth: 2.2, fill: false },
      { label: 'CPU Run CPU Util (%)', data: getSeries(cpuPts, 'cpu_util'), borderColor: '#ef4444', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false },
      { label: 'Hailo Host RAM Util (%)', data: getSeries(hailoPts, 'mem_util'), borderColor: '#2563eb', backgroundColor: 'transparent', borderWidth: 1.5, fill: false },
      { label: 'CPU Run RAM Util (%)', data: getSeries(cpuPts, 'mem_util'), borderColor: '#f59e0b', backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [4, 4], fill: false }
    ];
    setXAxis(resourceChart);
    resourceChart.update('none');
  }

  // 8. Disk Utilisation (%)
  if (diskChart) {
    diskChart.data.labels = labels;
    diskChart.data.datasets = [
      { label: 'Hailo Run Disk Util (%)', data: getSeries(hailoPts, 'disk_util'), borderColor: '#fbbf24', backgroundColor: 'transparent', borderWidth: 2, fill: false },
      { label: 'CPU Run Disk Util (%)', data: getSeries(cpuPts, 'disk_util'), borderColor: '#ea580c', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false }
    ];
    setXAxis(diskChart);
    diskChart.update('none');
  }

  // 9. Active Cooling & Fan Speed
  if (fanChart) {
    fanChart.data.labels = labels;
    fanChart.data.datasets = [
      { label: 'Hailo Run Fan Speed (RPM)', data: getSeries(hailoPts, 'fan_rpm'), borderColor: '#059669', backgroundColor: 'transparent', borderWidth: 2, fill: false },
      { label: 'CPU Run Fan Speed (RPM)', data: getSeries(cpuPts, 'fan_rpm'), borderColor: '#dc2626', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false }
    ];
    setXAxis(fanChart);
    fanChart.update('none');
  }

  // 10. CPU Quad-Core Frequencies (MHz)
  if (cpuFreqChart) {
    cpuFreqChart.data.labels = labels;
    cpuFreqChart.data.datasets = [
      { label: 'Hailo Run Core 0 Freq (MHz)', data: getSeries(hailoPts, 'cpu0_freq'), borderColor: '#2563eb', backgroundColor: 'transparent', borderWidth: 2.2, fill: false },
      { label: 'CPU Run Core 0 Freq (MHz)', data: getSeries(cpuPts, 'cpu0_freq'), borderColor: '#ef4444', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false },
      { label: 'Hailo Run Core 1-3 Avg (MHz)', data: getSeries(hailoPts, 'cpu1_freq'), borderColor: '#10b981', backgroundColor: 'transparent', borderWidth: 1.5, fill: false },
      { label: 'CPU Run Core 1-3 Avg (MHz)', data: getSeries(cpuPts, 'cpu1_freq'), borderColor: '#f59e0b', backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [4, 4], fill: false }
    ];
    setXAxis(cpuFreqChart);
    cpuFreqChart.update('none');
  }

  // 11. RP1 Southbridge Rail Voltages (V)
  if (voltageChart) {
    voltageChart.data.labels = labels;
    voltageChart.data.datasets = [
      { label: 'Hailo Run In1 Rail (V)', data: getSeries(hailoPts, 'v_in1'), borderColor: '#2563eb', backgroundColor: 'transparent', borderWidth: 2, fill: false },
      { label: 'CPU Run In1 Rail (V)', data: getSeries(cpuPts, 'v_in1'), borderColor: '#ef4444', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false },
      { label: 'Hailo Run In2 Rail (V)', data: getSeries(hailoPts, 'v_in2'), borderColor: '#10b981', backgroundColor: 'transparent', borderWidth: 1.5, fill: false },
      { label: 'CPU Run In2 Rail (V)', data: getSeries(cpuPts, 'v_in2'), borderColor: '#f59e0b', backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [4, 4], fill: false }
    ];
    setXAxis(voltageChart);
    voltageChart.update('none');
  }

  // 12. Process Footprint & System Load
  if (procFootprintChart) {
    procFootprintChart.data.labels = labels;
    procFootprintChart.data.datasets = [
      { label: 'Hailo Process CPU (%)', data: getSeries(hailoPts, 'proc_cpu'), borderColor: '#ef4444', backgroundColor: 'transparent', borderWidth: 2, fill: false, yAxisID: 'y' },
      { label: 'CPU Run Process CPU (%)', data: getSeries(cpuPts, 'proc_cpu'), borderColor: '#991b1b', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false, yAxisID: 'y' },
      { label: 'Hailo Process RAM (MB)', data: getSeries(hailoPts, 'proc_rss'), borderColor: '#2563eb', backgroundColor: 'transparent', borderWidth: 2, fill: false, yAxisID: 'y' },
      { label: 'CPU Run Process RAM (MB)', data: getSeries(cpuPts, 'proc_rss'), borderColor: '#0891b2', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false, yAxisID: 'y' },
      { label: 'Hailo System Load (1m)', data: getSeries(hailoPts, 'sys_load'), borderColor: '#f59e0b', backgroundColor: 'transparent', borderWidth: 2, fill: false, yAxisID: 'y1' },
      { label: 'CPU System Load (1m)', data: getSeries(cpuPts, 'sys_load'), borderColor: '#d97706', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 4], fill: false, yAxisID: 'y1' }
    ];
    setXAxis(procFootprintChart);
    procFootprintChart.update('none');
  }

  // Compute Summary KPI Stats
  const avg = (arr, k) => {
    if (!arr || arr.length === 0) return 0;
    const vals = arr.map(p => p[k]).filter(v => typeof v === 'number' && !isNaN(v));
    return vals.length > 0 ? (vals.reduce((a, b) => a + b, 0) / vals.length) : 0;
  };
  const max = (arr, k) => {
    if (!arr || arr.length === 0) return 0;
    const vals = arr.map(p => p[k]).filter(v => typeof v === 'number' && !isNaN(v));
    return vals.length > 0 ? Math.max(...vals) : 0;
  };

  const hFps = avg(hailoPts, 'fps');
  const cFps = avg(cpuPts, 'fps');
  const hLat = avg(hailoPts, 'latency_exec');
  const cLat = avg(cpuPts, 'latency_exec');
  const hCpu = avg(hailoPts, 'cpu_util');
  const cCpu = avg(cpuPts, 'cpu_util');
  const hTemp = max(hailoPts, 'cpu_temp');
  const cTemp = max(cpuPts, 'cpu_temp');

  // Update Card Header Stat Pills
  const elFpsPill = document.getElementById('lbl-fps-stat');
  if (elFpsPill) {
    if (hFps > 0 && cFps > 0) {
      const speedup = (hFps / (cFps || 1)).toFixed(1);
      elFpsPill.textContent = `Hailo: ${hFps.toFixed(1)} | CPU: ${cFps.toFixed(1)} FPS (${speedup}x)`;
    } else if (hFps > 0) {
      elFpsPill.textContent = `Hailo: ${hFps.toFixed(1)} FPS (Baseline)`;
    } else if (cFps > 0) {
      elFpsPill.textContent = `CPU: ${cFps.toFixed(1)} FPS`;
    }
  }

  const elInterPill = document.getElementById('lbl-inter-frame');
  if (elInterPill) {
    const hInter = avg(hailoPts, 'interframe');
    const cInter = avg(cpuPts, 'interframe');
    if (hInter > 0 && cInter > 0) {
      elInterPill.textContent = `Hailo: ${hInter.toFixed(1)}ms | CPU: ${cInter.toFixed(1)}ms`;
    }
  }

  const elFanPill = document.getElementById('lbl-fan-speed');
  if (elFanPill) {
    const hFan = avg(hailoPts, 'fan_rpm');
    const cFan = avg(cpuPts, 'fan_rpm');
    if (hFan > 0 || cFan > 0) {
      elFanPill.textContent = `Hailo: ${Math.round(hFan)} | CPU: ${Math.round(cFan)} RPM`;
    }
  }

  const elCpuFreqPill = document.getElementById('lbl-cpu-base-tag');
  if (elCpuFreqPill) elCpuFreqPill.textContent = `Overlaid t=0s...${maxLen - 1}s`;

  // Update KPI overview bar above waveforms
  const kpiBar = document.getElementById('wb-kpi-bar');
  if (kpiBar) {
    kpiBar.style.display = 'grid';
    const elFpsSpeedup = document.getElementById('wb-kpi-fps-speedup');
    const elFpsDetail = document.getElementById('wb-kpi-fps-detail');
    const elLatSpeedup = document.getElementById('wb-kpi-lat-speedup');
    const elLatDetail = document.getElementById('wb-kpi-lat-detail');
    const elCpuSaving = document.getElementById('wb-kpi-cpu-saving');
    const elCpuDetail = document.getElementById('wb-kpi-cpu-detail');
    const elTempDelta = document.getElementById('wb-kpi-temp-delta');
    const elTempDetail = document.getElementById('wb-kpi-temp-detail');

    if (hFps > 0 && cFps > 0) {
      const mult = (hFps / (cFps || 1)).toFixed(1);
      if (elFpsSpeedup) elFpsSpeedup.textContent = `⚡ ${mult}x Speedup`;
      if (elFpsDetail) elFpsDetail.textContent = `Hailo: ${hFps.toFixed(1)} FPS vs CPU: ${cFps.toFixed(1)} FPS`;
    } else {
      if (elFpsSpeedup) elFpsSpeedup.textContent = '--';
      if (elFpsDetail) elFpsDetail.textContent = `Hailo: ${hFps.toFixed(1)} FPS | CPU: ${cFps.toFixed(1)} FPS`;
    }

    if (hLat > 0 && cLat > 0) {
      const red = (cLat / (hLat || 1)).toFixed(1);
      if (elLatSpeedup) elLatSpeedup.textContent = `📉 ${red}x Faster`;
      if (elLatDetail) elLatDetail.textContent = `Hailo: ${hLat.toFixed(1)}ms vs CPU: ${cLat.toFixed(1)}ms`;
    }

    if (hCpu > 0 || cCpu > 0) {
      const saved = Math.round(cCpu - hCpu);
      if (elCpuSaving) elCpuSaving.textContent = saved > 0 ? `❄️ -${saved}% Host CPU` : `💻 ${Math.round(hCpu)}% vs ${Math.round(cCpu)}%`;
      if (elCpuDetail) elCpuDetail.textContent = `Hailo Host: ${hCpu.toFixed(1)}% vs CPU: ${cCpu.toFixed(1)}%`;
    }

    if (hTemp > 0 || cTemp > 0) {
      const delta = (cTemp - hTemp).toFixed(1);
      if (elTempDelta) elTempDelta.textContent = `🌡️ Δ ${delta}°C Cooler`;
      if (elTempDetail) elTempDetail.textContent = `Hailo Max: ${hTemp.toFixed(1)}°C vs CPU: ${cTemp.toFixed(1)}°C`;
    }
  }

  // Also sync modal overlay charts if initialised
  if (typeof renderBenchmarkOverlay === 'function') {
    renderBenchmarkOverlay(hailoPts, cpuPts);
  }

  console.log(`[WAVEFORMS] Rendered dual benchmark overlay directly onto the 12 live telemetry waveforms (${maxLen}s).`);
}

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', initCharts);
} else {
  initCharts();
}
