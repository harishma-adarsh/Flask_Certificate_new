# import os
# import sqlite3
# import pandas as pd
# import re
# import zipfile
# from datetime import datetime
# from flask import Flask, render_template, request, send_file
# from weasyprint import HTML
# from jinja2 import Template

# app = Flask(__name__)

# # ---------------- PATHS ----------------
# BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# DB_PATH = os.path.join(BASE_DIR, "certificates.db")
# PDF_DIR = os.path.join(BASE_DIR, "generated", "pdfs")


# # ---------------- DATABASE INIT ----------------
# def init_db():
#     conn = sqlite3.connect(DB_PATH)
#     c = conn.cursor()
#     c.execute("""
#         CREATE TABLE IF NOT EXISTS certificates (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             certificate_number TEXT,
#             student_name TEXT,
#             pdf_path TEXT
#         )
#     """)
#     conn.commit()
#     conn.close()


# # ---------------- CERTIFICATE NUMBER ----------------
# def get_next_certificate_number():
#     START_NUMBER = 1      # numeric value
#     PAD_LENGTH = 3        # number of digits → 001

#     conn = sqlite3.connect(DB_PATH)
#     c = conn.cursor()
#     c.execute("SELECT certificate_number FROM certificates ORDER BY id DESC LIMIT 1")
#     row = c.fetchone()
#     conn.close()

#     if not row:
#         return f"ACDT-C-25-{START_NUMBER:0{PAD_LENGTH}d}"

#     match = re.search(r"(\d+)$", row[0])
#     last_no = int(match.group(1)) if match else START_NUMBER - 1
#     next_no = last_no + 1

#     return f"ACDT-C-25-{next_no:0{PAD_LENGTH}d}"




# # ---------------- SEMESTER FORMAT ----------------
# def format_semester(semester):
#     if not semester:
#         return ""

#     semester = str(semester).strip()

#     # Handles 3rd, 2nd, 4th
#     match = re.match(r"^(\d+)(st|nd|rd|th)$", semester, re.IGNORECASE)
#     if match:
#         return f"{match.group(1)}<sup>{match.group(2)}</sup>"

#     # Handles only numbers
#     if semester.isdigit():
#         sem = int(semester)
#         if 11 <= sem % 100 <= 13:
#             suffix = "th"
#         else:
#             suffix = {1: "st", 2: "nd", 3: "rd"}.get(sem % 10, "th")
#         return f"{sem}<sup>{suffix}</sup>"

#     return semester


# # ---------------- INTERNSHIP DURATION ----------------
# def format_internship_duration(row):
#     """
#     Priority:
#     1. internship_hours
#     2. start_date + end_date
#     """

#     hours = row.get("internship_hours", "")
#     if pd.notna(hours) and str(hours).strip() != "":
#         return f"{int(hours)} Hours"

#     start = row.get("start_date", "")
#     end = row.get("end_date", "")

#     if pd.notna(start) and pd.notna(end):
#         try:
#             start_fmt = pd.to_datetime(start).strftime("%d-%m-%Y")
#             end_fmt = pd.to_datetime(end).strftime("%d-%m-%Y")
#             return f"from {start_fmt} to {end_fmt}"
#         except:
#             pass

#     return ""


# # ---------------- ROUTE ----------------
# @app.route("/", methods=["GET", "POST"])
# def upload():

#     if request.method == "POST":

#         excel_file = request.files.get("excel")
#         custom_content = request.form.get("content", "").strip()
#         single_name = request.form.get("student_name", "").strip()

#         # ======================================================
#         # BULK MODE
#         # ======================================================
#         if excel_file and excel_file.filename:

#             df = pd.read_excel(excel_file)

#             # Normalize column names
#             df.columns = (
#                 df.columns.astype(str)
#                 .str.strip()
#                 .str.lower()
#                 .str.replace(r"\s+", "_", regex=True)
#             )

#             # Parse dates safely
#             for col in ["issue_date", "start_date", "end_date"]:
#                 if col in df.columns:
#                     df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

#             pdf_files = []

#             for _, row in df.iterrows():

#                 cert_no = get_next_certificate_number()

#                 issue_date = ""
#                 if "issue_date" in row and not pd.isna(row["issue_date"]):
#                     issue_date = row["issue_date"].strftime("%d-%m-%Y")

#                 template = Template(custom_content)
#                 rendered_body = template.render(
#                     college_name=row.get("college_name", ""),
#                     college_location=row.get("college_location", ""),
#                     semester=format_semester(row.get("semester", "")),
#                     course_name=row.get("course_name", ""),
#                     reg_id=row.get("reg_id", ""),
#                     internship_duration=format_internship_duration(row),
#                     internship_program=row.get("internship_program", "")
#                 )

#                 context = {
#                     "student_name": row.get("student_name", ""),
#                     "certificate_body": rendered_body,
#                     "certificate_number": cert_no,
#                     "place": row.get("place", ""),
#                     "issue_date": issue_date,
#                     "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
#                 }

#                 html = render_template("certificate.html", **context)

#                 os.makedirs(PDF_DIR, exist_ok=True)
#                 pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

#                 HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
#                 pdf_files.append(pdf_path)

#                 # Save DB record
#                 conn = sqlite3.connect(DB_PATH)
#                 c = conn.cursor()
#                 c.execute(
#                     "INSERT INTO certificates (certificate_number, student_name, pdf_path) VALUES (?, ?, ?)",
#                     (cert_no, row.get("student_name", ""), pdf_path)
#                 )
#                 conn.commit()
#                 conn.close()

#             # ZIP download
#             zip_path = os.path.join(PDF_DIR, "certificates.zip")
#             if os.path.exists(zip_path):
#                 os.remove(zip_path)

#             with zipfile.ZipFile(zip_path, "w") as zipf:
#                 for pdf in pdf_files:
#                     zipf.write(pdf, os.path.basename(pdf))

#             return send_file(zip_path, as_attachment=True, download_name="certificates.zip")

#         # ======================================================
#         # SINGLE MODE
#         # ======================================================
#         elif single_name and custom_content:

#             raw_date = request.form.get("single_date", "")
#             single_place = request.form.get("single_place", "")

#             single_date = ""
#             if raw_date:
#                 single_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d-%m-%Y")

#             cert_no = get_next_certificate_number()

#             template = Template(custom_content)
#             rendered_body = template.render()

#             context = {
#                 "student_name": single_name,
#                 "certificate_body": rendered_body,
#                 "certificate_number": cert_no,
#                 "single_place": single_place,
#                 "single_issue_date": single_date,
#                 "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
#             }

#             html = render_template("certificate.html", **context)

#             os.makedirs(PDF_DIR, exist_ok=True)
#             pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

#             HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
#             return send_file(pdf_path, as_attachment=True)

#         return "Error: Upload Excel or enter Student Name"

#     return render_template("upload.html")


# # ---------------- MAIN ----------------
# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 10000))
#     app.run(host="0.0.0.0", port=port)
import os
import sqlite3
import pandas as pd
import re
import zipfile
from datetime import datetime
from flask import Flask, render_template, request, send_file
from weasyprint import HTML
from jinja2 import Template

app = Flask(__name__)

# ---------------- PATHS ----------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "certificates.db")
PDF_DIR = os.path.join(BASE_DIR, "generated", "pdfs")


# ---------------- DATABASE INIT ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            certificate_number TEXT,
            student_name TEXT,
            pdf_path TEXT
        )
    """)
    conn.commit()
    conn.close()


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


# ---------------- GET TEMPLATES ----------------
def get_certificate_templates():
    """
    Returns a list of available certificate HTML templates.
    Scans the 'templates' directory for files starting with 'certificate' and ending with '.html'.
    """
    templates_dir = os.path.join(BASE_DIR, "templates")
    files = [f for f in os.listdir(templates_dir) if f.startswith("certificate") and f.endswith(".html")]
    return sorted(files)


# ---------------- ROUTE ----------------
@app.route("/", methods=["GET", "POST"])
def upload():

    available_templates = get_certificate_templates()

    if request.method == "POST":

        excel_file = request.files.get("excel")
        custom_content = request.form.get("content", "").strip()
        single_name = request.form.get("student_name", "").strip()
        selected_template = request.form.get("template_name", "certificate.html")

        # Validate selected template
        if selected_template not in available_templates:
            selected_template = "certificate.html"

        # ===================== BULK MODE =====================
        if excel_file and excel_file.filename:

            df = pd.read_excel(excel_file)

            # Normalize column names
            df.columns = (
                df.columns.astype(str)
                .str.strip()
                .str.lower()
                .str.replace(r"\s+", "_", regex=True)
            )

            # Parse date columns safely
            for col in ["issue_date", "start_date", "end_date"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

            pdf_files = []

            for _, row in df.iterrows():

                cert_no = get_next_certificate_number()

                issue_date = ""
                if "issue_date" in row and not pd.isna(row["issue_date"]):
                    issue_date = row["issue_date"].strftime("%d-%m-%Y")

                template = Template(custom_content)
                rendered_body = template.render(
                    college_name=safe_value(row.get("college_name")),
                    college_location=safe_value(row.get("college_location")),
                    semester=format_semester(row.get("semester")),
                    course_name=safe_value(row.get("course_name")),
                    reg_id=safe_value(row.get("reg_id")),
                    internship_duration=format_internship_duration(row),
                    internship_program=safe_value(row.get("internship_program"))
                )

                context = {
                    "student_name": safe_value(row.get("student_name")),
                    "certificate_body": rendered_body,
                    "certificate_number": cert_no,
                    "place": safe_value(row.get("place")),
                    "issue_date": issue_date,
                    "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
                }

                html = render_template(selected_template, **context)

                os.makedirs(PDF_DIR, exist_ok=True)
                pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

                HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
                pdf_files.append(pdf_path)

                # Save DB record
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute(
                    "INSERT INTO certificates (certificate_number, student_name, pdf_path) VALUES (?, ?, ?)",
                    (cert_no, context["student_name"], pdf_path)
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

        # ===================== SINGLE MODE =====================
        elif single_name and custom_content:

            raw_date = request.form.get("single_date", "")
            single_place = request.form.get("single_place", "")

            single_date = ""
            if raw_date:
                single_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d-%m-%Y")

            cert_no = get_next_certificate_number()

            template = Template(custom_content)
            rendered_body = template.render()

            context = {
                "student_name": safe_value(single_name),
                "certificate_body": rendered_body,
                "certificate_number": cert_no,
                "single_place": safe_value(single_place),
                "single_issue_date": single_date,
                "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
            }

            html = render_template(selected_template, **context)

            os.makedirs(PDF_DIR, exist_ok=True)
            pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

            HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
            return send_file(pdf_path, as_attachment=True)

        return "Error: Upload Excel or enter Student Name"

    return render_template("upload.html", templates=available_templates)


# ---------------- INITIALIZE ----------------
with app.app_context():
    init_db()

# ---------------- MAIN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

