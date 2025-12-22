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
    # Ensure all required keys exist for every item in the list
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
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY)

# --- 3. CORE LOGIC FUNCTIONS ---
def get_store_name(url):
    try: return urlparse(url).netloc.replace("www.", "")
    except: return "Store"

def google_search_deep(query, worldwide=False, blacklist=[]):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    cx = st.secrets.get("GOOGLE_CX")
    if not api_key or not cx: return []
    all_links = []
    base_url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={query}"
    if not worldwide: base_url += "&cr=countryAU"
    try:
        response = requests.get(base_url, timeout=10)
        items = response.json().get("items", [])
        for item in items:
            link = item['link']
            domain = get_store_name(link)
            if not any(b.strip().lower() in domain.lower() for b in blacklist if b.strip()):
                all_links.append(link)
    except: pass
    return list(dict.fromkeys(all_links))

def analyze_with_vision(image_path, product_name):
    try:
        with Image.open(image_path) as img:
            img.thumbnail((800, 800)) 
            temp_path = f"v_{os.getpid()}.jpg"
            img.save(temp_path, "JPEG", quality=60)
        with open(temp_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extract the current price for {product_name}. Return ONLY the numeric value. If not found, return 'N/A'."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        if os.path.exists(temp_path): os.remove(temp_path)
        return response.choices[0].message.content.strip()
    except: return "AI Error"

def run_browser_watch(url, product_name):
    if not SAPI_KEY: return "Missing Key", None, None
    proxy_url = f"http://api.scraperapi.com?api_key={SAPI_KEY}&url={quote_plus(url)}&render=true&country_code=au"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(proxy_url, timeout=95000, wait_until="networkidle")
            time.sleep(5) 
            page_path = f"page_{os.getpid()}.png"
            page.screenshot(path=page_path)
            price = analyze_with_vision(page_path, product_name)
            
            # Thumbnail Generation
            thumb_path = f"thumb_{os.getpid()}.png"
            with Image.open(page_path) as img:
                w, h = img.size
                thumb = img.crop((w/4, 100, 3*w/4, 500)) 
                thumb.thumbnail((200, 200))
                thumb.save(thumb_path)

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
        bulk_input = st.text_area("SKUs (comma separated)", placeholder="iPhone 16, RTX 5080")
        exclude_domains = st.text_input("Exclude Domains", placeholder="ebay.com, facebook.com")
        is_worldwide = st.checkbox("Worldwide Search")
        st.divider()
        m_sku = st.text_input("Manual Name")
        m_url = st.text_input("Manual URL")
        submit_button = st.form_submit_button("Add to List")

    if submit_button:
        watchlist = get_watchlist()
        blacklist = [b.strip() for b in exclude_domains.split(",") if b.strip()]
        if bulk_input:
            skus = [s.strip() for s in bulk_input.split(",") if s.strip()]
            for s in skus:
                with st.spinner(f"Searching for {s}..."):
                    links = google_search_deep(s, is_worldwide, blacklist)
                    for l in links:
                        if not any(item['url'] == l for item in watchlist):
                            watchlist.append({"sku": s, "url": l, "price": "Pending", "last_updated": "Never", "img_url": None, "page_url": None})
        if m_sku and m_url:
            if not any(item['url'] == m_url for item in watchlist):
                watchlist.append({"sku": m_sku, "url": m_url, "price": "Pending", "last_updated": "Never", "img_url": None, "page_url": None})
        st.session_state["items"] = watchlist
        st.rerun()

    if st.button("🗑️ Clear All Search Records"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. RESULTS TABLE & SCAN LOGIC ---
watchlist = get_watchlist()

if watchlist:
    df = pd.DataFrame(watchlist)
    df.insert(0, "Seq", range(1, len(df) + 1))
    df['Store'] = df['url'].apply(get_store_name)

    m1, m2 = st.columns(2)
    m1.metric("Total Items", len(df))
    selected_info = m2.empty()

    st.write("### Watchlist")
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

    # --- RESTORED ACTION BUTTONS ---
    btn1, btn2, btn3 = st.columns(3)
    
    with btn1:
        # THE RESTORED DEEP SCAN BUTTON
        if st.button("🚀 Run Deep Scan on Selected", use_container_width=True):
            if not selected_indices:
                st.warning("Please select items in the table first.")
            else:
                status = st.empty()
                progress_bar = st.progress(0)
                for i, idx in enumerate(selected_indices):
                    item = st.session_state["items"][idx]
                    status.info(f"Scanning Store {i+1}/{len(selected_indices)}: {get_store_name(item['url'])}")
                    
                    price_val, img_b64, page_b64 = run_browser_watch(item['url'], item['sku'])
                    
                    # Update state with Australia/Sydney Time
                    aedt_time = (datetime.utcnow() + timedelta(hours=11)).strftime("%H:%M")
                    st.session_state["items"][idx].update({
                        "price": price_val,
                        "img_url": img_b64,
                        "page_url": page_b64,
                        "last_updated": aedt_time
                    })
                    progress_bar.progress((i + 1) / len(selected_indices))
                
                status.success("✅ Scanning sequence complete!")
                st.rerun()

    with btn2:
        if selected_indices:
            csv_data = df.iloc[selected_indices].to_csv(index=False).encode('utf-8')
            st.download_button("📥 Export Selected to CSV", data=csv_data, file_name=f"price_report_{datetime.now().strftime('%Y%m%d')}.csv", use_container_width=True)
        else:
            st.button("📥 Export (Select Items)", disabled=True, use_container_width=True)

    with btn3:
        if st.button("❌ Remove Selected", use_container_width=True):
            if selected_indices:
                st.session_state["items"] = [item for j, item in enumerate(st.session_state["items"]) if j not in selected_indices]
                st.rerun()
            else:
                st.warning("Select items to remove.")
else:
    st.info("Watchlist is empty. Search for SKUs in the sidebar to begin.")
