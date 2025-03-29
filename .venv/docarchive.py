import uuid
import os
import sys
import json
import re
import io
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import boto3
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import dateutil.parser
from botocore.exceptions import BotoCoreError, ClientError

# Chargement de l'ID du dossier racine Google Drive depuis une variable d'environnement
ROOT_FOLDER_ID = os.getenv("ROOT_FOLDER_ID", "root")  # "root" par défaut

# === 1. OCR ===
def extract_text_from_pdf(pdf_path):
    text = ""
    with fitz.open(pdf_path) as doc:
        for page_num, page in enumerate(doc, start=1):
            print(f"  - OCR page {page_num}/{len(doc)}")
            pix = page.get_pixmap()
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                page_text = pytesseract.image_to_string(img, lang="fra")
                if len(page_text.strip()) < 50:
                    print("    ⚠️ Peu de texte détecté, tentative en anglais.")
                    page_text = pytesseract.image_to_string(img, lang="eng")
            except pytesseract.TesseractError:
                print("    ⚠️ Erreur OCR en français, fallback en anglais.")
                page_text = pytesseract.image_to_string(img, lang="eng")
            text += page_text + "\n"
    text = re.sub(r"\n+", "\n", text).strip()
    return text

# === 2. BEDROCK ===
def ask_bedrock(text):
    prompt = f"""
Voici un texte de document. Tu dois en extraire les informations suivantes et les renvoyer en JSON strict :

{{
  "type": "le type du document (ex : facture, attestation, etc.)",
  "date": "la date du document",
  "organisation": "l'organisme ou entreprise émetteur",
  "description": "un résumé en moins de 150 mots"
}}

Texte :
{text}
"""

    client = boto3.client("bedrock-runtime", region_name="eu-west-1")

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.0
    }

    try:
        response = client.invoke_model(
            modelId="anthropic.claude-3-haiku-20240307-v1:0",
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )
    except (BotoCoreError, ClientError) as e:
        print("[⚠️] Erreur Bedrock :", e)
        return {
            "type": "Inconnu",
            "date": "1900",
            "organisation": "Inconnu",
            "description": "Erreur Bedrock"
        }

    raw_output = json.loads(response["body"].read())
    output_text = raw_output["content"][0]["text"]

    try:
        start = output_text.index("{")
        end = output_text.rindex("}") + 1
        return json.loads(output_text[start:end])
    except Exception as e:
        print("[⚠️] Échec du parsing JSON depuis Bedrock :", e)
        print("Sortie brute :", output_text)
        return {
            "type": "Inconnu",
            "date": "1900",
            "organisation": "Inconnu",
            "description": "Échec d'extraction automatique"
        }

# === 3. GOOGLE DRIVE ===
def get_file_year(pdf_path):
    try:
        ts = os.path.getmtime(pdf_path)
        dt = datetime.fromtimestamp(ts)
        return str(dt.year)
    except Exception:
        return "1900"

def escape_drive_name(name):
    return name.replace("'", "\\'")

def get_or_create_folder(service, name, parent_id=None):
    if parent_id is None:
        parent_id = ROOT_FOLDER_ID

    escaped_name = escape_drive_name(name)
    query = f"mimeType='application/vnd.google-apps.folder' and name='{escaped_name}' and '{parent_id}' in parents"
    results = service.files().list(q=query, fields="files(id)").execute()

    if results['files']:
        return results['files'][0]['id']

    metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }

    folder = service.files().create(body=metadata, fields='id').execute()
    return folder['id']

def upload_to_drive(pdf_path, metadata):
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")

    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=['https://www.googleapis.com/auth/drive']
    )
    service = build('drive', 'v3', credentials=creds)

    doc_type = metadata.get("type", "Inconnu")
    year = get_file_year(pdf_path)

    type_folder_id = get_or_create_folder(service, doc_type)
    year_folder_id = get_or_create_folder(service, year, type_folder_id)

    description_text = (
        f"Type : {metadata.get('type', 'Inconnu')}\n"
        f"Organisation : {metadata.get('organisation', 'Inconnue')}\n\n"
        f"{metadata.get('description', '')}"
    )

    unique_id = str(uuid.uuid4())[:8]
    type_clean = doc_type.replace("/", "-").strip()
    org_clean = metadata.get('organisation', 'Inconnu').replace("/", "-").strip()
    filename = f"{type_clean} - {org_clean} - {unique_id}.pdf"

    file_metadata = {
        'name': filename,
        'parents': [year_folder_id],
        'description': description_text
    }

    media = MediaFileUpload(pdf_path, mimetype='application/pdf')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    return file.get("id"), filename

# === 4. Logging ===
def log_entry(uploaded_filename, metadata):
    log_file = "docarchive_log.csv"
    exists = os.path.exists(log_file)
    with open(log_file, "a") as f:
        if not exists:
            f.write("timestamp;filename;type;date;organisation\n")
        f.write(f"{datetime.now().isoformat()};{uploaded_filename};"
                f"{metadata.get('type')};{metadata.get('date')};{metadata.get('organisation')}\n")

# === MAIN FLOW ===
def process_pdf(pdf_path, dry_run=False):
    print("🔍 Traitement du fichier :", pdf_path)

    print("[1] OCR...")
    text = extract_text_from_pdf(pdf_path)

    print("[2] Analyse avec Amazon Bedrock...")
    metadata = ask_bedrock(text)
    print("   ✅ Métadonnées :")
    print(json.dumps(metadata, indent=2, ensure_ascii=False))

    if not dry_run:
        print("[3] Upload vers Google Drive...")
        file_id, uploaded_filename = upload_to_drive(pdf_path, metadata)
        print(f"   ✅ Upload terminé. ID du fichier : {file_id}")
        print(f"   🔗 https://drive.google.com/file/d/{file_id}/view")

        print("[4] Journalisation...")
        log_entry(uploaded_filename, metadata)
        print("   ✅ Entrée enregistrée dans docarchive_log.csv")

        return uploaded_filename
    else:
        print("[DRY RUN] Aucun upload, suppression ou journalisation effectuée.")
        return None

def process_folder(folder_path, dry_run=False):
    total, success, errors = 0, 0, 0
    for file_name in os.listdir(folder_path):
        if file_name.lower().endswith(".pdf"):
            total += 1
            full_path = os.path.join(folder_path, file_name)
            print(f"\n=== Traitement du fichier : {file_name} ===")
            try:
                uploaded_filename = process_pdf(full_path, dry_run=dry_run)
                if not dry_run:
                    os.remove(full_path)
                    print(f"   🗑️ Fichier supprimé : {file_name}")
                success += 1
            except Exception as e:
                print(f"   ❌ Erreur sur {file_name} : {e}")
                errors += 1
    print(f"\n🧾 Résumé : {success}/{total} fichiers traités avec succès, {errors} échecs.")

# === EXECUTION ===
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python docarchive.py <chemin_du_pdf_ou_dossier> [--dry-run]")
        sys.exit(1)


    target_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if os.path.isdir(target_path):
        process_folder(target_path, dry_run=dry_run)
    elif os.path.isfile(target_path):
        process_pdf(target_path, dry_run=dry_run)
    else:
        print("Chemin invalide.")
