
document.addEventListener("DOMContentLoaded", function () {
    var canvas = document.getElementById("issueChart");
    if (!canvas || typeof Chart === "undefined") {
        return;
    }

    var total = Number(canvas.dataset.total || 0);
    var open = Number(canvas.dataset.open || 0);
    var resolved = Number(canvas.dataset.resolved || 0);

    var values = [total, open, resolved];

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: ["Total", "Open/In Progress", "Resolved"],
            datasets: [{
                data: values,
                backgroundColor: ["#2563eb", "#f59e0b", "#10b981"],
                borderRadius: 8,
                borderSkipped: false,
                maxBarThickness: 64,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false,
                },
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision: 0,
                    },
                    grid: {
                        color: "rgba(31, 41, 55, 0.08)",
                    },
                },
                x: {
                    grid: {
                        display: false,
                    },
                },
            },
        },
    });
});
