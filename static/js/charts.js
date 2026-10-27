/* Chart.js helpers. Data is embedded by Django with the json_script filter. */
(function () {
  "use strict";
  if (!window.Chart) return;

  var dark = document.body.classList.contains("theme-admin");
  var palette = dark
    ? ["#60A5FA", "#A78BFA", "#34D399", "#FBBF24", "#FB7185", "#22D3EE", "#F472B6"]
    : ["#2563EB", "#16A34A", "#F59E0B", "#DC2626", "#0891B2", "#7C3AED", "#64748B"];
  var statusColors = {
    Scheduled: dark ? "#60A5FA" : "#2563EB",
    Confirmed: dark ? "#22D3EE" : "#0891B2",
    Completed: dark ? "#34D399" : "#16A34A",
    Cancelled: dark ? "#6B7280" : "#94A3B8",
    "No-show": dark ? "#FBBF24" : "#F59E0B",
    Occupied: dark ? "#FB7185" : "#DC2626",
    Available: dark ? "#34D399" : "#16A34A",
    Maintenance: dark ? "#FBBF24" : "#F59E0B",
  };

  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = dark ? "#9CA3AF" : "#64748B";
  Chart.defaults.borderColor = dark ? "rgba(148,163,184,.12)" : "#E2E8F0";
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.maintainAspectRatio = false;

  function readData(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }

  function colorsFor(labels) {
    return labels.map(function (label, i) { return statusColors[label] || palette[i % palette.length]; });
  }

  window.HMSCharts = {
    bar: function (canvasId, dataId, opts) {
      var data = readData(dataId), canvas = document.getElementById(canvasId);
      if (!data || !canvas) return;
      opts = opts || {};
      new Chart(canvas, {
        type: "bar",
        data: {
          labels: data.labels,
          datasets: [{
            label: opts.label || "",
            data: data.values,
            backgroundColor: opts.multicolor ? colorsFor(data.labels) : palette[0],
            borderRadius: 8,
            maxBarThickness: 42,
          }],
        },
        options: {
          plugins: { legend: { display: false }, tooltip: { callbacks: opts.money ? { label: function (c) { return " " + (opts.currency || "") + c.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2 }); } } : {} } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { grid: { display: false } } },
        },
      });
    },
    line: function (canvasId, dataId, opts) {
      var data = readData(dataId), canvas = document.getElementById(canvasId);
      if (!data || !canvas) return;
      opts = opts || {};
      var ctx = canvas.getContext("2d");
      var gradient = ctx.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 280);
      gradient.addColorStop(0, dark ? "rgba(96,165,250,.35)" : "rgba(37,99,235,.25)");
      gradient.addColorStop(1, "rgba(37,99,235,0)");
      new Chart(canvas, {
        type: "line",
        data: {
          labels: data.labels,
          datasets: [{
            label: opts.label || "",
            data: data.values,
            borderColor: palette[0],
            backgroundColor: gradient,
            fill: true,
            tension: .35,
            pointRadius: 3,
            pointBackgroundColor: palette[0],
          }],
        },
        options: {
          plugins: { legend: { display: false }, tooltip: { callbacks: opts.money ? { label: function (c) { return " " + (opts.currency || "") + c.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2 }); } } : {} } },
          scales: { y: { beginAtZero: true }, x: { grid: { display: false } } },
        },
      });
    },
    doughnut: function (canvasId, dataId) {
      var data = readData(dataId), canvas = document.getElementById(canvasId);
      if (!data || !canvas) return;
      new Chart(canvas, {
        type: "doughnut",
        data: { labels: data.labels, datasets: [{ data: data.values, backgroundColor: colorsFor(data.labels), borderWidth: 0, hoverOffset: 6 }] },
        options: { cutout: "68%", plugins: { legend: { position: "bottom" } } },
      });
    },
  };
})();
