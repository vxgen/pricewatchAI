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
    # Ensure new keys exist in old records
    for item in st.session_state["items"]:
        if "img_url" not in item: item["img_url"] = None
        if "page_url" not in item: item["page_url"] = None
    return st.session_state["items"]

# ... (Install playwright logic) ...

# --- 2. CORE LOGIC ---
def run_browser_watch(url, product_name):
    if not st.secrets.get("SCRAPERAPI_KEY"): return "Error", None, None
    
    proxy_url = f"http://api.scraperapi.com?api_key={st.secrets.get('SCRAPERAPI_KEY')}&url={quote_plus(url)}&render=true&country_code=au"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(proxy_url, timeout=90000, wait_until="networkidle")
            time.sleep(5) 
            
            # 1. Capture Full Page Snapshot
            page_path = f"page_{os.getpid()}.png"
            page.screenshot(path=page_path)
            
            # 2. Extract Price (using vision as before)
            price = analyze_with_vision(page_path, product_name)
            
            # 3. Create a Thumbnail / "Product Picture"
            # We crop the center-top of the page where product images usually are
            thumb_path = f"thumb_{os.getpid()}.png"
            with Image.open(page_path) as img:
                # Simple crop: Top-center area (400x400)
                w, h = img.size
                thumb = img.crop((w/4, 100, 3*w/4, 500)) 
                thumb.save(thumb_path)

            # Convert images to Base64 so Streamlit can show them in the table
            def to_b64(path):
                with open(path, "rb") as f:
                    return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
            
            img_b64 = to_b64(thumb_path)
            page_b64 = to_b64(page_path)

            # Cleanup
            if os.path.exists(page_path): os.remove(page_path)
            if os.path.exists(thumb_path): os.remove(thumb_path)
            
            return price, img_b64, page_b64
        except:
            return "Timeout", None, None
        finally:
            browser.close()

# --- 3. UI TABLE ---
watchlist = get_watchlist()

if watchlist:
    df = pd.DataFrame(watchlist)
    df.insert(0, "Seq", range(1, len(df) + 1))
    
    st.dataframe(
        df[["Seq", "img_url", "sku", "price", "last_updated", "page_url"]],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "Seq": st.column_config.NumberColumn("Seq", width="small"),
            "img_url": st.column_config.ImageColumn("Product", width="small"),
            "page_url": st.column_config.ImageColumn("Page Shot", width="medium"),
            "sku": "Product Name",
            "price": "Price",
        }
    )

    if st.button("🚀 Run Deep Scan on Selected"):
        selected_rows = st.session_state.get("df_selection", {}).get("rows", [])
        for idx in selected_rows:
            p, img, pg = run_browser_watch(watchlist[idx]['url'], watchlist[idx]['sku'])
            st.session_state["items"][idx].update({
                "price": p, "img_url": img, "page_url": pg, 
                "last_updated": (datetime.utcnow() + timedelta(hours=11)).strftime("%H:%M")
            })
        st.rerun()
