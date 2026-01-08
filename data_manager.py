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
    # Ensure you have your secrets set up in .streamlit/secrets.toml
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
        if not records: return []
        # Return list of category names
        return [r['category_name'] for r in records if 'category_name' in r and r['category_name']]
    except:
        return []

@st.cache_data(ttl=60)
def get_schema():
    # Placeholder to prevent app.py from crashing if it calls this
    # We don't enforce schema anymore, but the app might request it for display.
    return ["Product Name", "SKU", "Price", "Stock"] 

@st.cache_data(ttl=60)
def get_all_products_df():
    """
    INTELLIGENT FETCH:
    1. Gets list of all categories.
    2. Opens the specific worksheet for each category.
    3. Combines them into one master DataFrame for the Search Bar.
    """
    sh = get_sheet()
    cats = get_categories()
    
    all_dfs = []
    
    for cat in cats:
        try:
            # Try to open the worksheet for this category
            ws = sh.worksheet(cat)
            records = ws.get_all_records()
            
            if records:
                cat_df = pd.DataFrame(records)
                # Tag the data with its category so we know where it came from
                cat_df['category'] = cat 
                all_dfs.append(cat_df)
        except gspread.exceptions.WorksheetNotFound:
            continue # Skip if sheet doesn't exist yet
        except Exception as e:
            print(f"Error loading category {cat}: {e}")
            continue

    if not all_dfs:
        return pd.DataFrame()

    # Concatenate all frames. Pandas handles different columns automatically (filling NaNs)
    final_df = pd.concat(all_dfs, ignore_index=True)
    
    # Cleanup empty columns
    final_df = final_df.dropna(axis=1, how='all')
    
    return final_df

# --- WRITE FUNCTIONS ---

def register_user(username, password, email):
    try:
        ws = get_sheet().worksheet("users")
    except:
        # Create users sheet if missing
        sh = get_sheet()
        ws = sh.add_worksheet("users", 100, 5)
        ws.append_row(["username", "password", "email", "status", "role"])
        
    ws.append_row([username, password, email, "pending", "user"])
    get_users.clear()

def log_action(user, action, details):
    try:
        ws = get_sheet().worksheet("logs")
        ws.append_row([str(datetime.now()), user, action, details])
    except:
        pass 

def add_category(name, user):
    # 1. Add to 'categories' tracking sheet
    try:
        ws = get_sheet().worksheet("categories")
    except:
        sh = get_sheet()
        ws = sh.add_worksheet("categories", 100, 3)
        ws.append_row(["category_name", "created_by", "created_at"])
    
    # Check if exists to avoid duplicates
    existing = [r['category_name'] for r in ws.get_all_records()]
    if name not in existing:
        ws.append_row([name, user, str(datetime.now())])
        
    # 2. Create the actual Worksheet for this category immediately
    ensure_category_sheet_exists(name)
    
    get_categories.clear()

def ensure_category_sheet_exists(category_name):
    """Checks if a worksheet exists for the category, creates it if not."""
    sh = get_sheet()
    try:
        ws = sh.worksheet(category_name)
        return ws
    except gspread.exceptions.WorksheetNotFound:
        # Create new sheet
        # Google Sheets max title length is 100 chars, usually safe
        ws = sh.add_worksheet(title=category_name, rows=1000, cols=26)
        return ws

# --- DYNAMIC DATA HANDLERS ---

def add_schema_column(col_name):
    pass # Deprecated function kept to prevent import errors

def delete_schema_column(col_name):
    pass # Deprecated function kept to prevent import errors

def save_products_dynamic(df, category, user):
    """
    Saves raw data to a specific worksheet named after the Category.
    It APPENDS to the sheet.
    """
    # 1. Ensure category is tracked
    add_category(category, user)
    
    # 2. Get the specific worksheet
    ws = ensure_category_sheet_exists(category)
    
    # 3. Check if sheet is empty (has headers?)
    existing_data = ws.get_all_values()
    
    if not existing_data:
        # Sheet is new/empty: Write Headers + Data
        # Convert all to string to avoid JSON serialization errors
        clean_df = df.astype(str)
        data_to_write = [clean_df.columns.tolist()] + clean_df.values.tolist()
        ws.update(range_name='A1', values=data_to_write)
    else:
        # Sheet exists: Append Data
        # Note: We assume the new file matches the existing columns of this category.
        # If columns differ, Gspread might misalign. 
        # For a "Direct Upload" feature, appending is standard.
        clean_df = df.astype(str)
        ws.append_rows(clean_df.values.tolist())
    
    log_action(user, "Upload Direct", f"Category: {category}, Rows: {len(df)}")
    get_all_products_df.clear()

def update_products_dynamic(new_df, category, user, key_column):
    """
    Updates a specific category.
    Logic:
    1. Reads current data from the Category Worksheet.
    2. Compares based on key_column.
    3. Archives EOL items.
    4. REPLACES the Category Worksheet with the NEW data (Sync).
    """
    # 1. Ensure sheet exists
    ws = ensure_category_sheet_exists(category)
    
    # 2. Read existing data
    try:
        current_records = ws.get_all_records()
        current_df = pd.DataFrame(current_records)
    except:
        current_df = pd.DataFrame()

    # 3. Analyze Differences
    eol_count = 0
    new_count = 0
    
    if not current_df.empty and key_column in current_df.columns and key_column in new_df.columns:
        current_keys = set(current_df[key_column].astype(str))
        new_keys = set(new_df[key_column].astype(str))
        
        eol_keys = current_keys - new_keys
        to_add_keys = new_keys - current_keys
        
        eol_count = len(eol_keys)
        new_count = len(to_add_keys)
        
        # Archive EOLs
        if eol_keys:
            eol_rows = current_df[current_df[key_column].astype(str).isin(eol_keys)]
            # Add metadata
            eol_rows['eol_date'] = str(datetime.now())
            eol_rows['original_category'] = category
            
            # Save to EOL sheet
            try:
                sh = get_sheet()
                try:
                    ws_eol = sh.worksheet("eol_products")
                except:
                    ws_
