import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import time
import random
from datetime import datetime
from PIL import Image
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. SESSION & BROWSER ---
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
def google_search_deep(query, worldwide=False, num_pages=1):
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return []
    all_links = []
    for i in range(num_pages):
        start_index = (i * 10) + 1
        base_url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}&start={start_index}"
        if not worldwide: base_url += "&cr=countryAU"
        try:
            response = requests.get(base_url, timeout=10)
            items = response.json().get("items", [])
            all_links.extend([item['link'] for item in items if "facebook" not in item['link']])
        except: break
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
                "content": [{"type": "text", "text": f"Extract the current price for {product_name}. Return ONLY the numeric price. If blocked/no price, return 'N/A'."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}]
            }],
            max_tokens=50
        )
        if os.path.exists(compressed_path): os.remove(compressed_path)
        return response.choices[0].message.content.strip()
    except Exception: return "AI Error"

def run_browser_watch(url, product_name):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Emulate a very specific Mac/Chrome user to bypass basic bot blocks
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1440, 'height': 900}
        )
        page = context.new_page()
        try:
            stealth(page)
            # Bypass navigator.webdriver detection
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(random.uniform(3, 6)) # Wait for prices to render
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path, full_page=False)
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except Exception: return "Timeout/Block"
        finally: browser.close()

# --- 4. UI LAYOUT ---
st.set_page_config(page_title="Price Watch AI", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher (Multi-SKU Mode)")

with st.sidebar:
    st.header("Search Parameters")
    # MULTI-SKU SUPPORT: Now accepts comma separated values
    sku_input = st.text_area("Product Names / SKUs (separate by comma)", help="Example: AM272P, MSI Monitor, iPhone 15")
    is_worldwide = st.checkbox("Search Worldwide?", value=False)
    
    st.divider()
    st.header("Manual Link Entry")
    manual_sku = st.text_input("Manual SKU Name")
    manual_url = st.text_input("Manual URL")
    
    if st.button("Add to List"):
        watchlist = get_watchlist()
        # 1. Handle Bulk SKUs
        if sku_input:
            skus = [s.strip() for s in sku_input.split(",") if s.strip()]
            for s in skus:
                with st.spinner(f"Finding stores for {s}..."):
                    links = google_search_deep(s, is_worldwide, num_pages=1)
                    for l in links:
                        if not any(item['url'] == l for item in watchlist):
                            watchlist.append({"sku": s, "url": l, "price": "Pending", "last_updated": "Never"})
        
        # 2. Handle Manual Entry
        if manual_sku and manual_url:
            if not any(item['url'] == manual_url for item in watchlist):
                watchlist.append({"sku": manual_sku, "url": manual_url, "price": "Pending", "last_updated": "Never"})
        
        st.session_state["items"] = watchlist
        st.rerun()

    if st.button("🗑️ Clear All"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. RESULTS ---
watchlist = get_watchlist()
if watchlist:
    st.subheader(f"Watchlist ({len(watchlist)} items)")
    df = pd.DataFrame(watchlist)
    
    # CLICKABLE LINKS: Transform the URL column into HTML links
    def make_clickable(link):
        return f'<a href="{link}" target="_blank">Open Store</a>'
    
    df_display = df.copy()
    df_display['url'] = df_display['url'].apply(make_clickable)
    
    # Display table with HTML rendering enabled
    st.write(df_display[["sku", "price", "last_updated", "url"]].to_html(escape=False, index=False), unsafe_allow_html=True)
    
    if st.button("🚀 Start Scanning Prices"):
        status_box = st.empty()
        bar = st.progress(0)
        for i, item in enumerate(watchlist):
            status_box.info(f"Scanning {i+1}/{len(watchlist)}: {item['sku']}...")
            found_price = run_browser_watch(item['url'], item['sku'])
            st.session_state["items"][i]["price"] = found_price
            st.session_state["items"][i]["last_updated"] = datetime.now().strftime("%H:%M")
            bar.progress((i + 1) / len(watchlist))
            if i < len(watchlist) - 1:
                status_box.warning("Cooldown 8s...")
                time.sleep(8)
        status_box.success("✅ Scan Complete!")
        st.rerun()
else:
    st.info("Enter multiple SKUs or a manual URL in the sidebar.")
