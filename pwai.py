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
    try:
        return urlparse(url).netloc.replace("www.", "")
    except: return "Store"

def google_search_deep(query, worldwide=False, blacklist=[]):
    if not st.secrets.get("GOOGLE_API_KEY"): return []
    all_links = []
    base_url = f"https://www.googleapis.com/customsearch/v1?key={st.secrets.get('GOOGLE_API_KEY')}&cx={st.secrets.get('GOOGLE_CX')}&q={query}"
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
    except: pass
    return list(dict.fromkeys(all_links))

def run_browser_watch(url, product_name):
    if not SAPI_KEY: return "Missing SAPI Key"
    proxy_url = f"http://api.scraperapi.com?api_key={SAPI_KEY}&url={quote_plus(url)}&render=true&country_code=au"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(proxy_url, timeout=90000, wait_until="networkidle")
            time.sleep(5) 
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path)
            # Vision AI call (assume analyze_with_vision exists as per previous versions)
            # price = analyze_with_vision(img_path, product_name) 
            price = "AI logic here" # Placeholder for brevity
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except: return "Timeout"
        finally: browser.close()

# --- 4. UI SETUP ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher")

# --- SIDEBAR WITH FORM (Enter-to-Submit) ---
with st.sidebar:
    st.header("Search Settings")
    
    with st.form("search_form", clear_on_submit=False):
        bulk_input = st.text_area("SKUs (comma separated)", placeholder="e.g. iPhone 16, RTX 5080")
        exclude_domains = st.text_input("Exclude Domains (comma separated)", placeholder="ebay.com, facebook.com")
        is_worldwide = st.checkbox("Worldwide Search")
        
        st.divider()
        st.subheader("Manual Direct URL")
        m_sku = st.text_input("Product Name")
        m_url = st.text_input("URL")
        
        submit_button = st.form_submit_button("Add to List")

    if submit_button:
        watchlist = get_watchlist()
        blacklist = exclude_domains.split(",") if exclude_domains else []
        
        if bulk_input:
            skus = [s.strip() for s in bulk_input.split(",") if s.strip()]
            for s in skus:
                with st.spinner(f"Searching {s}..."):
                    links = google_search_deep(s, is_worldwide, blacklist)
                    for l in links:
                        if not any(item['url'] == l for item in watchlist):
                            watchlist.append({"sku": s, "url": l, "price": "Pending", "last_updated": "Never"})
        
        if m_sku and m_url:
            watchlist.append({"sku": m_sku, "url": m_url, "price": "Pending", "last_updated": "Never"})
        
        st.session_state["items"] = watchlist
        st.rerun()

    if st.button("🗑️ Clear All"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. MAIN PAGE & COUNTERS ---
watchlist = get_watchlist()
total_items = len(watchlist)

# Display result counts
col1, col2 = st.columns(2)
col1.metric("Total Items Tracked", total_items)
col2.metric("Unique Stores", len(set(get_store_name(i['url']) for i in watchlist)) if watchlist else 0)

if watchlist:
    df = pd.DataFrame(watchlist)
    # Render table with clickable links
    df_display = df.copy()
    df_display['Store'] = df_display['url'].apply(lambda x: f'<a href="{x}" target="_blank">{get_store_name(x)}</a>')
    st.write(df_display[["sku", "price", "last_updated", "Store"]].to_html(escape=False, index=False), unsafe_allow_html=True)
    
    if st.button("🚀 Run Deep Scan"):
        # ... (Execution loop as per previous version)
        st.success("Scans complete!")
else:
    st.info("Your watchlist is empty. Add SKUs in the sidebar.")
