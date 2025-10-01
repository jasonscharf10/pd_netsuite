import requests
import base64
import streamlit as st
from requests_oauthlib import OAuth1
import os 
import tempfile 
import pandas as pd

st.title("PandaDoc to NetSuite New Vendor Request")

pandadoc_doc_id = st.text_input("Enter PandaDoc Document ID:")

netsuite_payload = {}


def collect_files_from_pandadoc(document_data, file_fields):
    """
    Download files from PandaDoc by a list of field_ids,
    base64-encode them, and return a dict:
    {filename1: ..., content1: ..., filename2: ..., content2: ..., ...}
    """
    result = {}
    for idx, field_id in enumerate(file_fields, start=1):
        try:
            val = next((f["value"] for f in document_data.get("fields", []) if f.get("field_id") == field_id), None)
            if not (val and isinstance(val, dict) and val.get("url")):
                continue  # Field missing, skip
            file_url = val["url"]
            file_name = val.get("name", f"{field_id}.bin")
            # Download to unique temp file
            with requests.get(file_url, stream=True) as fr:
                fr.raise_for_status()
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[-1]) as tmpf:
                    for chunk in fr.iter_content(chunk_size=8192):
                        tmpf.write(chunk)
                    temp_path = tmpf.name
            with open(temp_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            os.remove(temp_path)
            result[f"filename{idx}"] = file_name
            result[f"content{idx}"] = b64
        except Exception as exc:
            print(f"Failed to process {field_id}: {exc}")
            continue
    return result

if pandadoc_doc_id:
    with st.spinner("Fetching PandaDoc document details..."):
        PANDADOC_API_TOKEN = st.secrets["pandadoc"]["token"]
        pandadoc_headers = {
            "Authorization": f"API-Key {PANDADOC_API_TOKEN}",
            "Content-Type": "application/json"
        }
        pandadoc_url = f"https://api.pandadoc.com/public/v1/documents/{pandadoc_doc_id}/details"
        resp = requests.get(pandadoc_url, headers=pandadoc_headers)
        resp.raise_for_status()
        pandadoc_data = resp.json()

    # Now safely add files_payload into your NetSuite/RESTlet payload as before:

    # Field mapping (as in prior code)
    field_id_to_value = {field["field_id"]: field["value"] for field in pandadoc_data.get("fields", [])}
    PAYMENT_TERMS_ENUM = {"Net 15": "1", "Net 30": "1"}
    CURRENCY_ENUM = {"UAH": "6", "PLN": "7", "USD": "1"}
    PAYMENT_METHOD_ENUM = {"ACH": "1", "Wire": "4"}
    # CUSTOM_FORM_ENUM = {"PandaDoc United States- New Vendor Request Form": "45"}
    PANDADOC_TO_NETSUITE_FIELD_IDS = {
        "Text1": "custrecord_company_name",
        "Text1_1_1": "custrecord_vr_email",
        "Text1_1_1_1": "custrecord_vr_website",
        "Text1_1": "custrecord1524",
        "Dropdown2": "custrecord_vr_payment_terms",
        "Text3": "custrecord1531",
        "Dropdown1": "custrecord_vr_pref_pymt_method",
        "Text2": "custrecord_vr_tax_id",
        "Checkbox1": "custrecord_vr_1099",
        # "Dropdown3": "customform"
    }
    for pd_field_id, ns_key in PANDADOC_TO_NETSUITE_FIELD_IDS.items():
        val = field_id_to_value.get(pd_field_id, "")
        if ns_key == "custrecord_vr_payment_terms":
            val = PAYMENT_TERMS_ENUM.get(val, "")
        elif ns_key == "custrecord1531":
            val = CURRENCY_ENUM.get(val, "")
        elif ns_key == "custrecord_vr_pref_pymt_method":
            val = PAYMENT_METHOD_ENUM.get(val, "")
        # elif ns_key == "customform":
        #     val = CUSTOM_FORM_ENUM.get(val, "")
        netsuite_payload[ns_key] = val
    # netsuite_payload["custrecord_vr_category"] = "1"
    # netsuite_payload["custrecord1553"] = "N/A"
# Prepare preview rows
    preview_rows = []
    for pd_field_id, ns_key in PANDADOC_TO_NETSUITE_FIELD_IDS.items():
        value = field_id_to_value.get(pd_field_id, None)
        # If you have enum mapping logic for this key, map as your script does:
        display_value = value
        if ns_key == "custrecord_vr_payment_terms":
            display_value = PAYMENT_TERMS_ENUM.get(value, value)
        elif ns_key == "custrecord1531":
            display_value = CURRENCY_ENUM.get(value, value)
        elif ns_key == "custrecord_vr_pref_pymt_method":
            display_value = PAYMENT_METHOD_ENUM.get(value, value)
        preview_rows.append({
            "PandaDoc Field ID": pd_field_id,
            "NetSuite Field": ns_key,
            "PandaDoc Value": value if value != None else "❌ Missing",
            "Payload Value": display_value if display_value != None else "❌ Missing"
        })

    # Present as a nice dataframe
    preview_df = pd.DataFrame(preview_rows)
    st.write("### PandaDoc to NetSuite Mapping Preview")
    st.dataframe(preview_df, use_container_width=True)
    def fix_url(url):
        if not url or url.strip() == "":
            return None
        if url.startswith(("http://", "https://", "ftp://", "file://")):
            return url
        # If user provided only www..., prepend https://
        return "https://" + url

    # Fix website field before sending payload
    if "custrecord_vr_website" in netsuite_payload:
        netsuite_payload["custrecord_vr_website"] = fix_url(netsuite_payload["custrecord_vr_website"])
        
    # Package final RESTlet payload (only actual files included)
    payload = {
        "folderid": "367946",
        "customrec_type": "customrecord_vendor_request",
        "otherfields": netsuite_payload,
    }
    files_payload = collect_files_from_pandadoc(pandadoc_data, ["CollectFile1", "CollectFile2"])
    print(f"files_payload: {files_payload}")

    payload.update(files_payload)  # Dynamically adds only present file fields
    print(f"Final RESTlet payload: {payload}")

# Your RESTlet endpoint and NetSuite auth headers for RESTlet (NLAuth, Token-Based, or OAuth)
    restlet_url = "https://4454619-sb1.restlets.api.netsuite.com/app/site/hosting/restlet.nl?script=3116&deploy=1"
    ACCOUNT_ID = st.secrets["netsuite"]["account_id"]
    CONSUMER_KEY = st.secrets["netsuite"]["consumer_key"]
    CONSUMER_SECRET = st.secrets["netsuite"]["consumer_secret"]
    TOKEN_KEY = st.secrets["netsuite"]["token_key"]
    TOKEN_SECRET = st.secrets["netsuite"]["token_secret"]

    auth = OAuth1(
        client_key=CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        resource_owner_key=TOKEN_KEY,
        resource_owner_secret=TOKEN_SECRET,
        signature_method="HMAC-SHA256",
        signature_type="AUTH_HEADER",
        realm='4454619_SB1'
)
    # --- Final call to NetSuite RESTlet ---
    with st.spinner("Uploading file(s) and record..."):
        response = requests.post(restlet_url,auth=auth, headers={"Content-Type": "application/json"}, json=payload)
    try:
        result = response.json()
        if result.get("recordId"):
            st.success(f"SUCCESS! | RecordId: {result.get('recordId')}")
            netsuite_url = f"https://4454619-sb1.app.netsuite.com/app/common/custom/custrecordentry.nl?rectype=435&id={result.get('recordId')}"
            st.markdown(f"[Open NetSuite Record]({netsuite_url})", unsafe_allow_html=True)
            st.balloons()
        else:
            st.error(f"Upload failed: (No recordId returned):\n{result}")
    except Exception as exc:
        st.error(f"Upload failed: {exc}\nRaw Response: {response.text}")

else:
    st.info("Enter a PandaDoc document ID to get started.")

st.caption("© PandaDoc 2025 – Automated NetSuite integration via Streamlit")