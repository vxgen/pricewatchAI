import streamlit as st
import pandas as pd
import base64, os, requests, subprocess, time, random
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote_plus
from PIL import Image
from playwright.sync_api import sync_playwright
from openai import OpenAI

# --- 1. INITIALIZATION ---
def get_watchlist():
    if "items" not in st.session_state or st.session_state["items"] is None:
        st.session_state["items"] = []
    return st.session_state["items"]

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

def install_playwright_browsers():
    if not st.session_state.get("browser_installed", False):
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception: pass

# --- 2. API CLIENTS ---
SAPI_KEY = st.secrets.get("SCRAPERAPI_KEY") 
client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY"))

# --- 3. HELPER LOGIC ---
def get_store_name(url):
    try: return urlparse(url).netloc.replace("www.", "")
    except: return "Store"

# ... (Include analyze_with_vision and run_browser_watch from previous steps) ...

# --- 4. UI SETUP ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher")

with st.sidebar:
    st.header("Search Settings")
    with st.form("search_form"):
        bulk_input = st.text_area("SKUs (comma separated)")
        exclude_domains = st.text_input("Exclude Domains")
        is_worldwide = st.checkbox("Worldwide Search")
        submit_button = st.form_submit_button("Add to List")

    if submit_button:
        # Search and filter logic goes here...
        st.rerun()

    st.divider()
    # NEW: Dedicated Clear All function in Sidebar
    if st.button("🗑️ Clear All Search Records", use_container_width=True):
        st.session_state["items"] = []
        st.success("All records cleared!")
        st.rerun()

# --- 5. RESULTS TABLE ---
watchlist = get_watchlist()

if watchlist:
    df = pd.DataFrame(watchlist)
    df.insert(0, "Seq", range(1, len(df) + 1))
    df['Store'] = df['url'].apply(get_store_name)

    # UI Metrics
    col1, col2 = st.columns(2)
    col1.metric("Total Tracked", len(df))
    selected_placeholder = col2.empty() 

    st.write("### Watchlist")
    
    # Table with Selection
    selection_event = st.dataframe(
        df[["Seq", "sku", "price", "last_updated", "Store"]],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "Seq": st.column_config.NumberColumn("Seq", width="small", format="%d"),
        }
    )

    selected_rows = selection_event.selection.rows
    selected_placeholder.metric("Selected Rows", len(selected_rows))

    # --- ACTION BUTTONS ROW ---
    btn_col1, btn_col2, btn_col3 = st.columns([1.5, 1.5, 1.5])

    with btn_col1:
        if st.button("🚀 Run Scan on Selected", use_container_width=True):
            if selected_rows:
                # ... (Existing Scan Loop with AEDT Time) ...
                st.rerun()

    with btn_col2:
        if selected_rows:
            # Export CSV logic
            export_df = df.iloc[selected_rows][["Seq", "sku", "price", "last_updated", "Store", "url"]]
            csv = export_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Export CSV", data=csv, file_name="prices.csv", mime='text/csv', use_container_width=True)
        else:
            st.button("📥 Export (Select Items)", disabled=True, use_container_width=True)

    with btn_col3:
        # NEW: Remove Selected function
        if st.button("❌ Remove Selected", use_container_width=True):
            if selected_rows:
                # Remove rows by filtering out the selected indices
                st.session_state["items"] = [i for j, i in enumerate(st.session_state["items"]) if j not in selected_rows]
                st.rerun()
            else:
                st.warning("Select items to remove.")

else:
    st.info("Watchlist is empty. Search for SKUs in the sidebar.")
