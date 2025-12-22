import streamlit as st
import pandas as pd
import base64, os, requests, subprocess, time, random
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote_plus
from PIL import Image
from playwright.sync_api import sync_playwright
from openai import OpenAI

# --- 1. INITIALIZATION & SESSION STATE ---
def get_watchlist():
    if "items" not in st.session_state or st.session_state["items"] is None:
        st.session_state["items"] = []
    # Ensure consistency in data structure
    for item in st.session_state["items"]:
        item.setdefault("img_url", None)
        item.setdefault("page_url", None)
        item.setdefault("price", "Pending")
        item.setdefault("last_updated", "Never")
    return st.session_state["items"]

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

def install_playwright_browsers():
    if not st.session_state.get("browser_installed", False):
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception: pass

# --- 2. CORE LOGIC FUNCTIONS ---
def get_store_name(url):
    try: return urlparse(url).netloc.replace("www.", "")
    except: return "Store"

def google_search_deep(query, worldwide=False, blacklist=[]):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    cx = st.secrets.get("GOOGLE_CX")
    if not api_key or not cx: 
        st.error("Google API Search keys are missing in Secrets.")
        return []
    
    all_links = []
    base_url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={query}"
    if not worldwide: base_url += "&cr=countryAU"
    
    try:
        response = requests.get(base_url, timeout=10)
        items = response.json().get("items", [])
        for item in items:
            link = item['link']
            domain = get_store_name(link)
            # Filter out blacklisted domains
            if not any(b.strip().lower() in domain.lower() for b in blacklist if b.strip()):
                all_links.append(link)
    except Exception as e:
        st.error(f"Search error: {e}")
    return list(dict.fromkeys(all_links))

# (Note: analyze_with_vision and run_browser_watch remain the same as version 6.7)
# ... [Keeping those functions for brevity as they were working]

# --- 3. UI SETUP ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher")

with st.sidebar:
    st.header("Search Settings")
    with st.form("search_form"):
        bulk_input = st.text_area("SKUs (comma separated)", help="Type SKUs and hit Enter or click Add to List")
        exclude_domains = st.text_input("Exclude Domains", placeholder="ebay.com, facebook.com")
        is_worldwide = st.checkbox("Worldwide Search")
        st.divider()
        m_sku = st.text_input("Manual Name (Optional)")
        m_url = st.text_input("Manual URL (Optional)")
        submit_button = st.form_submit_button("Add to List")

    # --- THE RESTORED SUBMISSION LOGIC ---
    if submit_button:
        watchlist = get_watchlist()
        blacklist = [b.strip() for b in exclude_domains.split(",") if b.strip()]
        
        # Process Bulk Search
        if bulk_input:
            skus = [s.strip() for s in bulk_input.split(",") if s.strip()]
            for s in skus:
                with st.spinner(f"Searching for {s}..."):
                    links = google_search_deep(s, is_worldwide, blacklist)
                    for l in links:
                        # Prevent duplicates
                        if not any(item['url'] == l for item in watchlist):
                            watchlist.append({
                                "sku": s, "url": l, "price": "Pending", 
                                "last_updated": "Never", "img_url": None, "page_url": None
                            })
        
        # Process Manual Add
        if m_sku and m_url:
            if not any(item['url'] == m_url for item in watchlist):
                watchlist.append({
                    "sku": m_sku, "url": m_url, "price": "Pending", 
                    "last_updated": "Never", "img_url": None, "page_url": None
                })
        
        st.session_state["items"] = watchlist
        st.rerun()

    if st.button("🗑️ Clear All Records"):
        st.session_state["items"] = []
        st.rerun()

# --- 4. RESULTS TABLE ---
watchlist = get_watchlist()

if watchlist:
    df = pd.DataFrame(watchlist)
    df.insert(0, "Seq", range(1, len(df) + 1))
    df['Store'] = df['url'].apply(get_store_name)

    m1, m2 = st.columns(2)
    m1.metric("Total Items", len(df))
    selected_info = m2.empty()

    # The Selection Table
    selection_event = st.dataframe(
        df[["Seq", "img_url", "sku", "price", "last_updated", "Store", "page_url"]],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "Seq": st.column_config.NumberColumn("Seq", width="small"),
            "img_url": st.column_config.ImageColumn("Product", width="small"),
            "page_url": st.column_config.ImageColumn("Snapshot", width="small"),
        }
    )

    # Rest of the buttons (Run Scan, Export, Remove) remain the same...
    # ...
else:
    st.info("Add items to start. Enter SKUs in the sidebar and click 'Add to List'.")
