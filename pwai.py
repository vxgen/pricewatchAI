import streamlit as st
import pandas as pd
import base64, os, requests, subprocess, time, random
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from PIL import Image
from playwright.sync_api import sync_playwright
from openai import OpenAI

# --- 1. INITIALIZATION ---
def get_watchlist():
    if "items" not in st.session_state:
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

# (Include your google_search_deep and analyze_with_vision functions here)
# ...

# --- 4. UI SETUP ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher")

with st.sidebar:
    st.header("Search Settings")
    with st.form("search_form"):
        bulk_input = st.text_area("SKUs (comma separated)", placeholder="e.g. iPhone 16")
        exclude_domains = st.text_input("Exclude Domains", placeholder="ebay.com")
        is_worldwide = st.checkbox("Worldwide Search")
        submit_button = st.form_submit_button("Add to List")

    if submit_button:
        # (Your existing add-to-watchlist logic)
        st.rerun()

    if st.button("🗑️ Clear All"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. RESULTS TABLE WITH SELECTION ---
watchlist = get_watchlist()

if watchlist:
    # Prepare Data
    df = pd.DataFrame(watchlist)
    
    # 1. Add Sequence Number (#)
    df.insert(0, "#", range(1, len(df) + 1))
    
    # 2. Add Display columns
    df['Store'] = df['url'].apply(lambda x: get_store_name(x))

    # Display Metrics
    col1, col2 = st.columns(2)
    col1.metric("Total Results", len(df))
    col2.metric("Selected for Scan", 0) # Updated dynamically below

    st.write("### Watchlist")
    st.info("💡 Use the checkboxes on the left to select specific stores for scanning.")

    # 3. Use st.dataframe with selection enabled (Streamlit 1.35+)
    selection_event = st.dataframe(
        df[["#", "sku", "price", "last_updated", "Store"]],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row"
    )

    # Get selected indices
    selected_rows = selection_event.selection.rows
    col2.metric("Selected for Scan", len(selected_rows))

    # 4. Deep Scan Logic for Selected Only
    if st.button("🚀 Run Deep Scan on Selected"):
        if not selected_rows:
            st.warning("Please select at least one row using the checkboxes.")
        elif not SAPI_KEY:
            st.error("Missing ScraperAPI Key in Secrets.")
        else:
            status = st.empty()
            bar = st.progress(0)
            
            # Map selected indices back to original watchlist
            for i, idx in enumerate(selected_rows):
                item = watchlist[idx]
                status.info(f"Scanning {get_store_name(item['url'])} for {item['sku']}...")
                
                # Perform scan
                # price = run_browser_watch(item['url'], item['sku'])
                price = "$999" # Placeholder
                
                # Update main session state
                st.session_state["items"][idx]["price"] = price
                st.session_state["items"][idx]["last_updated"] = datetime.now().strftime("%H:%M")
                
                bar.progress((i + 1) / len(selected_rows))
                time.sleep(1)
            
            status.success("✅ Selected scans complete!")
            st.rerun()

else:
    st.info("Your watchlist is empty. Add items using the sidebar.")
