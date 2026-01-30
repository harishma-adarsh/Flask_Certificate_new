import os
import sqlite3
import pandas as pd
import re
import zipfile
from datetime import datetime
from flask import Flask, render_template, request, send_file, jsonify
from weasyprint import HTML
from jinja2 import Template
import cloudinary
import cloudinary.uploader
import logging
from dotenv import load_dotenv

load_dotenv()

# ---------------- LOGGING CONFIG ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------- CLOUDINARY CONFIG ----------------
cloudinary_cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
cloudinary_api_key = os.getenv("CLOUDINARY_API_KEY")
cloudinary_api_secret = os.getenv("CLOUDINARY_API_SECRET")

if not all([cloudinary_cloud_name, cloudinary_api_key, cloudinary_api_secret]):
    logger.warning("Cloudinary environment variables are missing!")

if cloudinary_cloud_name == "Certificate":
    logger.error("CRITICAL: Your Cloudinary 'cloud_name' is still set to 'Certificate'. Please update your Render environment variables with your actual Cloudinary Cloud Name.")

cloudinary.config(
    cloud_name=cloudinary_cloud_name,
    api_key=cloudinary_api_key,
    api_secret=cloudinary_api_secret
)

# ---------------- PATHS ----------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "certificates.db")
PDF_DIR = os.path.join(BASE_DIR, "generated", "pdfs")


# ---------------- DATABASE INIT ----------------
def init_db():
    logger.info("Initializing database...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            certificate_number TEXT,
            student_name TEXT,
            pdf_path TEXT,
            cloudinary_url TEXT
        )
    """)
    
    # Migration: Add cloudinary_url if not exists
    c.execute("PRAGMA table_info(certificates)")
    columns = [info[1] for info in c.fetchall()]
    if "cloudinary_url" not in columns:
        logger.info("Adding cloudinary_url column to certificates table...")
        c.execute("ALTER TABLE certificates ADD COLUMN cloudinary_url TEXT")
        
    conn.commit()
    conn.close()
    logger.info("Database initialization complete.")

# Initialize the DB immediately on startup
init_db()


# ---------------- SAFE VALUE (NaN FIX) ----------------
def safe_value(value):
    """
    Converts NaN / None to empty string
    """
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


# ---------------- CERTIFICATE NUMBER ----------------
def get_next_certificate_number():
    START_NUMBER = 1   # 001
    PAD_LENGTH = 3     # 3 digits

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT certificate_number FROM certificates ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        return f"ACDT-C-25-{START_NUMBER:0{PAD_LENGTH}d}"

    match = re.search(r"(\d+)$", row[0])
    last_no = int(match.group(1)) if match else START_NUMBER - 1
    next_no = last_no + 1

    return f"ACDT-C-25-{next_no:0{PAD_LENGTH}d}"


# ---------------- SEMESTER FORMAT ----------------
def format_semester(semester):
    if semester is None or pd.isna(semester):
        return ""

    semester = str(semester).strip()

    match = re.match(r"^(\d+)(st|nd|rd|th)$", semester, re.IGNORECASE)
    if match:
        return f"{match.group(1)}<sup>{match.group(2)}</sup>"

    if semester.isdigit():
        sem = int(semester)
        if 11 <= sem % 100 <= 13:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(sem % 10, "th")
        return f"{sem}<sup>{suffix}</sup>"

    return semester


# ---------------- INTERNSHIP DURATION ----------------
def format_internship_duration(row):
    hours = row.get("internship_hours")
    if not pd.isna(hours) and str(hours).strip():
        return f"{int(hours)} Hours"

    start = row.get("start_date")
    end = row.get("end_date")

    if not pd.isna(start) and not pd.isna(end):
        try:
            start_fmt = pd.to_datetime(start).strftime("%d-%m-%Y")
            end_fmt = pd.to_datetime(end).strftime("%d-%m-%Y")
            return f"from {start_fmt} to {end_fmt}"
        except:
            pass

    return ""


# ---------------- CLOUDINARY UPLOAD ----------------
def upload_to_cloudinary(file_path, public_id):
    try:
        logger.info(f"Uploading {file_path} to Cloudinary...")
        response = cloudinary.uploader.upload(file_path, public_id=public_id, resource_type="auto")
        url = response.get("secure_url")
        logger.info(f"Upload successful: {url}")
        return url
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {e}", exc_info=True)
        return None


# ---------------- SMART HEADER DETECTION ----------------
def detect_header_row(excel_file):
    """
    Scans first 10 rows to find the one with the most non-empty columns.
    Returns the 0-based index of that row.
    """
    try:
        # Read first 10 rows without header to inspect content
        df_preview = pd.read_excel(excel_file, header=None, nrows=10)
        
        max_cols = 0
        best_row = 0
        
        for idx, row in df_preview.iterrows():
            # Count values that are not null and not empty strings
            valid_cols = row.dropna().astype(str).str.strip().ne("").sum()
            
            # If this row has more data than previous best, it's likely the header
            # We use >= to prefer the *first* row if multiple have same count (standard case)
            if valid_cols > max_cols:
                max_cols = valid_cols
                best_row = idx
                
        return best_row
    except Exception:
        return 0  # Fallback to first row on error


# ---------------- PREVIEW EXCEL COLUMNS ----------------
@app.route("/preview_columns", methods=["POST"])
def preview_columns():
    """
    Returns the column names from uploaded Excel file as JSON
    """
    try:
        excel_file = request.files.get("excel")
        if not excel_file or not excel_file.filename:
            return jsonify({"error": "No file uploaded"}), 400
        
        # Smart detect header row
        header_row_idx = detect_header_row(excel_file)
        
        # Reset file pointer after detection read
        excel_file.seek(0)
        
        df = pd.read_excel(excel_file, header=header_row_idx)
        
        # Normalize column names
        original_columns = df.columns.tolist()
        normalized_columns = []
        for col in df.columns:
            # Handle non-string column names
            col_str = str(col).strip().lower()
            norm_col = re.sub(r"\s+", "_", col_str)
            normalized_columns.append(norm_col)
        
        # Create mapping of original to normalized
        column_mapping = [
            {"original": orig, "normalized": norm} 
            for orig, norm in zip(original_columns, normalized_columns)
        ]
        
        return jsonify({
            "success": True,
            "columns": column_mapping,
            "row_count": len(df)
        })
    except Exception as e:
        logger.error(f"Preview columns error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 400


# ---------------- ROUTE ----------------
@app.route("/", methods=["GET", "POST"])
def upload():

    if request.method == "POST":

        excel_file = request.files.get("excel")
        custom_content = request.form.get("content", "").strip()
        single_name = request.form.get("student_name", "").strip()

        # ===================== BULK MODE =====================
        if excel_file and excel_file.filename:
            try:
                # Smart detect header row
                header_row_idx = detect_header_row(excel_file)
                
                # Reset file pointer after detection read
                excel_file.seek(0)

                df = pd.read_excel(excel_file, header=header_row_idx)

                # Normalize column names
                df.columns = (
                    df.columns.astype(str)
                    .str.strip()
                    .str.lower()
                    .str.replace(r"\s+", "_", regex=True)
                )

                # Parse date columns safely
                for col in ["issue_date", "date", "start_date", "end_date"]:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

                pdf_files = []

                for _, row in df.iterrows():

                    cert_no = get_next_certificate_number()

                    # Find issue date in various columns or use today
                    issue_date_val = row.get("issue_date") or row.get("date")
                    if not pd.isna(issue_date_val) and hasattr(issue_date_val, "strftime"):
                        issue_date = issue_date_val.strftime("%d-%m-%Y")
                    else:
                        issue_date = datetime.now().strftime("%d-%m-%Y")

                    # Build dynamic context from ALL Excel columns
                    template_context = {}
                    for col in df.columns:
                        value = row.get(col)
                        
                        # Special formatting for certain columns
                        if col == "semester":
                            template_context[col] = format_semester(value)
                        elif col == "internship_duration":
                            template_context[col] = format_internship_duration(row)
                        elif col in ["start_date", "end_date"] and not pd.isna(value):
                            template_context[col] = pd.to_datetime(value).strftime("%d-%m-%Y")
                        elif col == "issue_date":
                            template_context[col] = issue_date
                        else:
                            template_context[col] = safe_value(value)
                    
                    # Add computed field for internship_duration if not in Excel
                    if "internship_duration" not in template_context:
                        template_context["internship_duration"] = format_internship_duration(row)

                    # Render the certificate body with dynamic context
                    template = Template(custom_content)
                    rendered_body = template.render(**template_context)

                    # Determine Certificate Title
                    content_lower = rendered_body.lower()
                    if "industrial visit" in content_lower:
                        cert_title = "INDUSTRIAL VISIT"
                    else:
                        cert_title = "INTERNSHIP"

                    # Find student name from common column variants
                    student_name_val = row.get("student_name") or row.get("full_name") or row.get("name")

                    context = {
                        "student_name": safe_value(student_name_val),
                        "certificate_body": rendered_body,
                        "certificate_title": cert_title,
                        "certificate_number": cert_no,
                        "place": safe_value(row.get("place")),
                        "issue_date": issue_date,
                        "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
                    }

                    # Get selected template (default to certificate.html)
                    selected_template = request.form.get("template", "certificate.html")
                    html = render_template(selected_template, **context)

                    os.makedirs(PDF_DIR, exist_ok=True)
                    pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

                    HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
                    pdf_files.append(pdf_path)

                    # Upload to Cloudinary
                    cloudinary_url = upload_to_cloudinary(pdf_path, cert_no)

                    # Save DB record
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute(
                        "INSERT INTO certificates (certificate_number, student_name, pdf_path, cloudinary_url) VALUES (?, ?, ?, ?)",
                        (cert_no, context["student_name"], pdf_path, cloudinary_url)
                    )
                    conn.commit()
                    conn.close()

                # ZIP download
                zip_path = os.path.join(PDF_DIR, "certificates.zip")
                if os.path.exists(zip_path):
                    os.remove(zip_path)

                with zipfile.ZipFile(zip_path, "w") as zipf:
                    for pdf in pdf_files:
                        zipf.write(pdf, os.path.basename(pdf))

                return send_file(zip_path, as_attachment=True, download_name="certificates.zip")
            except Exception as e:
                logger.error(f"Bulk generation error: {e}", exc_info=True)
                return jsonify({"error": f"An error occurred during bulk generation: {str(e)}"}), 500

        # ===================== SINGLE MODE =====================
        elif single_name and custom_content:
            try:
                raw_date = request.form.get("single_date", "")
                single_place = request.form.get("single_place", "")

                single_date = ""
                if raw_date:
                    single_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d-%m-%Y")

                cert_no = get_next_certificate_number()

                template = Template(custom_content)
                rendered_body = template.render()

                # Determine Certificate Title
                content_lower = rendered_body.lower()
                if "industrial visit" in content_lower:
                    cert_title = "INDUSTRIAL VISIT"
                else:
                    cert_title = "INTERNSHIP"

                context = {
                    "student_name": safe_value(single_name),
                    "certificate_body": rendered_body,
                    "certificate_title": cert_title,
                    "certificate_number": cert_no,
                    "single_place": safe_value(single_place),
                    "single_issue_date": single_date,
                    "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
                }

                # Get selected template (default to certificate.html)
                selected_template = request.form.get("template", "certificate.html")
                html = render_template(selected_template, **context)

                os.makedirs(PDF_DIR, exist_ok=True)
                pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

                HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
                
                # Upload to Cloudinary
                cloudinary_url = upload_to_cloudinary(pdf_path, cert_no)
                
                # Save DB record
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute(
                    "INSERT INTO certificates (certificate_number, student_name, pdf_path, cloudinary_url) VALUES (?, ?, ?, ?)",
                    (cert_no, context["student_name"], pdf_path, cloudinary_url)
                )
                conn.commit()
                conn.close()

                return send_file(pdf_path, as_attachment=True)
            except Exception as e:
                logger.error(f"Single generation error: {e}", exc_info=True)
                return jsonify({"error": f"An error occurred during certificate generation: {str(e)}"}), 500

        return "Error: Upload Excel or enter Student Name"

    return render_template("upload.html")


@app.route("/clear_db", methods=["POST"])
def clear_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM certificates")
        # Reset autoincrement
        c.execute("DELETE FROM sqlite_sequence WHERE name='certificates'")
        conn.commit()
        conn.close()
        
        # Also clean up local PDFs
        if os.path.exists(PDF_DIR):
            for f in os.listdir(PDF_DIR):
                file_path = os.path.join(PDF_DIR, f)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {e}")

        return jsonify({"success": True, "message": "Database cleared successfully!"})
    except Exception as e:
        logger.error(f"Clear DB error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------- MAIN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
