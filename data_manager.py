import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime
import time

# --- CONNECT (CACHED) ---
@st.cache_resource
def get_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_sheet():
    client = get_client()
    # Ensure this URL matches your actual Google Sheet URL
    url = "https://docs.google.com/spreadsheets/d/1KG8qWTYLa6GEWByYIg2vz3bHrGdW3gvqD_detwhyj7k/edit"
    return client.open_by_url(url)

# --- READ FUNCTIONS (CACHED TO PREVENT ERRORS) ---
@st.cache_data(ttl=60)
def get_users():
    ws = get_sheet().worksheet("users")
    return pd.DataFrame(ws.get_all_records())

@st.cache_data(ttl=60)
def get_categories():
    try:
        ws = get_sheet().worksheet("categories")
        records = ws.get_all_records()
        return [r['category_name'] for r in records]
    except:
        return []

@st.cache_data(ttl=60)
def get_schema():
    try:
        ws = get_sheet().worksheet("schema")
        return ws.col_values(1)[1:] 
    except:
        return []

@st.cache_data(ttl=60)
def get_all_products_df():
    """Fetch all products once and keep in memory."""
    ws = get_sheet().worksheet("products")
    return pd.DataFrame(ws.get_all_records())

# --- WRITE FUNCTIONS (NO CACHE) ---
def register_user(username, password, email):
    ws = get_sheet().worksheet("users")
    ws.append_row([username, password, email, "pending", "user"])
    get_users.clear() # Clear cache so new user appears immediately

def log_action(user, action, details):
    try:
        ws = get_sheet().worksheet("logs")
        ws.append_row([str(datetime.now()), user, action, details])
    except:
        pass 

def add_category(name, user):
    ws = get_sheet().worksheet("categories")
    ws.append_row([name, user, str(datetime.now())])
    get_categories.clear() # Force refresh next time

def add_schema_column(col_name):
    ws = get_sheet().worksheet("schema")
    existing = ws.col_values(1)
    if col_name not in existing:
        ws.append_row([col_name])
        sync_products_headers()
    get_schema.clear()

def delete_schema_column(col_name):
    ws = get_sheet().worksheet("schema")
    try:
        cell = ws.find(col_name)
        ws.delete_rows(cell.row)
        get_schema.clear()
    except:
        pass

def sync_products_headers():
    # Only run this when saving data, no cache needed
    client = get_client() 
    # Must use full URL here again to avoid cache issues inside this function
    sh = client.open_by_url("https://docs.google.com/spreadsheets/d/1KG8qWTYLa6GEWByYIg2vz3bHrGdW3gvqD_detwhyj7k/edit")
    ws_prod = sh.worksheet("products")
    ws_schema = sh.worksheet("schema")
    
    schema_cols = ws_schema.col_values(1)[1:]
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
    
    # IMPORTANT: Clear product cache so the search sees new items immediately
    get_all_products_df.clear()

def update_products_dynamic(new_df, category, user, key_column):
    sh = get_sheet()
    ws_eol = sh.worksheet("eol_products")
    
    # Use cached reading for speed
    all_data = get_all_products_df()
    
    if key_column not in new_df.columns:
        return {"error": f"Key column '{key_column}' missing in upload."}

    if not all_data.empty:
        current_data = all_data[all_data['category'] == category]
        existing_keys = set(current_data[key_column].astype(str))
    else:
        current_data = pd.DataFrame()
        existing_keys = set()
    
    new_keys = set(new_df[key_column].astype(str))
    
    # Identify differences
    to_add_keys = new_keys - existing_keys
    eol_keys = existing_keys - new_keys
    
    # Archive EOL
    if not current_data.empty and eol_keys:
        eol_rows = current_data[current_data[key_column].astype(str).isin(eol_keys)]
        eol_archive = []
        for _, row in eol_rows.iterrows():
             eol_archive.append([category, row.get(key_column, "Unknown"), "EOL", str(datetime.now())])
        if eol_archive:
            ws_eol.append_rows(eol_archive)

    # Save New Data
    save_products_dynamic(new_df, category, user)
    
    return {"new": len(to_add_keys), "eol": len(eol_keys), "total_uploaded": len(new_df)}
def search_products(query):
    # Backward compatibility wrapper just in case
    df = get_all_products_df()
    if df.empty: return df
    mask = df.astype(str).apply(lambda x: x.str.contains(query, case=False, na=False)).any(axis=1)
    return df[mask]
