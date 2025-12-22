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
    # Ensure all required keys exist for every item
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

# --- 2. API CLIENTS ---
SAPI_KEY = st.secrets.get("SCRAPERAPI_KEY") 
client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY"))

# --- 3. CORE LOGIC ---
def get_store_name(url):
    try: return urlparse(url).netloc.replace("www.", "")
    except: return "Store"

def analyze_with_vision(image_path, product_name):
    try:
        with Image.open(image_path) as img:
            img.thumbnail((800, 800)) 
            temp_path = "v_temp.jpg"
            img.save(temp_path, "JPEG", quality=60)
        with open(temp_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extract price for {product_name}. Return ONLY numeric value."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except: return "AI Error"

def run_browser_watch(url, product_name):
    if not SAPI_KEY: return "Missing Key", None, None
    proxy_url = f"http://api.scraperapi.com?api_key={SAPI_KEY}&url={quote_plus(url)}&render=true&country_code=au"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(proxy_url, timeout=90000, wait_until="networkidle")
            time.sleep(5) 
            
            page_path = f"page_{random.randint(1000,9999)}.png"
            page.screenshot(path=page_path)
            
            price = analyze_with_vision(page_path, product_name)
            
            # Create Thumbnail
            thumb_path = f"thumb_{random.randint(1000,9999)}.png"
            with Image.open(page_path) as img:
                w, h = img.size
                thumb = img.crop((w/4, 100, 3*w/4, 500)) 
                thumb.thumbnail((200, 200))
                thumb.save(thumb_path)

            def to_b64(path):
                with open(path, "rb") as f:
                    return f"data:image/png;base64,{base64_img}" # Simplified for stability
            
            # Using the actual base64 helper
            with open(thumb_path, "rb") as f:
                img_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
            with open(page_path, "rb") as f:
                page_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"

            if os.path.exists(page_path): os.remove(page_path)
            if os.path.exists(thumb_path): os.remove(thumb_path)
            
            return price, img_b64, page_b64
        except: return "Timeout", None, None
        finally: browser.close()

# --- 4. UI SETUP ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher")

with st.sidebar:
    st.header("Search Settings")
    with st.form("search_form"):
        bulk_input = st.text_area("SKUs (comma separated)")
        m_sku = st.text_input("Manual Name")
        m_url = st.text_input("Manual URL")
        submit_button = st.form_submit_button("Add to List")

    if submit_button:
        watchlist = get_watchlist()
        if m_sku and m_url:
            watchlist.append({"sku": m_sku, "url": m_url, "price": "Pending", "last_updated": "Never", "img_url": None, "page_url": None})
        st.session_state["items"] = watchlist
        st.rerun()

    if st.button("🗑️ Clear All Records"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. RESULTS ---
watchlist = get_watchlist()

if watchlist:
    df = pd.DataFrame(watchlist)
    df.insert(0, "Seq", range(1, len(df) + 1))
    df['Store'] = df['url'].apply(get_store_name)

    col1, col2 = st.columns(2)
    col1.metric("Total Items", len(df))
    selected_info = col2.empty()

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

    selected_indices = selection_event.selection.rows
    selected_info.metric("Selected for Scan", len(selected_indices))

    btn1, btn2, btn3 = st.columns(3)
    
    with btn1:
        if st.button("🚀 Run Scan", use_container_width=True):
            if selected_indices:
                status = st.empty()
                for idx in selected_indices:
                    item = st.session_state["items"][idx]
                    status.info(f"Scanning {item['sku']}...")
                    p, img, pg = run_browser_watch(item['url'], item['sku'])
                    st.session_state["items"][idx].update({
                        "price": p, "img_url": img, "page_url": pg, 
                        "last_updated": (datetime.utcnow() + timedelta(hours=11)).strftime("%H:%M")
                    })
                status.success("Finished!")
                st.rerun()
            else: st.warning("Select items first")

    with btn2:
        if selected_indices:
            csv = df.iloc[selected_indices].to_csv(index=False).encode('utf-8')
            st.download_button("📥 Export CSV", data=csv, file_name="prices.csv", use_container_width=True)

    with btn3:
        if st.button("❌ Remove Selected", use_container_width=True):
            st.session_state["items"] = [i for j, i in enumerate(st.session_state["items"]) if j not in selected_indices]
            st.rerun()
else:
    st.info("Add items to start.")
