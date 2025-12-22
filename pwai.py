import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import time
import random
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from PIL import Image
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
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
        except Exception as e:
            st.error(f"Browser installation failed: {e}")

# --- 2. API CLIENTS ---
# Make sure to add SCRAPERAPI_KEY to your Streamlit Secrets!
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")
SAPI_KEY = st.secrets.get("SCRAPERAPI_KEY") 

client = OpenAI(api_key=OPENAI_KEY)

# --- 3. CORE LOGIC ---
def get_store_name(url):
    try:
        domain = urlparse(url).netloc
        return domain.replace("www.", "")
    except:
        return "Store"

def google_search_deep(query, worldwide=False):
    if not GOOGLE_API_KEY or not GOOGLE_CX: return []
    all_links = []
    base_url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    if not worldwide: base_url += "&cr=countryAU"
    try:
        response = requests.get(base_url, timeout=10)
        items = response.json().get("items", [])
        all_links.extend([item['link'] for item in items if "facebook" not in item['link']])
    except: pass
    return list(dict.fromkeys(all_links))

def analyze_with_vision(image_path, product_name):
    try:
        with Image.open(image_path) as img:
            img.thumbnail((1000, 1000)) 
            compressed_path = "small_" + image_path
            img.save(compressed_path, "JPEG", quality=70)
        with open(compressed_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Locate current price for {product_name}. Return ONLY the numeric value. Return 'N/A' if blocked."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        if os.path.exists(compressed_path): os.remove(compressed_path)
        return response.choices[0].message.content.strip()
    except: return "AI Error"

def run_browser_watch(url, product_name):
    """
    NEW: ScraperAPI + Playwright Integration
    """
    if not SAPI_KEY:
        return "Missing API Key"

    # Encoding the URL so ScraperAPI can read it correctly
    safe_url = quote_plus(url)
    proxy_url = f"http://api.scraperapi.com?api_key={SAPI_KEY}&url={safe_url}&render=true&country_code=au"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        try:
            # ScraperAPI needs more time to render JS (90s)
            page.goto(proxy_url, timeout=90000, wait_until="networkidle")
            
            # Additional wait for dynamic prices to appear
            time.sleep(5) 
            
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path)
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except Exception as e:
            return "Proxy Timeout"
        finally:
            browser.close()

# --- 4. UI SETUP ---
st.set_page_config(page_title="AU Price Watcher Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher (Anti-Block Edition)")

with st.sidebar:
    st.header("Search & Add")
    bulk_input = st.text_area("Bulk SKUs (comma separated)", placeholder="AM272P, MSI G274")
    is_worldwide = st.checkbox("Search Worldwide?")
    
    st.divider()
    st.subheader("Manual URL")
    m_sku = st.text_input("Name")
    m_url = st.text_input("URL")
    
    if st.button("Add to List"):
        watchlist = get_watchlist()
        if bulk_input:
            skus = [s.strip() for s in bulk_input.split(",") if s.strip()]
            for s in skus:
                with st.spinner(f"Finding stores for {s}..."):
                    links = google_search_deep(s, is_worldwide)
                    for l in links:
                        if not any(item['url'] == l for item in watchlist):
                            watchlist.append({"sku": s, "url": l, "price": "Pending", "last_updated": "Never"})
        if m_sku and m_url:
            if not any(item['url'] == m_url for item in watchlist):
                watchlist.append({"sku": m_sku, "url": m_url, "price": "Pending", "last_updated": "Never"})
        st.session_state["items"] = watchlist
        st.rerun()

    if st.button("🗑️ Clear List"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. RESULTS ---
watchlist = get_watchlist()
if watchlist:
    df = pd.DataFrame(watchlist)
    df_display = df.copy()
    
    # Clickable Store Names
    df_display['Store'] = df_display['url'].apply(lambda x: f'<a href="{x}" target="_blank">{get_store_name(x)}</a>')
    
    st.write(df_display[["sku", "price", "last_updated", "Store"]].to_html(escape=False, index=False), unsafe_allow_html=True)
    
    if st.button("🚀 Start Deep Scanning"):
        if not SAPI_KEY:
            st.error("Please add 'SCRAPERAPI_KEY' to your Streamlit Secrets.")
        else:
            status = st.empty()
            bar = st.progress(0)
            for i, item in enumerate(watchlist):
                status.info(f"Using Proxy to scan {get_store_name(item['url'])}...")
                price = run_browser_watch(item['url'], item['sku'])
                st.session_state["items"][i]["price"] = price
                st.session_state["items"][i]["last_updated"] = datetime.now().strftime("%H:%M")
                bar.progress((i + 1) / len(watchlist))
                # Small delay to keep the UI smooth
                time.sleep(1)
            status.success("All scans finished!")
            st.rerun()
else:
    st.info("Enter SKUs in the sidebar to begin.")
