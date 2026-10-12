/**
 * Real-time Chart.js telemetry charts initialisation and streaming updates.
 */

const MAX_CHART_POINTS = 30;

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

function initCharts() {
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

window.addEventListener('DOMContentLoaded', initCharts);
