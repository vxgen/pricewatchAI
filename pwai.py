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
                    {"type": "text", "text": f"Extract the price for {product_name}. Return ONLY the numeric value."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        if os.path.exists(compressed_path): os.remove(compressed_path)
        return response.choices[0].message.content.strip()
    except: return "N/A"

def run_browser_watch(url, product_name):
    if not SAPI_KEY: return "Missing API Key"
    proxy_url = f"http://api.scraperapi.com?api_key={SAPI_KEY}&url={quote_plus(url)}&render=true&country_code=au"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(proxy_url, timeout=90000, wait_until="networkidle")
            time.sleep(5) 
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path)
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except: return "Timeout"
        finally: browser.close()

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
        # Search logic integration here
        st.rerun()

    if st.button("🗑️ Clear All"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. RESULTS TABLE ---
watchlist = get_watchlist()

if watchlist:
    df = pd.DataFrame(watchlist)
    # Renamed to "Seq" as requested
    df.insert(0, "Seq", range(1, len(df) + 1))
    df['Store'] = df['url'].apply(get_store_name)

    # UI Metrics
    col1, col2 = st.columns(2)
    col1.metric("Total Results", len(df))
    selected_placeholder = col2.empty() 

    st.write("### Watchlist")
    
    # Checkbox Selection with compact "Seq" column
    selection_event = st.dataframe(
        df[["Seq", "sku", "price", "last_updated", "Store"]],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "Seq": st.column_config.NumberColumn("Seq", width="small", format="%d"),
            "sku": "Product Name",
            "price": "Price",
            "last_updated": "Last Updated",
            "Store": "Store Domain"
        }
    )

    selected_rows = selection_event.selection.rows
    selected_placeholder.metric("Selected for Scan", len(selected_rows))

    if st.button("🚀 Run Deep Scan on Selected"):
        if selected_rows:
            status = st.empty()
            bar = st.progress(0)
            for i, idx in enumerate(selected_rows):
                item = st.session_state["items"][idx]
                status.info(f"Scanning {get_store_name(item['url'])}...")
                
                # Fetch Price
                new_price = run_browser_watch(item['url'], item['sku'])
                
                # Update State with AEDT Time (UTC + 11)
                aedt_now = datetime.utcnow() + timedelta(hours=11)
                st.session_state["items"][idx]["price"] = new_price
                st.session_state["items"][idx]["last_updated"] = aedt_now.strftime("%H:%M")
                
                bar.progress((i + 1) / len(selected_rows))
            status.success("✅ Done!")
            st.rerun()
else:
    st.info("Watchlist is empty.")
