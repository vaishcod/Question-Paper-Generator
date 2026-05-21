from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
import os
import json
import requests
import sqlite3
import firebase_admin

from firebase_admin import credentials , auth
from fpdf import FPDF

from engine import read_syllabus, generate_with_retries, save_to_docx, analyze_paper_quality

# Load local .env file if it exists (highly useful for local development)
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, val = stripped.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

firebase_config = json.loads(os.environ["FIREBASE_CREDENTIALS"])

cred = credentials.Certificate(firebase_config)
firebase_admin.initialize_app(cred)

# ------------------ APP SETUP ------------------

app = Flask(__name__)
app.secret_key = "temporary-secret-key"  # OK for local dev

is_vercel = os.environ.get("VERCEL") == "1" or "AWS_LAMBDA_FUNCTION_NAME" in os.environ

if is_vercel:
    UPLOAD_FOLDER = "/tmp/uploads"
    OUTPUT_FOLDER = "/tmp/outputs"
    DB_NAME = "/tmp/history.db"
else:
    UPLOAD_FOLDER = "uploads"
    OUTPUT_FOLDER = "outputs"
    DB_NAME = "history.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_uid TEXT,
            filename TEXT,
            current_version INTEGER
        )
    ''')
    
    try:
        c.execute("ALTER TABLE papers ADD COLUMN user_email TEXT")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE papers ADD COLUMN difficulty TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE papers ADD COLUMN exam_format TEXT")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE papers ADD COLUMN syllabus_text TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE papers ADD COLUMN subject TEXT")
    except sqlite3.OperationalError:
        pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS edits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER,
            version INTEGER,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            action TEXT,
            paper_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            uid TEXT PRIMARY KEY,
            api_key TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ------------------ HELPERS ------------------
def log_action(user_email, action, paper_id=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO logs (user_email, action, paper_id) VALUES (?, ?, ?)", 
              (user_email, action, paper_id))
    conn.commit()
    conn.close()

def get_user_api_key(uid):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT api_key FROM users WHERE uid = ?", (uid,))
    result = c.fetchone()
    conn.close()
    
    # Return user key if exists, else return the global default API key
    if result and result[0]:
        return result[0]
    return os.environ.get("OPENROUTER_API_KEY")

def save_to_pdf(text: str, output_path: str, subject_name: str = "Subject Name", exam_format: str = "End-Semester"):
    pdf = FPDF()
    pdf.add_page()
    
    # 1. UNIVERSITY HEADER
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 8, txt="GLOBAL UNIVERSITY OF TECHNOLOGY", ln=1, align="C")
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 6, txt=f"{exam_format.upper()} EXAMINATION", ln=1, align="C")
    
    pdf.set_font("Arial", '', 11)
    pdf.cell(0, 6, txt=f"Course Title: {subject_name}", ln=1, align="C")
    
    # Line separator
    pdf.line(10, pdf.get_y()+2, 200, pdf.get_y()+2)
    pdf.ln(6)
    
    # Details Row
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(95, 6, txt=f"Time: {'3 Hours' if exam_format == 'End-Semester' else '2 Hours'}", ln=0)
    pdf.cell(95, 6, txt=f"Max Marks: {'100' if exam_format == 'End-Semester' else '50'}", ln=1, align="R")
    
    # Line separator
    pdf.line(10, pdf.get_y()+2, 200, pdf.get_y()+2)
    pdf.ln(8)
    
    pdf.set_font("Arial", size=11)
    
    # Effective page width (A4: 210mm wide - 10mm left - 10mm right = 190mm)
    epw = 190

    for line in text.splitlines():
        # Encode to latin-1 to avoid fpdf unicode errors gracefully
        safe_line = line.encode('latin-1', 'replace').decode('latin-1')
        stripped = safe_line.strip()
        if not stripped:
            pdf.ln(5)
            continue
            
        if stripped.upper() in [
            "QUESTION PAPER", "SUBJECT", "TIME AND MARKS", 
            "SECTION A", "SECTION B", "SECTION C", "INSTRUCTIONS"
        ]:
            pdf.ln(4)
            pdf.set_font("Arial", 'B', 12)
            # Center "QUESTION PAPER" and "SECTION [X]", left align others
            if stripped.upper().startswith("SECTION") or stripped.upper() == "QUESTION PAPER":
                pdf.cell(epw, 8, txt=safe_line, new_x="LMARGIN", new_y="NEXT", align="C")
            else:
                pdf.cell(epw, 8, txt=safe_line, new_x="LMARGIN", new_y="NEXT", align="L")
            pdf.set_font("Arial", '', 11)
        else:
            # Fix FPDF2 internal word-wrapping bug by explicitly declaring epw width
            pdf.multi_cell(epw, 6, txt=safe_line, align="L")
            
    pdf.output(output_path)

# ------------------ FIREBASE INIT ------------------

import json

# Try to load credentials from environment variable first
firebase_env = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_env:
    try:
        cred_dict = json.loads(firebase_env)
        cred = credentials.Certificate(cred_dict)
    except json.JSONDecodeError:
        raise ValueError("FIREBASE_CREDENTIALS environment variable is not valid JSON.")
else:
    # Fallback to local file for development
    FIREBASE_CRED_PATH = "firebase_service_account.json"
    if not os.path.exists(FIREBASE_CRED_PATH):
        raise FileNotFoundError("Firebase credentials not found. Please set FIREBASE_CREDENTIALS env var or provide firebase_service_account.json locally.")
    cred = credentials.Certificate(FIREBASE_CRED_PATH)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

# Firebase Web API Key (from Firebase Console -> Project Settings)
# You could also make this an environment variable: os.environ.get("FIREBASE_API_KEY", "your_api_key")
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY")


# ------------------ HELPERS ------------------

def _load_users_for_admin_table(include_admin_rows=True):
    users = []
    for user_record in auth.list_users().iterate_all():
        claims = user_record.custom_claims or {}
        role = claims.get("role") or ("Admin" if claims.get("admin") else "Faculty")
        is_admin_user = bool(claims.get("admin", False)) or str(role).lower() == "admin"

        if not include_admin_rows and is_admin_user:
            continue

        users.append(
            {
                "name": claims.get("name") or user_record.display_name or "-",
                "email": user_record.email or "-",
                "role": role,
                "branch": claims.get("branch") or "-",
            }
        )

    users.sort(key=lambda u: u["email"])
    return users


def _get_user_access(uid=None, email=None):
    """Resolve role and access from server-side Firebase claims."""
    try:
        if uid:
            user_record = auth.get_user(uid)
        elif email:
            user_record = auth.get_user_by_email(email)
        else:
            return {
                "role": "Guest",
                "is_admin": False,
                "is_dean": False,
                "can_manage_users": False,
            }

        claims = user_record.custom_claims or {}
        role = claims.get("role") or ("Admin" if claims.get("admin") else "Faculty")
        role_lower = str(role).strip().lower()
        is_admin = bool(claims.get("admin", False)) or role_lower == "admin"
        is_dean = role_lower == "dean"
        return {
            "role": role,
            "is_admin": is_admin,
            "is_dean": is_dean,
            "can_manage_users": is_admin or is_dean,
        }
    except Exception:
        return {
            "role": "Faculty",
            "is_admin": False,
            "is_dean": False,
            "can_manage_users": False,
        }


def _refresh_session_access():
    access = _get_user_access(session.get("uid"), session.get("user"))
    session["role"] = access["role"]
    session["is_admin"] = access["is_admin"]
    session["is_dean"] = access["is_dean"]
    session["can_manage_users"] = access["can_manage_users"]
    return access


@app.context_processor
def inject_nav_context():
    is_authenticated = "user" in session
    role = "Guest"
    can_manage_users = False

    if is_authenticated:
        access = _refresh_session_access()
        role = access["role"]
        can_manage_users = access["can_manage_users"]

    return {
        "nav_is_authenticated": is_authenticated,
        "nav_role": role,
        "nav_can_manage_users": can_manage_users,
    }

@app.route("/api/models")
def api_models():
    if "user" not in session:
        return jsonify({"models": []}), 401
    uid = session.get("uid")
    api_key = get_user_api_key(uid)
    if not api_key:
        return jsonify({"models": []})
    
    from llm_client import get_available_models
    return jsonify({"models": get_available_models(api_key)})

# ------------------ ROUTES ------------------

@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))

    access = _refresh_session_access()

    if access["can_manage_users"]:
        return redirect(url_for("admin_dashboard"))

    return redirect(url_for("upload"))

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user" not in session:
        return redirect(url_for("login"))
        
    uid = session.get("uid")
    message = None
    success = False

    if request.args.get("error") == "api_key_required":
        message = "Please configure your OpenRouter API Key to start generating question papers."
        success = False
    
    if request.method == "POST":
        api_key = request.form.get("api_key", "").strip()
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO users (uid, api_key) VALUES (?, ?) ON CONFLICT(uid) DO UPDATE SET api_key=excluded.api_key", (uid, api_key))
        conn.commit()
        conn.close()
        message = "Configuration saved securely."
        success = True
        
    current_key = get_user_api_key(uid)
    is_configured = current_key is not None and len(current_key) > 0
    masked_key = f"{current_key[:8]}...{current_key[-4:]}" if is_configured and len(current_key) > 12 else (current_key if current_key else "")
        
    return render_template("settings.html", is_configured=is_configured, masked_key=masked_key, message=message, success=success)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if not FIREBASE_API_KEY:
            try:
                user_record = auth.get_user_by_email(email)
                uid = user_record.uid
                session["user"] = email
                session["uid"] = uid
                access = _refresh_session_access()
                if access["can_manage_users"]:
                    return redirect(url_for("admin_dashboard"))
                return redirect(url_for("upload"))
            except Exception:
                return render_template("login.html", error="User not found or Firebase API Key not configured.")

        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True,
        }

        response = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}",
            json=payload,
            timeout=20,
        )

        data = response.json()

        if "idToken" not in data:
            return render_template("login.html", error="Invalid email or password")

        uid = data.get("localId")
        if not uid:
            try:
                decoded_token = auth.verify_id_token(data["idToken"])
                uid = decoded_token.get("uid")
            except Exception:
                return render_template("login.html", error="Unable to verify login token")

        if not uid:
            return render_template("login.html", error="Unable to resolve account identity")

        # Firebase has authenticated the user; keep identity + role in session.
        session["user"] = email
        session["uid"] = uid
        access = _refresh_session_access()

        if access["can_manage_users"]:
            return redirect(url_for("admin_dashboard"))

        return redirect(url_for("upload"))

    return render_template("login.html")


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        file = request.files.get("syllabus")
        user_uid = session.get("uid")
        user_email = session.get("user")

        if not file or file.filename == "":
            return render_template("upload.html", error="No file selected")

        syllabus_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(syllabus_path)

        try:
            raw = read_syllabus(syllabus_path)
            model_id = request.form.get("model", "google/gemini-2.5-flash")
            difficulty = request.form.get("difficulty", "Medium")
            exam_format = request.form.get("exam_format", "End-Semester")
            
            subject = request.form.get("department", "Subject") + " " + request.form.get("semester", "")

            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()

            # Gather all past questions for this subject to enforce uniqueness
            c.execute("SELECT syllabus_text FROM papers WHERE subject = ?", (subject,))
            past_papers = c.fetchall()
            
            # Combine past paper texts to feed to the engine
            # We use edits here instead to get the ACTUAL generated text, not just syllabus
            c.execute('''
                SELECT content FROM edits 
                JOIN papers ON edits.paper_id = papers.id 
                WHERE papers.subject = ?
            ''', (subject,))
            past_edits = c.fetchall()
            past_papers_text = "\n---\n".join([edit[0] for edit in past_edits]) if past_edits else ""
            api_key = get_user_api_key(user_uid)
            if not api_key:
                return redirect(url_for("settings", error="api_key_required"))

            # Generation Execution
            paper = generate_with_retries(raw, api_key=api_key, model_id=model_id, difficulty=difficulty, exam_format=exam_format, past_papers_text=past_papers_text)
            
            # Create paper entry
            c.execute("INSERT INTO papers (user_uid, user_email, subject, filename, current_version, difficulty, exam_format, syllabus_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                      (user_uid, user_email, subject, file.filename, 1, difficulty, exam_format, raw))
            paper_id = c.lastrowid
            
            # Create first edit entry
            c.execute("INSERT INTO edits (paper_id, version, content) VALUES (?, ?, ?)", 
                      (paper_id, 1, paper))
            
            conn.commit()
            conn.close()
            
            # Log action
            log_action(user_email, f"Generated new paper for {subject}", paper_id)
            
            # Redirect to the editor view
            return redirect(url_for('editor', paper_id=paper_id))

        except Exception as e:
            return render_template(
                "upload.html",
                error=f"Generation failed: {str(e)}",
            )

    return render_template("upload.html")


@app.route("/admin", methods=["GET", "POST"])
def admin_dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    # Re-check privilege from Firebase claims each request.
    access = _refresh_session_access()
    if not access["can_manage_users"]:
        return redirect(url_for("upload"))

    message = None
    success = False

    if request.method == "POST":
        remove_email = request.form.get("remove_email")

        if remove_email:
            try:
                user_record = auth.get_user_by_email(remove_email)
                target_claims = user_record.custom_claims or {}
                target_role = target_claims.get("role") or ("Admin" if target_claims.get("admin") else "Faculty")
                target_is_admin = bool(target_claims.get("admin", False)) or str(target_role).lower() == "admin"

                if target_is_admin and not access["is_admin"]:
                    message = "Only Admin can remove Admin users"
                else:
                    auth.delete_user(user_record.uid)
                    message = f"Removed user: {remove_email}"
                    success = True
            except Exception as e:
                message = f"Could not remove user: {str(e)}"

        elif request.form.get("add_user") is not None:
            name = (request.form.get("name") or "").strip()
            email = (request.form.get("email") or "").strip()
            password = request.form.get("password") or ""
            role = (request.form.get("role") or "").strip()
            branch = (request.form.get("branch") or "").strip()

            if not all([name, email, password, role, branch]):
                message = "All fields are required"
            else:
                try:
                    requested_admin = role.lower() == "admin"
                    if requested_admin and not access["is_admin"]:
                        message = "Only Admin can create Admin users"
                        users = _load_users_for_admin_table(include_admin_rows=access["is_admin"])
                        return render_template("admin.html", users=users, message=message, success=success)

                    user_record = auth.create_user(
                        email=email,
                        password=password,
                        display_name=name,
                    )

                    is_admin = requested_admin
                    auth.set_custom_user_claims(
                        user_record.uid,
                        {
                            "admin": is_admin,
                            "role": role,
                            "branch": branch,
                            "name": name,
                        },
                    )

                    message = f"Added user: {email}"
                    success = True
                except Exception as e:
                    message = f"Could not add user: {str(e)}"

    users = _load_users_for_admin_table(include_admin_rows=access["is_admin"])
    return render_template("admin.html", users=users, message=message, success=success)


@app.route("/editor/<int:paper_id>")
def editor(paper_id):
    if "user" not in session:
        return redirect(url_for("login"))

    user_uid = session.get("uid")
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Check if paper exists and belongs to user (or allow Admins/Deans to access all papers)
    access = _refresh_session_access()
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    else:
        c.execute("SELECT * FROM papers WHERE id = ? AND user_uid = ?", (paper_id, user_uid))
    paper = c.fetchone()
    
    if not paper:
        conn.close()
        return redirect(url_for("upload"))

    # Get the latest version content
    c.execute("SELECT content, version FROM edits WHERE paper_id = ? ORDER BY version DESC LIMIT 1", (paper_id,))
    latest_edit = c.fetchone()
    
    # Get all history
    c.execute("SELECT version, timestamp FROM edits WHERE paper_id = ? ORDER BY version DESC", (paper_id,))
    history = c.fetchall()
    
    conn.close()

    return render_template("editor.html", paper=paper, content=latest_edit['content'], history=history, current_version=latest_edit['version'])

@app.route("/api/analytics/<int:paper_id>")
def get_paper_analytics(paper_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_uid = session.get("uid")
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    access = _refresh_session_access()
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT syllabus_text FROM papers WHERE id = ?", (paper_id,))
    else:
        c.execute("SELECT syllabus_text FROM papers WHERE id = ? AND user_uid = ?", (paper_id, user_uid))
    paper_record = c.fetchone()
    
    if not paper_record or not paper_record[0]:
        conn.close()
        return jsonify({"error": "Syllabus not found for analytics"}), 404
        
    syllabus_text = paper_record[0]
    
    c.execute("SELECT content FROM edits WHERE paper_id = ? ORDER BY version DESC LIMIT 1", (paper_id,))
    edit_record = c.fetchone()
    conn.close()
    
    if not edit_record:
        return jsonify({"error": "Paper content not found"}), 404
        
    paper_text = edit_record[0]
    api_key = get_user_api_key(user_uid)
    if not api_key:
        return jsonify({"error": "No API Key Configured. Please configure in settings."}), 400

    # Run the analysis
    analytics_data = analyze_paper_quality(syllabus_text, paper_text, api_key=api_key)
    
    return jsonify(analytics_data)

@app.route("/save_edit/<int:paper_id>", methods=["POST"])
def save_edit(paper_id):
    if "user" not in session:
        return redirect(url_for("login"))

    user_uid = session.get("uid")
    new_content = request.form.get("content")
    
    if not new_content:
        return redirect(url_for('editor', paper_id=paper_id))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Verify ownership (or allow Admins/Deans)
    access = _refresh_session_access()
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT current_version FROM papers WHERE id = ?", (paper_id,))
    else:
        c.execute("SELECT current_version FROM papers WHERE id = ? AND user_uid = ?", (paper_id, user_uid))
    paper = c.fetchone()
    
    if not paper:
        conn.close()
        return redirect(url_for("upload"))

    new_version = paper[0] + 1
    
    # Update paper to new version
    c.execute("UPDATE papers SET current_version = ? WHERE id = ?", (new_version, paper_id))
    
    # Insert new edit
    c.execute("INSERT INTO edits (paper_id, version, content) VALUES (?, ?, ?)", 
              (paper_id, new_version, new_content))
              
    conn.commit()
    conn.close()
    
    log_action(session.get("user"), f"Saved edit for paper #{paper_id} (Version {new_version})", paper_id)

    return redirect(url_for('editor', paper_id=paper_id))

@app.route("/view_version/<int:paper_id>/<int:version>")
def view_version(paper_id, version):
    if "user" not in session:
        return redirect(url_for("login"))

    user_uid = session.get("uid")
    
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Verify ownership (or allow Admins/Deans)
    access = _refresh_session_access()
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    else:
        c.execute("SELECT * FROM papers WHERE id = ? AND user_uid = ?", (paper_id, user_uid))
    paper = c.fetchone()
    
    if not paper:
        conn.close()
        return redirect(url_for("upload"))

    # Get specific version content
    c.execute("SELECT content, version, timestamp FROM edits WHERE paper_id = ? AND version = ?", (paper_id, version))
    edit = c.fetchone()
    
    # Get all history
    c.execute("SELECT version, timestamp FROM edits WHERE paper_id = ? ORDER BY version DESC", (paper_id,))
    history = c.fetchall()
    
    conn.close()

    if not edit:
        return redirect(url_for('editor', paper_id=paper_id))

    return render_template("editor.html", paper=paper, content=edit['content'], history=history, current_version=edit['version'], viewing_old=True)

@app.route("/restore_version/<int:paper_id>/<int:version>", methods=["POST"])
def restore_version(paper_id, version):
    if "user" not in session:
        return redirect(url_for("login"))

    user_uid = session.get("uid")
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Verify ownership (or allow Admins/Deans)
    access = _refresh_session_access()
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT current_version FROM papers WHERE id = ?", (paper_id,))
    else:
        c.execute("SELECT current_version FROM papers WHERE id = ? AND user_uid = ?", (paper_id, user_uid))
    paper = c.fetchone()
    
    if not paper:
        conn.close()
        return redirect(url_for("upload"))

    # Get the old version content
    c.execute("SELECT content FROM edits WHERE paper_id = ? AND version = ?", (paper_id, version))
    old_edit = c.fetchone()
    
    if not old_edit:
        conn.close()
        return redirect(url_for('editor', paper_id=paper_id))

    new_version = paper[0] + 1
    
    # Update paper to new version
    c.execute("UPDATE papers SET current_version = ? WHERE id = ?", (new_version, paper_id))
    
    # Insert restored content as new edit
    c.execute("INSERT INTO edits (paper_id, version, content) VALUES (?, ?, ?)", 
              (paper_id, new_version, old_edit[0]))
              
    conn.commit()
    conn.close()

    log_action(session.get("user"), f"Restored paper #{paper_id} to Version {version}", paper_id)

    return redirect(url_for('editor', paper_id=paper_id))

@app.route("/download/<int:paper_id>")
def download(paper_id):
    if "user" not in session:
        return redirect(url_for("login"))

    user_uid = session.get("uid")
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Verify ownership and get latest content (or allow Admins/Deans)
    access = _refresh_session_access()
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT p.filename, e.content FROM papers p JOIN edits e ON p.id = e.paper_id WHERE p.id = ? ORDER BY e.version DESC LIMIT 1", (paper_id,))
    else:
        c.execute("SELECT p.filename, e.content FROM papers p JOIN edits e ON p.id = e.paper_id WHERE p.id = ? AND p.user_uid = ? ORDER BY e.version DESC LIMIT 1", (paper_id, user_uid))
    result = c.fetchone()
    
    conn.close()

    if not result:
        return redirect(url_for("upload"))
        
    filename, content = result

    output_path = os.path.join(OUTPUT_FOLDER, f"Question_Paper_{paper_id}.docx")
    
    # Fetch paper details for the header
    conn2 = sqlite3.connect(DB_NAME)
    c2 = conn2.cursor()
    c2.execute("SELECT subject, exam_format FROM papers WHERE id = ?", (paper_id,))
    paper_metadata = c2.fetchone()
    conn2.close()
    subject_name = paper_metadata[0] if (paper_metadata and paper_metadata[0]) else "Subject"
    exam_format = paper_metadata[1] if (paper_metadata and paper_metadata[1]) else "End-Semester"
    
    save_to_docx(content, output_path, subject_name, exam_format)

    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"Question_Paper_{filename.split('.')[0]}.docx",
    )

@app.route("/download_pdf/<int:paper_id>")
def download_pdf(paper_id):
    if "user" not in session:
        return redirect(url_for("login"))

    user_uid = session.get("uid")
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Verify ownership and get latest content (or allow Admins/Deans)
    access = _refresh_session_access()
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT p.filename, e.content FROM papers p JOIN edits e ON p.id = e.paper_id WHERE p.id = ? ORDER BY e.version DESC LIMIT 1", (paper_id,))
    else:
        c.execute("SELECT p.filename, e.content FROM papers p JOIN edits e ON p.id = e.paper_id WHERE p.id = ? AND p.user_uid = ? ORDER BY e.version DESC LIMIT 1", (paper_id, user_uid))
    result = c.fetchone()
    conn.close()

    if not result:
        return redirect(url_for("upload"))
        
    filename, content = result

    output_path = os.path.join(OUTPUT_FOLDER, f"Question_Paper_{paper_id}.pdf")
    
    # Fetch paper details for the header
    conn2 = sqlite3.connect(DB_NAME)
    c2 = conn2.cursor()
    c2.execute("SELECT subject, exam_format FROM papers WHERE id = ?", (paper_id,))
    paper_metadata = c2.fetchone()
    conn2.close()
    subject_name = paper_metadata[0] if (paper_metadata and paper_metadata[0]) else "Subject"
    exam_format = paper_metadata[1] if (paper_metadata and paper_metadata[1]) else "End-Semester"
    
    save_to_pdf(content, output_path, subject_name, exam_format)

    log_action(session.get("user"), f"Downloaded PDF for paper #{paper_id}", paper_id)

    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"Question_Paper_{filename.split('.')[0]}.pdf",
    )

@app.route("/papers")
def papers_hub():
    if "user" not in session:
        return redirect(url_for("login"))

    access = _refresh_session_access()
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Admins and Deans see all papers, Faculty see only their own
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT * FROM papers ORDER BY id DESC")
    else:
        c.execute("SELECT * FROM papers WHERE user_uid = ? ORDER BY id DESC", (session.get("uid"),))
        
    all_papers = c.fetchall()
    conn.close()

    return render_template("papers.html", papers=all_papers)

@app.route("/logs")
def view_logs():
    if "user" not in session:
        return redirect(url_for("login"))

    access = _refresh_session_access()
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Admins and Deans see all activity logs, Faculty see only their own
    if access["is_admin"] or access["is_dean"]:
        c.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 500")
    else:
        c.execute("SELECT * FROM logs WHERE user_email = ? ORDER BY timestamp DESC LIMIT 500", (session.get("user"),))
        
    logs = c.fetchall()
    conn.close()

    return render_template("logs.html", logs=logs)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            return render_template(
                "signup.html",
                error="Email and password are required",
            )

        try:
            # Create a regular user account; admin rights are assigned explicitly later.
            created_user = auth.create_user(
                email=email,
                password=password,
            )

            # Log them in immediately as non-admin.
            session["user"] = email
            session["uid"] = created_user.uid
            session["role"] = "Faculty"
            session["is_admin"] = False
            session["is_dean"] = False
            session["can_manage_users"] = False

            return redirect(url_for("upload"))

        except Exception as e:
            return render_template(
                "signup.html",
                error=str(e),
            )

    return render_template("signup.html")


# ------------------ RUN ------------------

if __name__ == "__main__":
    app.run()
