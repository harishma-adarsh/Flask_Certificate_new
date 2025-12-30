
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
#     conn = sqlite3.connect(DB_PATH)
#     c = conn.cursor()
#     c.execute("SELECT certificate_number FROM certificates ORDER BY id DESC LIMIT 1")
#     row = c.fetchone()
#     conn.close()

#     if not row:
#         return "ACDT-C-25-001"

#     match = re.search(r"(\d+)$", row[0])
#     next_no = 1 if not match else int(match.group(1)) + 1
#     return f"ACDT-C-25-{next_no:03d}"


# # ---------------- SEMESTER FORMATTER ----------------
# def format_semester(semester):
#     """
#     Handles:
#     3      → 3<sup>rd</sup>
#     3rd    → 3<sup>rd</sup>
#     2nd    → 2<sup>nd</sup>
#     11th   → 11<sup>th</sup>
#     """

#     if not semester:
#         return ""

#     semester = str(semester).strip()

#     # Case 1: already like "3rd", "2nd", "4th"
#     match = re.match(r"^(\d+)(st|nd|rd|th)$", semester, re.IGNORECASE)
#     if match:
#         number = match.group(1)
#         suffix = match.group(2)
#         return f"{number}<sup>{suffix}</sup>"

#     # Case 2: only number like "3"
#     if semester.isdigit():
#         sem = int(semester)
#         if 11 <= sem % 100 <= 13:
#             suffix = "th"
#         else:
#             suffix = {1: "st", 2: "nd", 3: "rd"}.get(sem % 10, "th")
#         return f"{sem}<sup>{suffix}</sup>"

#     # Fallback
#     return semester



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

#             if "issue_date" in df.columns:
#                 df["issue_date"] = pd.to_datetime(df["issue_date"], dayfirst=True)

#             pdf_files = []

#             for _, row in df.iterrows():

#                 cert_no = get_next_certificate_number()

#                 issue_date = ""
#                 if "issue_date" in row and not pd.isna(row["issue_date"]):
#                     issue_date = row["issue_date"].strftime("%d-%m-%Y")

#                 # semester_num, semester_suffix = split_semester(row.get("semester", ""))

#                 template = Template(custom_content)
#                 rendered_body = template.render(
#                     college_name=row.get("college_name", ""),
#                     college_location=row.get("college_location", ""),
#                     semester=format_semester(row.get("semester", "")),
#                     course_name=row.get("course_name", ""),
#                     reg_id=row.get("reg_id", ""),
#                     internship_hours=row.get("internship_hours", ""),
#                     internship_program=row.get("internship_program", "")
# )


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
#     init_db()
#     app.run(debug=True)

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


# ---------------- CERTIFICATE NUMBER ----------------
def get_next_certificate_number():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT certificate_number FROM certificates ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        return "ACDT-C-25-001"

    match = re.search(r"(\d+)$", row[0])
    next_no = 1 if not match else int(match.group(1)) + 1
    return f"ACDT-C-25-{next_no:03d}"


# ---------------- SEMESTER FORMAT ----------------
def format_semester(semester):
    if not semester:
        return ""

    semester = str(semester).strip()

    # Handles 3rd, 2nd, 4th
    match = re.match(r"^(\d+)(st|nd|rd|th)$", semester, re.IGNORECASE)
    if match:
        return f"{match.group(1)}<sup>{match.group(2)}</sup>"

    # Handles only numbers
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
    """
    Priority:
    1. internship_hours
    2. start_date + end_date
    """

    hours = row.get("internship_hours", "")
    if pd.notna(hours) and str(hours).strip() != "":
        return f"{int(hours)} Hours"

    start = row.get("start_date", "")
    end = row.get("end_date", "")

    if pd.notna(start) and pd.notna(end):
        try:
            start_fmt = pd.to_datetime(start).strftime("%d-%m-%Y")
            end_fmt = pd.to_datetime(end).strftime("%d-%m-%Y")
            return f"from {start_fmt} to {end_fmt}"
        except:
            pass

    return ""


# ---------------- ROUTE ----------------
@app.route("/", methods=["GET", "POST"])
def upload():

    if request.method == "POST":

        excel_file = request.files.get("excel")
        custom_content = request.form.get("content", "").strip()
        single_name = request.form.get("student_name", "").strip()

        # ======================================================
        # BULK MODE
        # ======================================================
        if excel_file and excel_file.filename:

            df = pd.read_excel(excel_file)

            # Normalize column names
            df.columns = (
                df.columns.astype(str)
                .str.strip()
                .str.lower()
                .str.replace(r"\s+", "_", regex=True)
            )

            # Parse dates safely
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
                    college_name=row.get("college_name", ""),
                    college_location=row.get("college_location", ""),
                    semester=format_semester(row.get("semester", "")),
                    course_name=row.get("course_name", ""),
                    reg_id=row.get("reg_id", ""),
                    internship_duration=format_internship_duration(row),
                    internship_program=row.get("internship_program", "")
                )

                context = {
                    "student_name": row.get("student_name", ""),
                    "certificate_body": rendered_body,
                    "certificate_number": cert_no,
                    "place": row.get("place", ""),
                    "issue_date": issue_date,
                    "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
                }

                html = render_template("certificate.html", **context)

                os.makedirs(PDF_DIR, exist_ok=True)
                pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

                HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
                pdf_files.append(pdf_path)

                # Save DB record
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute(
                    "INSERT INTO certificates (certificate_number, student_name, pdf_path) VALUES (?, ?, ?)",
                    (cert_no, row.get("student_name", ""), pdf_path)
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

        # ======================================================
        # SINGLE MODE
        # ======================================================
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
                "student_name": single_name,
                "certificate_body": rendered_body,
                "certificate_number": cert_no,
                "single_place": single_place,
                "single_issue_date": single_date,
                "base_url": f"file:///{BASE_DIR.replace(os.sep, '/')}"
            }

            html = render_template("certificate.html", **context)

            os.makedirs(PDF_DIR, exist_ok=True)
            pdf_path = os.path.join(PDF_DIR, f"{cert_no}.pdf")

            HTML(string=html, base_url=BASE_DIR).write_pdf(pdf_path)
            return send_file(pdf_path, as_attachment=True)

        return "Error: Upload Excel or enter Student Name"

    return render_template("upload.html")


# ---------------- MAIN ----------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)


