import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime
import time
import json 

# --- CONNECT ---
@st.cache_resource
def get_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_sheet():
    client = get_client()
    # REPLACE WITH YOUR SHEET URL
    url = "https://docs.google.com/spreadsheets/d/1KG8qWTYLa6GEWByYIg2vz3bHrGdW3gvqD_detwhyj7k/edit"
    return client.open_by_url(url)

# --- READ ---
@st.cache_data(ttl=60)
def get_users():
    try:
        ws = get_sheet().worksheet("users")
        return pd.DataFrame(ws.get_all_records())
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def get_categories():
    try:
        ws = get_sheet().worksheet("categories")
        data = ws.get_all_values()
        if len(data) < 2: return []
        return pd.DataFrame(data[1:], columns=data[0])['category_name'].tolist()
    except: return []

@st.cache_data(ttl=60)
def get_all_products_df():
    sh = get_sheet()
    cats = get_categories()
    all_dfs = []
    for cat in cats:
        try:
            ws = sh.worksheet(cat)
            data = ws.get_all_values()
            if len(data) > 1:
                cat_df = pd.DataFrame(data[1:], columns=data[0])
                cat_df['category'] = cat 
                all_dfs.append(cat_df)
        except: continue
    if not all_dfs: return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True).dropna(axis=1, how='all')

@st.cache_data(ttl=5)
def get_quotes():
    """Robust fetch that handles column mismatches safely."""
    try:
        ws = get_sheet().worksheet("quotes")
        data = ws.get_all_values()
        if len(data) < 2: return pd.DataFrame()
        
        headers = data[0]
        rows = data[1:]
        
        # Safe creation
        df = pd.DataFrame(rows, columns=headers)
        return df
    except:
        return pd.DataFrame()

# --- WRITE ---
def register_user(u, p, e):
    try: ws = get_sheet().worksheet("users")
    except: 
        ws = get_sheet().add_worksheet("users", 100, 5)
        ws.append_row(["username", "password", "email", "status", "role"])
    ws.append_row([u, p, e, "pending", "user"])
    get_users.clear()

def log_action(user, action, details):
    try:
        ws = get_sheet().worksheet("logs")
        ws.append_row([str(datetime.now()), user, action, details])
    except: pass

def add_category(name, user):
    try: ws = get_sheet().worksheet("categories")
    except: 
        ws = get_sheet().add_worksheet("categories", 100, 3)
        ws.append_row(["category_name", "created_by", "created_at"])
    
    existing = [r['category_name'] for r in ws.get_all_records()]
    if name not in existing:
        ws.append_row([name, user, str(datetime.now())])
    
    try: get_sheet().worksheet(name)
    except: get_sheet().add_worksheet(name, 1000, 26)
    get_categories.clear()

def save_products_dynamic(df, category, user):
    add_category(category, user)
    ws = get_sheet().worksheet(category)
    clean_df = df.astype(str)
    ws.clear()
    ws.update([clean_df.columns.tolist()] + clean_df.values.tolist())
    log_action(user, "Upload", category)
    get_all_products_df.clear()

def update_products_dynamic(new_df, category, user, key_col):
    save_products_dynamic(new_df, category, user)
    return {"new": len(new_df), "eol": 0, "total": len(new_df)}

# --- QUOTE SAVE (FIXED) ---
def save_quote(quote_data, user):
    sh = get_sheet()
    try:
        ws = sh.worksheet("quotes")
    except:
        ws = sh.add_worksheet(title="quotes", rows=1000, cols=15)
        # DEFINE HEADERS (Column A to J)
        ws.append_row([
            "quote_id", 
            "created_at", 
            "created_by", 
            "client_name", 
            "client_email", 
            "client_phone",  # <--- Ensure this column exists
            "status", 
            "total_amount", 
            "items_json", 
            "expiration_date",
            "seller_info" # <--- NEW: Store custom seller info
        ])
    
    quote_id = f"Q-{int(time.time())}"
    
    # Pack Seller Info into a simple string or JSON
    seller_info = json.dumps(quote_data.get("seller_info", {}))

    # ROW DATA MUST MATCH HEADER ORDER
    row = [
        quote_id,
        str(datetime.now()),
        user,
        quote_data.get("client_name", ""),
        quote_data.get("client_email", ""),
        quote_data.get("client_phone", ""),
        "Draft",
        str(quote_data.get("total_amount", 0)),
        json.dumps(quote_data.get("items", [])),
        str(quote_data.get("expiration_date", "")),
        seller_info
    ]
    
    ws.append_row(row)
    log_action(user, "Created Quote", f"ID: {quote_id}")
    get_quotes.clear() 
    return quote_id

def delete_quote(qid, user):
    try:
        ws = get_sheet().worksheet("quotes")
        cell = ws.find(str(qid))
        ws.delete_rows(cell.row)
        get_quotes.clear()
        return True
    except: return False
