import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime
import time

# --- CONNECT (WITH CACHING TO FIX ERRORS) ---
@st.cache_resource
def get_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_sheet():
    client = get_client()
    # Replace this with your actual URL if needed, or use the one below
    url = "https://docs.google.com/spreadsheets/d/1KG8qWTYLa6GEWByYIg2vz3bHrGdW3gvqD_detwhyj7k/edit"
    return client.open_by_url(url)

# --- USER & LOGS ---
def get_users():
    ws = get_sheet().worksheet("users")
    return pd.DataFrame(ws.get_all_records())

def register_user(username, password, email):
    ws = get_sheet().worksheet("users")
    ws.append_row([username, password, email, "pending", "user"])

def log_action(user, action, details):
    try:
        ws = get_sheet().worksheet("logs")
        ws.append_row([str(datetime.now()), user, action, details])
    except:
        pass # Don't crash app if logging fails

# --- SCHEMA MANAGEMENT ---
def get_schema():
    try:
        ws = get_sheet().worksheet("schema")
        return ws.col_values(1)[1:] 
    except:
        return []

def add_schema_column(col_name):
    ws = get_sheet().worksheet("schema")
    existing = ws.col_values(1)
    if col_name not in existing:
        ws.append_row([col_name])
        sync_products_headers()

def delete_schema_column(col_name):
    ws = get_sheet().worksheet("schema")
    try:
        cell = ws.find(col_name)
        ws.delete_rows(cell.row)
    except:
        pass

def sync_products_headers():
    schema_cols = get_schema()
    ws_prod = get_sheet().worksheet("products")
    current_headers = ws_prod.row_values(1)
    
    if "category" not in current_headers: 
        ws_prod.update_cell(1, 1, "category")
        current_headers.append("category")
    
    for col in schema_cols:
        if col not in current_headers:
            ws_prod.update_cell(1, len(current_headers) + 1, col)
            current_headers.append(col)
            
    if "last_updated" not in current_headers:
        ws_prod.update_cell(1, len(current_headers) + 1, "last_updated")

# --- CATEGORIES ---
def get_categories():
    ws = get_sheet().worksheet("categories")
    records = ws.get_all_records()
    return [r['category_name'] for r in records]

def add_category(name, user):
    ws = get_sheet().worksheet("categories")
    ws.append_row([name, user, str(datetime.now())])

# --- SAVING & UPDATING ---
def save_products_dynamic(df, category, user):
    sh = get_sheet()
    ws = sh.worksheet("products")
    sync_products_headers()
    
    headers = ws.row_values(1)
    header_map = {name: i+1 for i, name in enumerate(headers)}
    timestamp = str(datetime.now())
    rows_to_append = []
    
    for _, row in df.iterrows():
        db_row = [""] * len(headers)
        db_row[header_map["category"]-1] = category
        db_row[header_map["last_updated"]-1] = timestamp
        
        for col_name in df.columns:
            if col_name in header_map:
                val = str(row[col_name]) if pd.notnull(row[col_name]) else ""
                db_row[header_map[col_name]-1] = val
        rows_to_append.append(db_row)
        
    ws.append_rows(rows_to_append)
    log_action(user, "Upload Products", f"Category: {category}, Items: {len(df)}")

def update_products_dynamic(new_df, category, user, key_column):
    """
    Updates existing products in a category based on a Key Column (e.g. 'Product Name').
    1. Fetches current DB data.
    2. Identifies New vs Existing vs EOL.
    3. Returns summary stats.
    NOTE: This APPENDS new versions. To fully replace, we'd need to clear rows, 
    but for safety/history we usually append or mark status. 
    """
    sh = get_sheet()
    ws = sh.worksheet("products")
    ws_eol = sh.worksheet("eol_products")
    sync_products_headers()
    
    # 1. Get Existing
    all_data = pd.DataFrame(ws.get_all_records())
    
    # If key_column not in data, we can't update
    if key_column not in new_df.columns:
        return {"error": f"Key column '{key_column}' missing in upload."}

    # Filter for this category only
    if not all_data.empty:
        current_data = all_data[all_data['category'] == category]
        existing_keys = set(current_data[key_column].astype(str))
    else:
        existing_keys = set()
    
    new_keys = set(new_df[key_column].astype(str))
    
    # 2. Identify Status
    to_add_keys = new_keys - existing_keys
    eol_keys = existing_keys - new_keys
    
    # 3. Handle EOL (Archive)
    if not current_data.empty and eol_keys:
        eol_rows = current_data[current_data[key_column].astype(str).isin(eol_keys)]
        eol_archive = []
        for _, row in eol_rows.iterrows():
             # Basic EOL Archive format
             eol_archive.append([category, row.get(key_column, "Unknown"), "EOL", str(datetime.now())])
        if eol_archive:
            ws_eol.append_rows(eol_archive)

    # 4. Save the NEW batch (Treating update as new revision for safety)
    save_products_dynamic(new_df, category, user)
    
    return {"new": len(to_add_keys), "eol": len(eol_keys), "total_uploaded": len(new_df)}

def search_products(query):
    ws = get_sheet().worksheet("products")
    df = pd.DataFrame(ws.get_all_records())
    if df.empty: return df
    
    mask = df.astype(str).apply(lambda x: x.str.contains(query, case=False, na=False)).any(axis=1)
    return df[mask]
