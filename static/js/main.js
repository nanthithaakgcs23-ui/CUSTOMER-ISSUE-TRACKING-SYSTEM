
// Client-side enhancement for simple validation and better UX.
document.addEventListener("DOMContentLoaded", function () {
    document.body.classList.add("page-loaded");

    var themeToggle = document.getElementById("theme-toggle");
    var body = document.body;
    var storedTheme = localStorage.getItem("theme");

    function applyTheme(theme) {
        if (theme === "dark") {
            body.setAttribute("data-theme", "dark");
            if (themeToggle) {
                themeToggle.textContent = "Light Mode";
            }
        } else {
            body.removeAttribute("data-theme");
            if (themeToggle) {
                themeToggle.textContent = "Dark Mode";
            }
        }
    }

    applyTheme(storedTheme || "light");

    if (themeToggle) {
        themeToggle.addEventListener("click", function () {
            var nextTheme = body.getAttribute("data-theme") === "dark" ? "light" : "dark";
            localStorage.setItem("theme", nextTheme);
            applyTheme(nextTheme);
        });
    }

    var issueForm = document.getElementById("issue-form");
    var issueItems = document.querySelectorAll(".issue-item");
    var compactToggles = document.querySelectorAll(".table-compact-toggle");
    var revealTargets = document.querySelectorAll(".card, .landing-stat, .feature-card, .issue-item, .table-wrap");
    var tableRows = document.querySelectorAll("tbody tr");
    var duplicateWarningBox = document.getElementById("duplicate-warning");

    if (issueForm) {
        var attachmentsPreview = document.getElementById("attachment-preview");
        var attachmentInput = document.getElementById("attachments");
        var titleInput = document.getElementById("title");
        var descriptionInput = document.getElementById("description");
        var categoryInput = issueForm.querySelector("select[name='category']");
        var duplicateTimer = null;
        var hasDuplicateBlocked = false;

        if (attachmentInput && attachmentsPreview) {
            attachmentInput.addEventListener("change", function () {
                var lines = [];
                for (var i = 0; i < attachmentInput.files.length; i += 1) {
                    var file = attachmentInput.files[i];
                    lines.push((i + 1) + ". " + file.name + " (" + Math.ceil(file.size / 1024) + " KB)");
                }
                attachmentsPreview.innerHTML = lines.length
                    ? "<strong>Selected files:</strong><br>" + lines.join("<br>")
                    : "";
            });
        }

        issueForm.addEventListener("submit", function (event) {
            var title = document.getElementById("title");
            var description = document.getElementById("description");
            var attachments = document.getElementById("attachments");

            if (title && title.value.trim().length < 5) {
                alert("Issue title must be at least 5 characters long.");
                event.preventDefault();
                return;
            }

            if (description && description.value.trim().length < 15) {
                alert("Description must be at least 15 characters long.");
                event.preventDefault();
                return;
            }

            if (attachments && attachments.files.length > 5) {
                alert("You can upload up to 5 files only.");
                event.preventDefault();
                return;
            }

            if (attachments) {
                for (var i = 0; i < attachments.files.length; i += 1) {
                    if (attachments.files[i].size > 5 * 1024 * 1024) {
                        alert("Each file must be 5 MB or smaller.");
                        event.preventDefault();
                        return;
                    }
                }
            }
        });

        function renderDuplicateWarning(items, blocked) {
            if (!duplicateWarningBox) {
                return;
            }
            if (!items.length) {
                duplicateWarningBox.hidden = true;
                duplicateWarningBox.innerHTML = "";
                hasDuplicateBlocked = false;
                return;
            }
            hasDuplicateBlocked = Boolean(blocked);
            var listItems = items.map(function (item) {
                return "<li><strong>" + item.title + "</strong> (" + item.status + ", " + item.created_at + ")</li>";
            }).join("");
            var header = "<strong>Similar issue(s) found:</strong> submission is blocked.";
            duplicateWarningBox.innerHTML = header + "<ul>" + listItems + "</ul>";
            duplicateWarningBox.hidden = false;
            duplicateWarningBox.classList.toggle("duplicate-block", hasDuplicateBlocked);
        }

        function checkDuplicates() {
            if (!titleInput || !titleInput.value || titleInput.value.trim().length < 4) {
                renderDuplicateWarning([]);
                return;
            }
            var formData = new FormData();
            formData.append("title", titleInput.value.trim());
            if (descriptionInput) {
                formData.append("description", descriptionInput.value.trim());
            }
            if (categoryInput) {
                formData.append("category", categoryInput.value || "");
            }
            fetch("/issues/check-duplicate", {
                method: "POST",
                body: formData,
            })
                .then(function (response) { return response.json(); })
                .then(function (data) {
                    renderDuplicateWarning((data && data.duplicates) || [], data && data.blocked);
                })
                .catch(function () {
                    renderDuplicateWarning([], false);
                });
        }

        if (titleInput) {
            titleInput.addEventListener("input", function () {
                clearTimeout(duplicateTimer);
                duplicateTimer = setTimeout(checkDuplicates, 350);
            });
        }
        if (categoryInput) {
            categoryInput.addEventListener("change", checkDuplicates);
        }
        if (descriptionInput) {
            descriptionInput.addEventListener("input", function () {
                clearTimeout(duplicateTimer);
                duplicateTimer = setTimeout(checkDuplicates, 350);
            });
        }

        issueForm.addEventListener("submit", function (event) {
            if (hasDuplicateBlocked) {
                alert("Similar issue found. Submit blocked.");
                event.preventDefault();
            }
        });
    }

    if (issueItems.length) {
        function setActiveIssue(activeItem) {
            issueItems.forEach(function (item) {
                var isActive = item === activeItem;
                item.classList.toggle("is-active", isActive);
                item.setAttribute("aria-expanded", isActive ? "true" : "false");
            });
        }

        issueItems.forEach(function (item) {
            item.addEventListener("click", function () {
                var isAlreadyActive = item.classList.contains("is-active");
                if (isAlreadyActive) {
                    item.classList.remove("is-active");
                    item.setAttribute("aria-expanded", "false");
                    return;
                }
                setActiveIssue(item);
            });

            item.addEventListener("keydown", function (event) {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    item.click();
                }
            });
        });
    }

    if (compactToggles.length) {
        compactToggles.forEach(function (toggleButton) {
            toggleButton.addEventListener("click", function () {
                var targetId = toggleButton.getAttribute("data-target");
                var table = document.getElementById(targetId);
                if (!table) {
                    return;
                }

                var compactEnabled = table.classList.toggle("table-compact");
                toggleButton.textContent = compactEnabled ? "Normal Mode" : "Compact Mode";
            });
        });
    }

    if (revealTargets.length && "IntersectionObserver" in window) {
        revealTargets.forEach(function (target, index) {
            target.classList.add("reveal-item");
            target.style.setProperty("--delay", String(index % 8));
        });

        var observer = new IntersectionObserver(function (entries, obs) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-visible");
                    obs.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12 });

        revealTargets.forEach(function (target) {
            observer.observe(target);
        });
    }

    if (tableRows.length) {
        tableRows.forEach(function (row, index) {
            row.classList.add("table-row-animate");
            row.style.setProperty("--row-delay", String(index % 12));
        });
    }
});

