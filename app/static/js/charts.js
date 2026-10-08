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
        color: '#94a3b8',
        font: { family: 'Inter', size: 11 },
        boxWidth: 10
      }
    }
  },
  scales: {
    x: {
      grid: { color: 'rgba(255, 255, 255, 0.05)' },
      ticks: { display: false }
    },
    y: {
      grid: { color: 'rgba(255, 255, 255, 0.05)' },
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
          { label: 'NPU Exec (ms)', data: [], borderColor: '#00f0ff', backgroundColor: 'rgba(0, 240, 255, 0.1)', fill: false },
          { label: 'Preprocess (ms)', data: [], borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)', fill: false },
          { label: 'Postprocess (ms)', data: [], borderColor: '#8b5cf6', backgroundColor: 'rgba(139, 92, 246, 0.1)', fill: false }
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
          { label: 'Inference FPS', data: [], borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)', fill: true }
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
          { label: 'RP1 Temp (°C)', data: [], borderColor: '#00f0ff', backgroundColor: 'transparent' },
          { label: 'Hailo NPU (°C)', data: [], borderColor: '#10b981', backgroundColor: 'transparent' }
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
          { label: 'CPU Util (%)', data: [], borderColor: '#8b5cf6', backgroundColor: 'transparent' },
          { label: 'RAM Util (%)', data: [], borderColor: '#00f0ff', backgroundColor: 'transparent' }
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
