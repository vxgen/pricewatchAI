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
    # REPLACE WITH YOUR ACTUAL SHEET URL
    url = "https://docs.google.com/spreadsheets/d/1KG8qWTYLa6GEWByYIg2vz3bHrGdW3gvqD_detwhyj7k/edit"
    return client.open_by_url(url)

# --- READ FUNCTIONS ---

@st.cache_data(ttl=60)
def get_users():
    try:
        ws = get_sheet().worksheet("users")
        return pd.DataFrame(ws.get_all_records())
    except:
        return pd.DataFrame(columns=["username", "password", "email", "status", "role"])

@st.cache_data(ttl=60)
def get_categories():
    try:
        ws = get_sheet().worksheet("categories")
        records = ws.get_all_records()
        if not records: 
            return []
        return [r['category_name'] for r in records if 'category_name' in r and r['category_name']]
    except:
        return []

@st.cache_data(ttl=60)
def get_schema():
    # Placeholder for compatibility
    return ["Product Name", "SKU", "Price", "Stock"] 

@st.cache_data(ttl=60)
def get_all_products_df():
    """
    Fetches data from ALL category worksheets and combines them.
    """
    sh = get_sheet()
    cats = get_categories()
    
    all_dfs = []
    
    for cat in cats:
        try:
            ws = sh.worksheet(cat)
            records = ws.get_all_records()
            
            if records:
                cat_df = pd.DataFrame(records)
                cat_df['category'] = cat 
                all_dfs.append(cat_df)
        except:
            continue

    if not all_dfs:
        return pd.DataFrame()

    final_df = pd.concat(all_dfs, ignore_index=True)
    final_df = final_df.dropna(axis=1, how='all')
    
    return final_df

# --- WRITE FUNCTIONS ---

def register_user(username, password, email):
    try:
        ws = get_sheet().worksheet("users")
    except:
        sh = get_sheet()
        ws = sh.add_worksheet(title="users", rows=100, cols=5)
        ws.append_row(["username", "password", "email", "status", "role"])
        
    ws.append_row([username, password, email, "pending", "user"])
    get_users.clear()

def log_action(user, action, details):
    try:
        ws = get_sheet().worksheet("logs")
        ws.append_row([str(datetime.now()), user, action, details])
    except:
        pass 

def ensure_category_sheet_exists(category_name):
    sh = get_sheet()
    try:
        ws = sh.worksheet(category_name)
        return ws
    except:
        # Create new sheet if missing
        ws = sh.add_worksheet(title=category_name, rows=1000, cols=26)
        return ws

def add_category(name, user):
    try:
        ws = get_sheet().worksheet("categories")
    except:
        sh = get_sheet()
        ws = sh.add_worksheet(title="categories", rows=100, cols=3)
        ws.append_row(["category_name", "created_by", "created_at"])
    
    existing = [r['category_name'] for r in ws.get_all_records()]
    if name not in existing:
        ws.append_row([name, user, str(datetime.now())])
        
    ensure_category_sheet_exists(name)
    get_categories.clear()

def save_products_dynamic(df, category, user):
    # 1. Ensure category exists
    add_category(category, user)
    
    # 2. Get worksheet
    ws = ensure_category_sheet_exists(category)
    
    # 3. Check if empty
    existing_data = ws.get_all_values()
    
    clean_df = df.astype(str)
    
    if not existing_data:
        # Write Headers + Data
        data = [clean_df.columns.tolist()] + clean_df.values.tolist()
        ws.update(values=data, range_name='A1')
    else:
        # Append Data
        ws.append_rows(clean_df.values.tolist())
    
    log_action(user, "Upload Direct", f"Category: {category}, Rows: {len(df)}")
    get_all_products_df.clear()

def update_products_dynamic(new_df, category, user, key_column):
    ws = ensure_category_sheet_exists(category)
    
    try:
        current_records = ws.get_all_records()
        current_df = pd.DataFrame(current_records)
    except:
        current_df = pd.DataFrame()

    eol_count = 0
    new_count = 0
    
    # Check differences if possible
    if not current_df.empty and key_column in current_df.columns and key_column in new_df.columns:
        current_keys = set(current_df[key_column].astype(str))
        new_keys = set(new_df[key_column].astype(str))
        
        eol_keys = current_keys - new_keys
        to_add_keys = new_keys - current_keys
        
        eol_count = len(eol_keys)
        new_count = len(to_add_keys)
        
        # Archive EOL
        if eol_keys:
            eol_rows = current_df[current_df[key_column].astype(str).isin(eol_keys)]
            eol_rows['eol_date'] = str(datetime.now())
            eol_rows['original_category'] = category
            
            try:
                sh = get_sheet()
                try:
                    ws_eol = sh.worksheet("eol_products")
                except:
                    ws_eol = sh.add_worksheet(title="eol_products", rows=1000, cols=20)
                    ws_eol.append_row(eol_rows.columns.tolist())
                
                ws_eol.append_rows(eol_rows.astype(str).values.tolist())
            except:
                pass

    # FULL OVERWRITE for Update
    ws.clear()
    
    clean_df = new_df.astype(str)
    data = [clean_df.columns.tolist()] + clean_df.values.tolist()
    
    ws.update(values=data, range_name='A1')
    
    log_action(user, "Update Data", f"Category: {category}")
    get_all_products_df.clear()
    
    return {"new": new_count, "eol": eol_count, "total": len(new_df)}
