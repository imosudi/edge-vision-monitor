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
}

function updateChartSeries(chart, label, values) {
  if (!chart) return;
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

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', initCharts);
} else {
  initCharts();
}
