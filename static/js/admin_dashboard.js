document.addEventListener("DOMContentLoaded", function () {
    var chartRoot = document.getElementById("admin-dashboard-charts");
    if (!chartRoot || typeof Chart === "undefined") {
        return;
    }

    var textColor = getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || "#1f2937";
    var gridColor = "rgba(148, 163, 184, 0.18)";

    function parseChartData(attributeName) {
        try {
            return JSON.parse(chartRoot.getAttribute(attributeName) || "{}");
        } catch (error) {
            return { labels: [], values: [] };
        }
    }

    var summary = parseChartData("data-summary");
    var status = parseChartData("data-status");
    var priority = parseChartData("data-priority");
    var trend = parseChartData("data-trend");

    var summaryCanvas = document.getElementById("issueSummaryChart");
    var statusCanvas = document.getElementById("issueStatusChart");
    var trendCanvas = document.getElementById("issueTrendChart");

    if (summaryCanvas) {
        new Chart(summaryCanvas, {
            type: "bar",
            data: {
                labels: summary.labels,
                datasets: [{
                    data: summary.values,
                    backgroundColor: ["#2563eb", "#f59e0b", "#10b981"],
                    borderRadius: 10,
                    borderSkipped: false,
                    maxBarThickness: 56,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0, color: textColor },
                        grid: { color: gridColor },
                    },
                    x: {
                        ticks: { color: textColor },
                        grid: { display: false },
                    },
                },
            },
        });
    }

    if (statusCanvas) {
        new Chart(statusCanvas, {
            type: "pie",
            data: {
                labels: status.labels,
                datasets: [{
                    data: status.values,
                    backgroundColor: ["#3b82f6", "#f59e0b", "#10b981"],
                    borderWidth: 0,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            color: textColor,
                            usePointStyle: true,
                            padding: 16,
                        },
                    },
                },
            },
        });
    }

    if (trendCanvas) {
        new Chart(trendCanvas, {
            type: "line",
            data: {
                labels: trend.labels,
                datasets: [{
                    label: "Issues Created",
                    data: trend.values,
                    borderColor: "#38bdf8",
                    backgroundColor: "rgba(56, 189, 248, 0.18)",
                    fill: true,
                    tension: 0.35,
                    pointRadius: 4,
                    pointHoverRadius: 5,
                    pointBackgroundColor: "#38bdf8",
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: {
                            color: textColor,
                        },
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0, color: textColor },
                        grid: { color: gridColor },
                    },
                    x: {
                        ticks: { color: textColor },
                        grid: { color: "rgba(148, 163, 184, 0.1)" },
                    },
                },
            },
        });
    }
});
