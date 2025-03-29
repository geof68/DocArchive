# DocArchive

This Python script automates OCR, document analysis using Amazon Bedrock, and PDF archiving in Google Drive with structured metadata.

## Features

- OCR on PDF files (Tesseract)
- Metadata extraction using Amazon Bedrock (Claude 3 Haiku)
- Classification in Google Drive by document type and year
- Logging to a local CSV file

---

## Prerequisites


### macOS

- [Homebrew](https://brew.sh)
- Python 3.8+
- Tesseract with `fra` and `eng` languages
- AWS CLI
- Google service account JSON key with Drive access

---

## Installation

### 1. Install dependencies

```bash
brew install python tesseract tesseract-lang awscli
```

### 2. Set up Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**requirements.txt**:

```
pytesseract
pillow
boto3
google-api-python-client
google-auth
google-auth-oauthlib
python-dateutil
pymupdf
```

### 3. Configure AWS CLI

```bash
aws configure
```

Provide:

- AWS Access Key ID
- AWS Secret Access Key
- Region: `eu-west-1`

The account must have `bedrock:InvokeModel` permission on Claude 3 Haiku.

### 4. Configure Google Drive API

- Create a GCP project
- Enable the Google Drive API
- Create a service account with the `Editor` role
- Generate a JSON key (e.g., `docarchive-creds.json`)
- Place the JSON key file in the same directory as the script or specify the correct path in the script parameter `credentials_path`
- Share the root Drive folder with the service account's email
- Set the folder's ID in `ROOT_FOLDER_ID`

---

## Usage

```bash
python docarchive.py /path/to/file_or_folder
```

Dry-run mode (no upload):

```bash
python docarchive.py /path/to/folder --dry-run
```

---

## Drive Structure

```
ROOT_FOLDER_ID/
  Invoice/
    2023/
      Invoice - EDF - ab12cd34.pdf
```

---

## Logging

A `docarchive_log.csv` file is created with the following columns:

- Timestamp
- Filename
- Type
- Date
- Organization

---

## Author

Geoffray | MIT License

---

**Note**: For proper support of accents and French text, ensure Tesseract is installed with the required language data.