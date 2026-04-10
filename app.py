
from functools import wraps
from pathlib import Path
import csv
import io
import json
import time
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, Response, jsonify
from flask_mysqldb import MySQL
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Flask app setup
app = Flask(__name__)
app.secret_key = "replace_with_a_secure_secret_key"

# MySQL configuration (update these values for your local setup)
app.config["MYSQL_HOST"] = "localhost"
app.config["MYSQL_USER"] = "root"
app.config["MYSQL_PASSWORD"] = "Nandhu@0105"
app.config["MYSQL_DB"] = "customer_issue_tracking"
app.config["MYSQL_CURSORCLASS"] = "DictCursor"

# Upload configuration
UPLOAD_FOLDER = Path("uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "doc", "docx", "txt"}
MAX_FILES_PER_ISSUE = 5
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

# Ensure uploads folder exists
UPLOAD_FOLDER.mkdir(exist_ok=True)

mysql = MySQL(app)
serializer = URLSafeTimedSerializer(app.secret_key)


def init_optional_tables():
    """Create optional extension tables if they do not exist."""
    cur = mysql.connection.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS issue_ratings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            issue_id INT NOT NULL UNIQUE,
            user_id INT NOT NULL,
            rating TINYINT NOT NULL,
            feedback TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_issue_ratings_issue FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE,
            CONSTRAINT fk_issue_ratings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            recipient_user_id INT NOT NULL,
            recipient_role ENUM('customer', 'admin') NOT NULL,
            issue_id INT,
            message VARCHAR(255) NOT NULL,
            is_read TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_notifications_user FOREIGN KEY (recipient_user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT fk_notifications_issue FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE
        )
        """
    )
    mysql.connection.commit()
    cur.close()


def allowed_file(filename: str) -> bool:
    """Return True if file extension is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_size(file) -> int:
    """Safely calculate file size without consuming file content."""
    current_position = file.stream.tell()
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(current_position)
    return size


def parse_attachments(file_path_value):
    """Convert DB file_path field into a list of attachment names."""
    if not file_path_value:
        return []

    if isinstance(file_path_value, str):
        value = file_path_value.strip()
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return [value]
        if "|" in value:
            return [item for item in value.split("|") if item]
        return [value]

    return []


def attach_files_to_issues(issues):
    """Inject attachments list into issue dict objects for template rendering."""
    for issue in issues:
        issue["attachments"] = parse_attachments(issue.get("file_path"))


def create_notification(message: str, recipient_role: str, recipient_user_id: int, issue_id: int | None = None):
    """Persist a notification for a specific user."""
    cur = mysql.connection.cursor()
    cur.execute(
        """
        INSERT INTO notifications (recipient_user_id, recipient_role, issue_id, message)
        VALUES (%s, %s, %s, %s)
        """,
        (recipient_user_id, recipient_role, issue_id, message),
    )
    cur.close()


def notify_all_admins(message: str, issue_id: int | None = None):
    """Fan out one notification to every admin account."""
    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM users WHERE role = 'admin'")
    admins = cur.fetchall()

    if admins:
        cur.executemany(
            """
            INSERT INTO notifications (recipient_user_id, recipient_role, issue_id, message)
            VALUES (%s, 'admin', %s, %s)
            """,
            [(admin["id"], issue_id, message) for admin in admins],
        )

    cur.close()


def get_notification_link(role: str) -> str:
    """Return the destination page for role-specific notifications."""
    return url_for("admin_issues") if role == "admin" else url_for("customer_issues")


def get_recent_notifications(role: str, user_id: int, limit: int = 6):
    """Fetch recent notifications for a specific signed-in user."""
    safe_limit = max(1, min(limit, 10))
    cur = mysql.connection.cursor()
    cur.execute(
        f"""
        SELECT id, message, is_read, created_at, issue_id
        FROM notifications
        WHERE recipient_role = %s AND recipient_user_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT {safe_limit}
        """,
        (role, user_id),
    )
    notifications = cur.fetchall()
    cur.close()
    return notifications


def get_unread_notification_count(role: str, user_id: int) -> int:
    """Return unread notification count for header badge display."""
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS unread_total
        FROM notifications
        WHERE recipient_role = %s AND recipient_user_id = %s AND is_read = 0
        """,
        (role, user_id),
    )
    unread_total = cur.fetchone()["unread_total"]
    cur.close()
    return unread_total


def mark_notifications_read(role: str, user_id: int):
    """Mark all unread notifications as read for the current user."""
    cur = mysql.connection.cursor()
    cur.execute(
        """
        UPDATE notifications
        SET is_read = 1
        WHERE recipient_role = %s AND recipient_user_id = %s AND is_read = 0
        """,
        (role, user_id),
    )
    cur.close()


def serialize_notifications(notifications, role: str):
    """Prepare notifications for templates and JSON responses."""
    link = get_notification_link(role)
    serialized = []
    for notification in notifications:
        serialized.append(
            {
                "id": notification["id"],
                "message": notification["message"],
                "issue_id": notification.get("issue_id"),
                "is_read": bool(notification["is_read"]),
                "created_at": notification["created_at"].strftime("%Y-%m-%d %H:%M"),
                "link": link,
            }
        )
    return serialized


def login_required(role=None):
    """Protect routes and optionally enforce a specific role."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("customer_login"))

            if role and session.get("role") != role:
                flash("You are not authorized to access this page.", "danger")
                return redirect(url_for("home"))

            return func(*args, **kwargs)
        return wrapper
    return decorator


def generate_reset_token(user_id: int, email: str) -> str:
    """Generate a time-limited reset token for password reset."""
    return serializer.dumps({"user_id": user_id, "email": email}, salt="password-reset")


def verify_reset_token(token: str, max_age_seconds: int = 1800):
    """Validate reset token and return payload or None."""
    try:
        data = serializer.loads(token, salt="password-reset", max_age=max_age_seconds)
        return data
    except (BadSignature, SignatureExpired):
        return None


@app.route("/")
def home():
    """Public landing page and role-based redirect."""
    if session.get("role") == "customer":
        return redirect(url_for("customer_dashboard"))
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("customer_login"))


@app.before_request
def ensure_optional_tables():
    """Ensure extension tables are available."""
    if not app.config.get("_OPTIONAL_TABLES_READY"):
        init_optional_tables()
        app.config["_OPTIONAL_TABLES_READY"] = True


@app.context_processor
def inject_notification_context():
    """Expose unread notification count for the signed-in user."""
    if "user_id" not in session or "role" not in session:
        return {"unread_notification_count": 0}

    return {
        "unread_notification_count": get_unread_notification_count(
            session["role"],
            session["user_id"],
        )
    }


@app.route("/register", methods=["GET", "POST"])
def register():
    """Customer registration route."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing_user = cur.fetchone()

        if existing_user:
            flash("Email is already registered.", "warning")
            cur.close()
            return render_template("register.html")

        hashed_password = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s)",
            (name, email, hashed_password, "customer"),
        )
        mysql.connection.commit()
        cur.close()

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("customer_login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def customer_login():
    """Customer login route."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s AND role = %s", (email, "customer"))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            flash("Welcome back!", "success")
            return redirect(url_for("customer_dashboard"))

        flash("Invalid customer credentials.", "danger")

    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Generate password reset link for a registered user email."""
    reset_link = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not email:
            flash("Please enter your registered email.", "danger")
            return render_template("forgot_password.html")

        cur = mysql.connection.cursor()
        cur.execute("SELECT id, email FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()

        # Always show generic success message to avoid account enumeration.
        if user:
            token = generate_reset_token(user["id"], user["email"])
            reset_link = url_for("reset_password", token=token, _external=True)
            flash("Password reset link generated successfully.", "info")
            # Optional server-side visibility for development mode.
            print(f"[Password Reset Link] {reset_link}")
        else:
            flash("If the email is registered, a reset link has been generated.", "info")

        return render_template("forgot_password.html", reset_link=reset_link)

    return render_template("forgot_password.html", reset_link=reset_link)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Reset user password using a signed token link."""
    data = verify_reset_token(token)
    if not data:
        flash("Reset link is invalid or expired. Please request a new one.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not password or len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("reset_password.html", token=token)

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("reset_password.html", token=token)

        cur = mysql.connection.cursor()
        cur.execute(
            "UPDATE users SET password = %s WHERE id = %s",
            (generate_password_hash(password), data["user_id"]),
        )
        mysql.connection.commit()
        cur.close()

        flash("Password reset successful. Please log in.", "success")
        return redirect(url_for("customer_login"))

    return render_template("reset_password.html", token=token)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin login route."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s AND role = %s", (email, "admin"))
        admin = cur.fetchone()
        cur.close()

        if admin:
            password_ok = False

            # Normal path: hashed password validation.
            if admin["password"].startswith(("pbkdf2:", "scrypt:")):
                password_ok = check_password_hash(admin["password"], password)
            else:
                # Compatibility path for first-time seeded admin password.
                password_ok = admin["password"] == password
                if password_ok:
                    cur = mysql.connection.cursor()
                    cur.execute(
                        "UPDATE users SET password = %s WHERE id = %s",
                        (generate_password_hash(password), admin["id"]),
                    )
                    mysql.connection.commit()
                    cur.close()

            if password_ok:
                session["user_id"] = admin["id"]
                session["name"] = admin["name"]
                session["role"] = admin["role"]
                flash("Admin login successful.", "success")
                return redirect(url_for("admin_dashboard"))

        flash("Invalid admin credentials.", "danger")

    return render_template("admin_login.html")


@app.route("/logout")
def logout():
    """Clear session for both customer and admin."""
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("home"))


@app.route("/customer/dashboard")
@login_required(role="customer")
def customer_dashboard():
    """Show customer summary and recent issues."""
    cur = mysql.connection.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM issues WHERE user_id = %s", (session["user_id"],))
    total_issues = cur.fetchone()["total"]

    cur.execute(
        "SELECT COUNT(*) AS open_count FROM issues WHERE user_id = %s AND status IN ('Open', 'In Progress')",
        (session["user_id"],),
    )
    active_issues = cur.fetchone()["open_count"]

    cur.execute(
        "SELECT * FROM issues WHERE user_id = %s ORDER BY created_at DESC LIMIT 5",
        (session["user_id"],),
    )
    recent_issues = cur.fetchall()

    cur.close()
    notifications = serialize_notifications(
        get_recent_notifications("customer", session["user_id"]),
        "customer",
    )

    return render_template(
        "customer_dashboard.html",
        total_issues=total_issues,
        active_issues=active_issues,
        recent_issues=recent_issues,
        notifications=notifications,
    )


@app.route("/issues/new", methods=["GET", "POST"])
@login_required(role="customer")
def create_issue():
    """Create a new issue with optional multi-file upload."""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        priority = request.form.get("priority", "").strip()
        description = request.form.get("description", "").strip()
        files = request.files.getlist("attachments")

        if not title or not category or not priority or not description:
            flash("Please fill in all required fields.", "danger")
            return render_template("create_issue.html")

        # Hard duplicate detection by exact normalized match.
        normalized_title = " ".join(title.lower().split())
        normalized_description = " ".join(description.lower().split())

        cur = mysql.connection.cursor()
        cur.execute(
            """
            SELECT id, title, status, created_at
            FROM issues
            WHERE user_id = %s
              AND LOWER(TRIM(title)) = %s
              AND LOWER(TRIM(description)) = %s
              AND category = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session["user_id"], normalized_title, normalized_description, category),
        )
        exact_duplicate = cur.fetchone()
        cur.close()
        if exact_duplicate:
            flash("Duplicate blocked: the same issue already exists.", "danger")
            return render_template("create_issue.html")

        # Hard block for similar issues by title match (same customer).
        cur = mysql.connection.cursor()
        cur.execute(
            """
            SELECT id, title, status, created_at
            FROM issues
            WHERE user_id = %s
              AND (
                LOWER(title) LIKE %s
                OR LOWER(description) LIKE %s
              )
            ORDER BY created_at DESC
            LIMIT 3
            """,
            (session["user_id"], f"%{normalized_title}%", f"%{normalized_title}%"),
        )
        possible_duplicates = cur.fetchall()
        cur.close()
        if possible_duplicates:
            flash("Similar issue found. Submission blocked to avoid duplicate tickets.", "danger")
            return render_template("create_issue.html")

        uploaded_files = []
        selected_files = [f for f in files if f and f.filename]
        if len(selected_files) > MAX_FILES_PER_ISSUE:
            flash(f"You can upload up to {MAX_FILES_PER_ISSUE} files only.", "danger")
            return render_template("create_issue.html")

        for file in selected_files:
            if not allowed_file(file.filename):
                flash("One or more files have an invalid type.", "danger")
                return render_template("create_issue.html")

            if get_file_size(file) > MAX_FILE_SIZE_BYTES:
                flash("Each file must be 5 MB or smaller.", "danger")
                return render_template("create_issue.html")

            safe_name = secure_filename(file.filename)
            file_name = f"{int(time.time())}_{safe_name}"
            file.save(UPLOAD_FOLDER / file_name)
            uploaded_files.append(file_name)

        cur = mysql.connection.cursor()
        cur.execute(
            """
            INSERT INTO issues (user_id, title, category, priority, description, status, remark, file_path, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                session["user_id"],
                title,
                category,
                priority,
                description,
                "Open",
                "",
                json.dumps(uploaded_files) if uploaded_files else None,
            ),
        )
        issue_id = cur.lastrowid
        notify_all_admins(
            f"New issue submitted by {session['name']}: {title}",
            issue_id=issue_id,
        )
        mysql.connection.commit()
        cur.close()

        flash("Issue submitted successfully.", "success")
        return redirect(url_for("customer_issues"))

    return render_template("create_issue.html")


@app.route("/customer/issues")
@login_required(role="customer")
def customer_issues():
    """List all issues submitted by the logged-in customer."""
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()
    sort_by = request.args.get("sort_by", "created_at").strip()
    sort_dir = request.args.get("sort_dir", "desc").strip().lower()
    sort_dir_sql = "ASC" if sort_dir == "asc" else "DESC"
    allowed_sort = {
        "created_at": "created_at",
        "priority": "FIELD(priority, 'Low', 'Medium', 'High', 'Critical')",
        "status": "FIELD(status, 'Open', 'In Progress', 'Resolved')",
        "title": "title",
    }
    sort_expr = allowed_sort.get(sort_by, "created_at")

    query = "SELECT * FROM issues WHERE user_id = %s"
    params = [session["user_id"]]

    if status_filter:
        query += " AND status = %s"
        params.append(status_filter)

    if priority_filter:
        query += " AND priority = %s"
        params.append(priority_filter)

    query += f" ORDER BY {sort_expr} {sort_dir_sql}"

    cur = mysql.connection.cursor()
    cur.execute(query, tuple(params))
    issues = cur.fetchall()
    issue_ids = [issue["id"] for issue in issues]

    ratings_by_issue = {}
    if issue_ids:
        placeholders = ", ".join(["%s"] * len(issue_ids))
        cur.execute(
            f"SELECT issue_id, rating, feedback FROM issue_ratings WHERE issue_id IN ({placeholders})",
            tuple(issue_ids),
        )
        ratings = cur.fetchall()
        ratings_by_issue = {row["issue_id"]: row for row in ratings}
    cur.close()
    attach_files_to_issues(issues)

    for issue in issues:
        issue["rating_data"] = ratings_by_issue.get(issue["id"])

    return render_template(
        "customer_issues.html",
        issues=issues,
        sort_by=sort_by,
        sort_dir=sort_dir,
        status_filter=status_filter,
        priority_filter=priority_filter,
    )


@app.route("/issues/<int:issue_id>/rate", methods=["POST"])
@login_required(role="customer")
def rate_issue(issue_id):
    """Allow customer to rate resolved tickets once."""
    rating = request.form.get("rating", "").strip()
    feedback = request.form.get("feedback", "").strip()

    try:
        rating_value = int(rating)
    except ValueError:
        flash("Please select a valid rating.", "danger")
        return redirect(url_for("customer_issues"))

    if rating_value < 1 or rating_value > 5:
        flash("Rating must be between 1 and 5.", "danger")
        return redirect(url_for("customer_issues"))

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, status FROM issues WHERE id = %s AND user_id = %s",
        (issue_id, session["user_id"]),
    )
    issue = cur.fetchone()
    if not issue:
        cur.close()
        flash("Issue not found.", "danger")
        return redirect(url_for("customer_issues"))

    if issue["status"] != "Resolved":
        cur.close()
        flash("You can rate only resolved issues.", "warning")
        return redirect(url_for("customer_issues"))

    cur.execute("SELECT id FROM issue_ratings WHERE issue_id = %s", (issue_id,))
    existing = cur.fetchone()
    if existing:
        cur.close()
        flash("Rating already submitted for this issue.", "info")
        return redirect(url_for("customer_issues"))

    cur.execute(
        "INSERT INTO issue_ratings (issue_id, user_id, rating, feedback) VALUES (%s, %s, %s, %s)",
        (issue_id, session["user_id"], rating_value, feedback),
    )
    mysql.connection.commit()
    cur.close()

    flash("Thank you for your feedback.", "success")
    return redirect(url_for("customer_issues"))


@app.route("/issues/<int:issue_id>/reopen", methods=["POST"])
@login_required(role="customer")
def reopen_issue(issue_id):
    """Allow customer to reopen resolved issues with a reason."""
    reason = request.form.get("reopen_reason", "").strip()
    if not reason:
        flash("Please provide a reason to reopen the issue.", "warning")
        return redirect(url_for("customer_issues"))

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT status, remark FROM issues WHERE id = %s AND user_id = %s",
        (issue_id, session["user_id"]),
    )
    issue = cur.fetchone()

    if not issue:
        cur.close()
        flash("Issue not found.", "danger")
        return redirect(url_for("customer_issues"))

    if issue["status"] != "Resolved":
        cur.close()
        flash("Only resolved issues can be reopened.", "warning")
        return redirect(url_for("customer_issues"))

    previous_remark = (issue.get("remark") or "").strip()
    customer_note = f"Customer reopened issue: {reason}"
    combined_remark = f"{previous_remark} | {customer_note}" if previous_remark else customer_note

    cur.execute(
        "UPDATE issues SET status = %s, remark = %s WHERE id = %s AND user_id = %s",
        ("Open", combined_remark, issue_id, session["user_id"]),
    )
    mysql.connection.commit()
    cur.close()

    flash("Issue reopened successfully.", "success")
    return redirect(url_for("customer_issues"))


@app.route("/issues/<int:issue_id>/delete", methods=["POST"])
@login_required(role="customer")
def delete_customer_issue(issue_id):
    """Allow customer to delete only their own issue."""
    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM issues WHERE id = %s AND user_id = %s", (issue_id, session["user_id"]))
    issue = cur.fetchone()
    if not issue:
        cur.close()
        flash("Issue not found.", "danger")
        return redirect(url_for("customer_issues"))

    cur.execute("DELETE FROM issues WHERE id = %s AND user_id = %s", (issue_id, session["user_id"]))
    mysql.connection.commit()
    cur.close()
    flash("Issue deleted successfully.", "success")
    return redirect(url_for("customer_issues"))


@app.route("/uploads/<path:filename>")
@login_required()
def uploaded_file(filename):
    """Serve uploaded files to authenticated users."""
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/admin/dashboard")
@login_required(role="admin")
def admin_dashboard():
    """Admin dashboard with stats and chart data."""
    cur = mysql.connection.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM issues")
    total_issues = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) AS open_count FROM issues WHERE status IN ('Open', 'In Progress')")
    open_issues = cur.fetchone()["open_count"]

    cur.execute("SELECT COUNT(*) AS resolved_count FROM issues WHERE status = 'Resolved'")
    resolved_issues = cur.fetchone()["resolved_count"]

    cur.execute(
        """
        SELECT status, COUNT(*) AS total
        FROM issues
        GROUP BY status
        ORDER BY FIELD(status, 'Open', 'In Progress', 'Resolved')
        """
    )
    status_rows = cur.fetchall()

    cur.execute(
        """
        SELECT priority, COUNT(*) AS total
        FROM issues
        GROUP BY priority
        ORDER BY FIELD(priority, 'Low', 'Medium', 'High', 'Critical')
        """
    )
    priority_rows = cur.fetchall()

    cur.execute(
        """
        SELECT DATE_FORMAT(created_at, '%%Y-%%m') AS month_key, COUNT(*) AS total
        FROM issues
        WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 5 MONTH)
        GROUP BY DATE_FORMAT(created_at, '%%Y-%%m')
        ORDER BY month_key
        """
    )
    trend_rows = cur.fetchall()

    cur.close()
    notifications = serialize_notifications(
        get_recent_notifications("admin", session["user_id"]),
        "admin",
    )

    status_chart = {
        "labels": [row["status"] for row in status_rows],
        "values": [row["total"] for row in status_rows],
    }
    priority_chart = {
        "labels": [row["priority"] for row in priority_rows],
        "values": [row["total"] for row in priority_rows],
    }

    trend_map = {row["month_key"]: row["total"] for row in trend_rows}
    trend_labels = []
    trend_values = []
    current = datetime.now()
    current_month_index = current.year * 12 + current.month - 1
    for offset in range(5, -1, -1):
        month_index = current_month_index - offset
        year = month_index // 12
        month = month_index % 12 + 1
        month_key = f"{year:04d}-{month:02d}"
        trend_labels.append(datetime(year, month, 1).strftime("%b %Y"))
        trend_values.append(trend_map.get(month_key, 0))

    trend_chart = {
        "labels": trend_labels,
        "values": trend_values,
    }

    return render_template(
        "admin_dashboard.html",
        total_issues=total_issues,
        open_issues=open_issues,
        resolved_issues=resolved_issues,
        status_chart=status_chart,
        priority_chart=priority_chart,
        trend_chart=trend_chart,
        notifications=notifications,
    )


@app.route("/admin/issues")
@login_required(role="admin")
def admin_issues():
    """Admin list page with filter by status and priority."""
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()
    sort_by = request.args.get("sort_by", "created_at").strip()
    sort_dir = request.args.get("sort_dir", "desc").strip().lower()
    sort_dir_sql = "ASC" if sort_dir == "asc" else "DESC"
    allowed_sort = {
        "created_at": "issues.created_at",
        "priority": "FIELD(issues.priority, 'Low', 'Medium', 'High', 'Critical')",
        "status": "FIELD(issues.status, 'Open', 'In Progress', 'Resolved')",
        "title": "issues.title",
    }
    sort_expr = allowed_sort.get(sort_by, "issues.created_at")

    query = """
        SELECT issues.*, users.name AS customer_name, users.email AS customer_email,
               issue_ratings.rating AS customer_rating, issue_ratings.feedback AS customer_feedback
        FROM issues
        JOIN users ON issues.user_id = users.id
        LEFT JOIN issue_ratings ON issue_ratings.issue_id = issues.id
        WHERE 1=1
    """
    params = []

    if status_filter:
        query += " AND issues.status = %s"
        params.append(status_filter)

    if priority_filter:
        query += " AND issues.priority = %s"
        params.append(priority_filter)

    query += f" ORDER BY {sort_expr} {sort_dir_sql}"

    cur = mysql.connection.cursor()
    cur.execute(query, tuple(params))
    issues = cur.fetchall()
    cur.close()
    attach_files_to_issues(issues)

    return render_template(
        "admin_issues.html",
        issues=issues,
        status_filter=status_filter,
        priority_filter=priority_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@app.route("/issues/check-duplicate", methods=["POST"])
@login_required(role="customer")
def check_duplicate_issue():
    """Check if similar issues already exist for the user."""
    title = request.form.get("title", "").strip().lower()
    description = request.form.get("description", "").strip().lower()
    category = request.form.get("category", "").strip()

    if len(title) < 4:
        return jsonify({"duplicates": [], "exact_duplicate": False, "has_similar": False, "blocked": False})

    normalized_title = " ".join(title.split())
    normalized_description = " ".join(description.split())

    exact_duplicate = False
    if normalized_description:
        cur = mysql.connection.cursor()
        cur.execute(
            """
            SELECT id
            FROM issues
            WHERE user_id = %s
              AND LOWER(TRIM(title)) = %s
              AND LOWER(TRIM(description)) = %s
              AND (%s = '' OR category = %s)
            LIMIT 1
            """,
            (session["user_id"], normalized_title, normalized_description, category, category),
        )
        exact_duplicate = cur.fetchone() is not None
        cur.close()

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT id, title, status, created_at
        FROM issues
        WHERE user_id = %s
          AND (LOWER(title) LIKE %s OR LOWER(description) LIKE %s)
          AND (%s = '' OR category = %s)
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (session["user_id"], f"%{normalized_title}%", f"%{normalized_title}%", category, category),
    )
    rows = cur.fetchall()
    cur.close()

    return jsonify(
        {
            "exact_duplicate": exact_duplicate,
            "has_similar": len(rows) > 0,
            "blocked": exact_duplicate or len(rows) > 0,
            "duplicates": [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M"),
                }
                for row in rows
            ]
        }
    )


@app.route("/admin/issues/<int:issue_id>/delete", methods=["POST"])
@login_required(role="admin")
def delete_admin_issue(issue_id):
    """Allow admin to delete any issue."""
    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM issues WHERE id = %s", (issue_id,))
    issue = cur.fetchone()
    if not issue:
        cur.close()
        flash("Issue not found.", "danger")
        return redirect(url_for("admin_issues"))

    cur.execute("DELETE FROM issues WHERE id = %s", (issue_id,))
    mysql.connection.commit()
    cur.close()
    flash("Issue deleted successfully by admin.", "success")
    return redirect(url_for("admin_issues"))


@app.route("/admin/issues/export.csv")
@login_required(role="admin")
def export_issues_csv():
    """Export filtered admin issues to CSV report."""
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()

    query = """
        SELECT issues.*, users.name AS customer_name, users.email AS customer_email
        FROM issues
        JOIN users ON issues.user_id = users.id
        WHERE 1=1
    """
    params = []

    if status_filter:
        query += " AND issues.status = %s"
        params.append(status_filter)

    if priority_filter:
        query += " AND issues.priority = %s"
        params.append(priority_filter)

    query += " ORDER BY issues.created_at DESC"

    cur = mysql.connection.cursor()
    cur.execute(query, tuple(params))
    issues = cur.fetchall()
    cur.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Issue ID",
            "Customer Name",
            "Customer Email",
            "Title",
            "Category",
            "Priority",
            "Status",
            "Admin Remark",
            "Attachments",
            "Created At",
        ]
    )

    for issue in issues:
        attachments = ", ".join(parse_attachments(issue.get("file_path")))
        writer.writerow(
            [
                issue["id"],
                issue["customer_name"],
                issue["customer_email"],
                issue["title"],
                issue["category"],
                issue["priority"],
                issue["status"],
                issue.get("remark") or "",
                attachments,
                issue["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )

    csv_data = output.getvalue()
    output.close()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=issues_report_{timestamp}.csv"},
    )


@app.route("/admin/issues/<int:issue_id>/update", methods=["POST"])
@login_required(role="admin")
def update_issue(issue_id):
    """Admin updates issue status and remarks."""
    status = request.form.get("status", "").strip()
    remark = request.form.get("remark", "").strip()

    if status not in {"Open", "In Progress", "Resolved"}:
        flash("Invalid status value.", "danger")
        return redirect(url_for("admin_issues"))

    cur = mysql.connection.cursor()
    cur.execute("SELECT user_id, title, status FROM issues WHERE id = %s", (issue_id,))
    issue = cur.fetchone()
    if not issue:
        cur.close()
        flash("Issue not found.", "danger")
        return redirect(url_for("admin_issues"))

    cur.execute(
        "UPDATE issues SET status = %s, remark = %s WHERE id = %s",
        (status, remark, issue_id),
    )

    if status == "Resolved" and issue["status"] != "Resolved":
        create_notification(
            f"Your issue '{issue['title']}' has been resolved by the admin.",
            recipient_role="customer",
            recipient_user_id=issue["user_id"],
            issue_id=issue_id,
        )

    mysql.connection.commit()
    cur.close()

    flash("Issue updated successfully.", "success")
    return redirect(url_for("admin_issues"))


@app.route("/notifications/feed")
@login_required()
def notification_feed():
    """Return recent notifications for the signed-in user."""
    role = session["role"]
    user_id = session["user_id"]
    notifications = serialize_notifications(get_recent_notifications(role, user_id), role)
    unread_count = get_unread_notification_count(role, user_id)
    return jsonify({"notifications": notifications, "unread_count": unread_count})


@app.route("/notifications/mark-read", methods=["POST"])
@login_required()
def mark_notification_feed_read():
    """Mark all notifications as read after dashboard display."""
    role = session["role"]
    user_id = session["user_id"]
    mark_notifications_read(role, user_id)
    mysql.connection.commit()
    return jsonify({"success": True, "unread_count": 0})


if __name__ == "__main__":
    app.run(debug=True)
