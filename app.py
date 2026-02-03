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
import gc
from concurrent.futures import ThreadPoolExecutor
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
def get_last_certificate_number_int():
    """Returns the integer part of the last certificate number"""
    START_NUMBER = 274
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT certificate_number FROM certificates ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        return START_NUMBER - 1

    match = re.search(r"(\d+)$", row[0])
    db_last_no = int(match.group(1)) if match else 0
    
    # Return whichever is higher: the sequence from DB or the START_NUMBER
    return max(db_last_no, START_NUMBER - 1)

def format_certificate_number(number):
    PAD_LENGTH = 3
    return f"ACDT-C-25-{number:0{PAD_LENGTH}d}"

def get_next_certificate_number():
    last_no = get_last_certificate_number_int()
    return format_certificate_number(last_no + 1)


# ---------------- SEMESTER FORMAT ----------------
def format_semester(semester):
    if semester is None or pd.isna(semester):
        return ""

    semester = str(semester).strip()
    if not semester:
        return ""

    match = re.match(r"^(\d+)(st|nd|rd|th)$", semester, re.IGNORECASE)
    if match:
        return f"{match.group(1)}<sup>{match.group(2)}</sup>"

    if semester.isdigit():
        sem = int(semester)
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(sem % 10, "th")
        return f"{sem}{suffix}"

    return semester

def get_font_size(name):
    """Calculate dynamic font size based on name length.
    More aggressive scaling to ensure names fit on one line.
    """
    length = len(str(name))
    if length > 25: return "28px"
    if length > 20: return "34px"
    if length > 15: return "40px"
    return "52px"


# ---------------- INTERNSHIP DURATION ----------------
def format_internship_duration(row):
    hours = row.get("internship_hours")
    if not pd.isna(hours) and str(hours).strip():
        return f"{int(hours)} Hours"

    # Support various date column names
    start = row.get("start_date") or row.get("joining_date") or row.get("start")
    end = row.get("end_date") or row.get("ending_date") or row.get("end")

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
        cert_type_preference = request.form.get("cert_type", "auto")

        # ===================== BULK MODE =====================
        if excel_file and excel_file.filename:
            try:
                # Smart detect header row
                header_row_idx = detect_header_row(excel_file)
                
                # Reset file pointer after detection read
                excel_file.seek(0)

                df = pd.read_excel(excel_file, header=header_row_idx)
                
                # Cleanup: remove completely empty rows and convert all headers to string
                df = df.dropna(how='all')
                df.columns = [str(c).strip() for c in df.columns]

                # Normalize column names
                df.columns = (
                    pd.Series(df.columns)
                    .str.lower()
                    .str.replace(r"\s+", "_", regex=True)
                )
                
                # Further cleanup: remove rows where the student name is missing
                name_cols = ["student_name", "full_name", "name", "full_name_with_initial", "studentname"]
                actual_name_col = next((c for c in name_cols if c in df.columns), None)
                if actual_name_col:
                    df = df[df[actual_name_col].astype(str).str.strip().ne("nan") & df[actual_name_col].astype(str).str.strip().ne("")]
                
                df = df.reset_index(drop=True)
                
                logger.info(f"Bulk generation started. Rows detected after cleanup: {len(df)}")
                if len(df) == 0:
                    return "Error: No valid data rows found in Excel file. Please check column headings."

                # Parse date columns safely (including user-defined ones)
                date_cols = ["issue_date", "date", "start_date", "end_date", "joining_date", "ending_date"]
                for col in date_cols:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

                pdf_files = []
                upload_tasks = []
                generation_info = []

                # Use a single connection for the whole batch
                conn = sqlite3.connect(DB_PATH)
                
                # Get starting number for this batch
                current_last_no = get_last_certificate_number_int()
                
                with ThreadPoolExecutor(max_workers=5) as executor:
                    for i, (_, row) in enumerate(df.iterrows()):
                        # Incremented number for each row
                        cert_no = format_certificate_number(current_last_no + i + 1)

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
                            if col == "semester":
                                template_context[col] = format_semester(value)
                            elif col == "internship_duration":
                                template_context[col] = format_internship_duration(row)
                            elif col in ["start_date", "end_date", "joining_date", "ending_date"] and not pd.isna(value):
                                template_context[col] = pd.to_datetime(value).strftime("%d-%m-%Y")
                            elif col == "issue_date":
                                template_context[col] = issue_date
                            else:
                                template_context[col] = safe_value(value)
                        
                        # Smart Mappings for user template (Support truncated names too)
                        if "course_name" not in template_context and "subject" in template_context:
                            template_context["course_name"] = template_context["subject"]
                        if "internship_program" not in template_context:
                            template_context["internship_program"] = template_context.get("subject") or template_context.get("department", "")
                        
                        # Handle "Register Numbe" or "Register Number" or "Reg ID"
                        reg_val = None
                        for key in template_context.keys():
                            if "register" in key or "reg" in key:
                                reg_val = template_context[key]
                                break
                        if reg_val:
                            template_context["reg_id"] = reg_val
                            template_context["register_number"] = reg_val
                        
                        if "internship_duration" not in template_context:
                            template_context["internship_duration"] = format_internship_duration(row)

                        template = Template(custom_content)
                        rendered_body = template.render(**template_context)

                        # Determine Title
                        if cert_type_preference == "internship":
                            cert_title = "INTERNSHIP"
                        elif cert_type_preference == "industrial_visit":
                            cert_title = "INDUSTRIAL VISIT"
                        else:
                            # Auto-detect logic
                            subject_val = str(template_context.get("subject", "")).lower()
                            program_val = str(template_context.get("internship_program", "")).lower()
                            content_lower = rendered_body.lower()
                            
                            if "industrial visit" in subject_val or "industrial visit" in program_val or "industrial visit" in content_lower:
                                cert_title = "INDUSTRIAL VISIT"
                            else:
                                cert_title = "INTERNSHIP"

                        student_name_val = (
                            row.get("student_name") or 
                            row.get("full_name") or 
                            row.get("name") or 
                            row.get("full_name_with_initial")
                        )

                        context = {
                            "student_name": safe_value(student_name_val),
                            "student_name_style": f"font-size: {get_font_size(student_name_val)};",
                            "certificate_body": rendered_body,
                            "certificate_title": cert_title,
                            "certificate_number": cert_no,
                            "place": safe_value(row.get("place")),
                            "issue_date": issue_date,
                            "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
                        }

                        selected_template = request.form.get("template", "certificate.html")
                        html = render_template(selected_template, **context)

                        os.makedirs(PDF_DIR, exist_ok=True)
                        pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

                        # Generate PDF
                        HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
                        pdf_files.append(pdf_path)
                        
                        # Queue Cloudinary upload (Parallel)
                        upload_tasks.append(executor.submit(upload_to_cloudinary, pdf_path, cert_no))
                        
                        # Store info for DB insertion later
                        generation_info.append({
                            "cert_no": cert_no,
                            "name": context["student_name"],
                            "path": pdf_path
                        })
                        
                        # Clean up memory
                        del html
                        gc.collect()

                    # Wait for all uploads and update DB
                    for i, future in enumerate(upload_tasks):
                        cloudinary_url = future.result()
                        info = generation_info[i]
                        
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO certificates (certificate_number, student_name, pdf_path, cloudinary_url) VALUES (?, ?, ?, ?)",
                            (info["cert_no"], info["name"], info["path"], cloudinary_url)
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
                if cert_type_preference == "internship":
                    cert_title = "INTERNSHIP"
                elif cert_type_preference == "industrial_visit":
                    cert_title = "INDUSTRIAL VISIT"
                else:
                    content_lower = rendered_body.lower()
                    if "industrial visit" in content_lower:
                        cert_title = "INDUSTRIAL VISIT"
                    else:
                        cert_title = "INTERNSHIP"

                context = {
                    "student_name": safe_value(single_name),
                    "student_name_style": f"font-size: {get_font_size(single_name)};",
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
