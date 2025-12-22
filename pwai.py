import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import time
import random
from datetime import datetime
from urllib.parse import urlparse
from PIL import Image
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. SESSION & BROWSER SETUP ---
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
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")
client = OpenAI(api_key=OPENAI_KEY)

# --- 3. CORE LOGIC ---
def get_store_name(url):
    try:
        domain = urlparse(url).netloc
        return domain.replace("www.", "")
    except:
        return "Store"

def google_search_deep(query, worldwide=False):
    if not GOOGLE_API_KEY or not GOOGLE_CX: 
        return []
    all_links = []
    base_url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    if not worldwide: 
        base_url += "&cr=countryAU"
    try:
        response = requests.get(base_url, timeout=10)
        items = response.json().get("items", [])
        all_links.extend([item['link'] for item in items if "facebook" not in item['link']])
    except: 
        pass
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
                    {"type": "text", "text": f"Extract the current price for {product_name}. Return ONLY the numeric price. If blocked or not found, return 'N/A'."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        if os.path.exists(compressed_path): 
            os.remove(compressed_path)
        return response.choices[0].message.content.strip()
    except Exception: 
        return "AI Error"

def run_browser_watch(url, product_name):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()
        try:
            stealth(page)
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto(url, wait_until="domcontentloaded", timeout=75000)
            
            # Behavior simulation
            time.sleep(random.uniform(5, 8))
            page.mouse.wheel(0, 400)
            time.sleep(2)
            
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path)
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): 
                os.remove(img_path)
            return price
        except: 
            return "Timeout/Block"
        finally: 
            browser.close()

# --- 4. SIDEBAR & UI ---
st.set_page_config(page_title="Price Watch Pro AU", layout="wide")
if not st.session_state.get("browser_installed"): 
    install_playwright_browsers()

st.title("🛒 AI Price Watcher (Ultra Stealth)")

with st.sidebar:
    st.header("Search & Add")
    bulk_input = st.text_area("Bulk SKUs (separate by comma)", placeholder="e.g. AM272P, MSI Monitor")
    is_worldwide = st.checkbox("Search Worldwide?")
    
    st.divider()
    st.subheader("Manual URL Entry")
    m_sku = st.text_input("Product Name")
    m_url = st.text_input("Direct URL")
    
    if st.button("Add to Watchlist"):
        watchlist = get_watchlist()
        if bulk_input:
            skus = [s.strip() for s in bulk_input.split(",") if s.strip()]
            for s in skus:
                with st.spinner(f"Searching for {s}..."):
                    links = google_search_deep(s, is_worldwide)
                    for l in links:
                        if not any(item['url'] == l for item in watchlist):
                            watchlist.append({"sku": s, "url": l, "price": "Pending", "last_updated": "Never"})
        
        if m_sku and m_url:
            if not any(item['url'] == m_url for item in watchlist):
                watchlist.append({"sku": m_sku, "url": m_url, "price": "Pending", "last_updated": "Never"})
        
        st.session_state["items"] = watchlist
        st.rerun()

    # --- THE FIXED BLOCK ---
    if st.button("🗑️ Clear List"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. RESULTS TABLE ---
watchlist = get_watchlist()
if watchlist:
    df = pd.DataFrame(watchlist)
    df_display = df.copy()
    
    # Store Link logic
    df_display['Store'] = df_display['url'].apply(lambda x: f'<a href="{x}" target="_blank">{get_store_name(x)}</a>')
    
    st.write(df_display[["sku", "price", "last_updated", "Store"]].to_html(escape=False, index=False), unsafe_allow_html=True)
    
    if st.button("🚀 Start Deep Scan"):
        status = st.empty()
        bar = st.progress(0)
        for i, item in enumerate(watchlist):
            status.info(f"Scanning {get_store_name(item['url'])} for {item['sku']}...")
            price = run_browser_watch(item['url'], item['sku'])
            st.session_state["items"][i]["price"] = price
            st.session_state["items"][i]["last_updated"] = datetime.now().strftime("%H:%M")
            bar.progress((i + 1) / len(watchlist))
            if i < len(watchlist) - 1:
                status.warning("API Cooldown 8s...")
                time.sleep(8)
        status.success("✅ All scans complete!")
        st.rerun()
else:
    st.info("Sidebar: Add SKUs to build your tracking list.")
