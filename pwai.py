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
    if "items" not in st.session_state:
        st.session_state["items"] = []
    return st.session_state["items"]

if "next_start" not in st.session_state:
    st.session_state["next_start"] = 1

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

def install_playwright_browsers():
    if not st.session_state.get("browser_installed", False):
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception: pass

# --- 2. SEARCH ENGINE ---
def google_search_paginated(query, start_index=1, worldwide=False, blacklist=[]):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    cx = st.secrets.get("GOOGLE_CX")
    if not api_key or not cx: return []
    all_links = []
    base_url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={query}&start={start_index}"
    if not worldwide: base_url += "&cr=countryAU"
    try:
        response = requests.get(base_url, timeout=10)
        items = response.json().get("items", [])
        for item in items:
            link = item['link']
            domain = urlparse(link).netloc.replace("www.", "")
            if not any(b.strip().lower() in domain.lower() for b in blacklist if b.strip()):
                all_links.append(link)
    except: pass
    return all_links

# --- 3. UI SETUP ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher")

with st.sidebar:
    st.header("Search Settings")
    with st.form("search_form"):
        bulk_input = st.text_input("Product Search", placeholder="e.g. iPhone 17 Pro Max")
        exclude_domains = st.text_input("Exclude Domains")
        is_worldwide = st.checkbox("Worldwide Search")
        
        st.divider()
        st.subheader("Manual Target URL")
        m_sku = st.text_input("Product Name (Manual)")
        m_url = st.text_input("Target URL (Manual)")
        
        submit_button = st.form_submit_button("Search & Add to List")

    if submit_button:
        watchlist = get_watchlist()
        
        # 1. Process Manual URL if provided
        if m_sku and m_url:
            if not any(item['url'] == m_url for item in watchlist):
                watchlist.append({
                    "sku": m_sku, "url": m_url, "price": "Pending", "last_updated": "Never", "img_url": None
                })
        
        # 2. Process Bulk Search if provided
        if bulk_input:
            st.session_state["last_query"] = bulk_input
            blacklist = [b.strip() for b in exclude_domains.split(",") if b.strip()]
            for page_start in [1, 11]:
                links = google_search_paginated(bulk_input, start_index=page_start, worldwide=is_worldwide, blacklist=blacklist)
                for l in links:
                    if not any(item['url'] == l for item in watchlist):
                        watchlist.append({
                            "sku": bulk_input, "url": l, "price": "Pending", "last_updated": "Never", "img_url": None
                        })
            st.session_state["next_start"] = 21
        
        st.session_state["items"] = watchlist
        st.rerun()

    # --- LOAD MORE BUTTON ---
    if "last_query" in st.session_state and len(st.session_state.get("items", [])) > 0:
        st.write("---")
        if st.button("🔍 Load 20 More Stores", use_container_width=True):
            query = st.session_state["last_query"]
            current_start = st.session_state["next_start"]
            with st.spinner("Fetching more stores..."):
                for page_start in [current_start, current_start + 10]:
                    links = google_search_paginated(query, start_index=page_start, worldwide=is_worldwide)
                    for l in links:
                        if not any(item['url'] == l for item in st.session_state["items"]):
                            st.session_state["items"].append({
                                "sku": query, "url": l, "price": "Pending", "last_updated": "Never", "img_url": None
                            })
            st.session_state["next_start"] += 20
            st.rerun()

    if st.button("🗑️ Clear All Records", use_container_width=True):
        st.session_state["items"] = []
        st.session_state.pop("last_query", None)
        st.rerun()

# --- 4. COMPACT RESULTS TABLE ---
watchlist = get_watchlist()
if watchlist:
    df = pd.DataFrame(watchlist)
    df.insert(0, "Seq", range(1, len(df) + 1))

    st.metric("Total Stores Tracked", len(df))
    
    selection_event = st.dataframe(
        df[["Seq", "img_url", "sku", "price", "last_updated", "url"]],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "Seq": st.column_config.NumberColumn("Seq", width=30), # Minimum width
            "img_url": st.column_config.ImageColumn("Product", width="small"),
            "sku": "Product",
            "url": st.column_config.LinkColumn("Store Link")
        }
    )
    
    # ... (Include the btn1/btn2/btn3 scan/export/remove logic from v8.0)
