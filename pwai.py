import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
from datetime import datetime
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. ROBUST SESSION INITIALIZATION ---
def get_watchlist():
    if "items" not in st.session_state or st.session_state["items"] is None:
        st.session_state["items"] = []
    
    for item in st.session_state["items"]:
        if "price" not in item: item["price"] = "Pending"
        if "last_updated" not in item: item["last_updated"] = "Never"
    return st.session_state["items"]

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

# --- 2. CLOUD INSTALLER ---
def install_playwright_browsers():
    if not st.session_state.get("browser_installed", False):
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception as e:
            st.error(f"Browser installation failed: {e}")

# --- 3. API CLIENTS ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")
client = OpenAI(api_key=OPENAI_KEY)

# --- 4. IMPROVED SEARCH (PAGINATION) ---
def google_search_deep(query, worldwide=False, num_pages=3):
    """Fetches up to 30 results by paginating through Google API."""
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return []
    
    all_links = []
    for i in range(num_pages):
        start_index = (i * 10) + 1
        base_url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}&start={start_index}"
        
        if not worldwide:
            base_url += "&cr=countryAU" # Focus on Australia
        
        try:
            response = requests.get(base_url, timeout=10)
            items = response.json().get("items", [])
            for item in items:
                link = item['link']
                # Basic filter to avoid social media or non-store links
                if not any(x in link for x in ["facebook", "twitter", "youtube", "linkedin", "pinterest"]):
                    all_links.append(link)
        except Exception as e:
            st.warning(f"Error on page {i+1}: {e}")
            break
            
    # Deduplicate while keeping order
    return list(dict.fromkeys(all_links))

def analyze_with_vision(image_path, product_name):
    try:
        with open(image_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Find the price for {product_name}. Return ONLY the numeric value (e.g. 129.50). Use 'N/A' if not visible."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

def run_browser_watch(url, product_name):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0")
        page = context.new_page()
        try:
            try: stealth(page)
            except: pass
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path)
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except:
            return "Scan Failed"
        finally:
            browser.close()

# --- 5. UI LAYOUT ---
st.set_page_config(page_title="Deep Price Watcher", layout="wide")
if not st.session_state.get("browser_installed"):
    install_playwright_browsers()

st.title("🛒 Deep Scan Price Watcher")

with st.sidebar:
    st.header("Search Settings")
    sku_val = st.text_input("Product Name / SKU", key="sku_input")
    is_worldwide = st.checkbox("Search Worldwide?", value=False)
    depth = st.slider("Search Depth (Number of Google pages)", 1, 5, 2)
    
    if st.button("Add All Resellers to List"):
        if sku_val:
            items = get_watchlist()
            with st.spinner(f"Scouring the web for {sku_val}..."):
                found_links = google_search_deep(sku_val, worldwide=is_worldwide, num_pages=depth)
                
                if found_links:
                    for link in found_links:
                        # Avoid adding the same URL twice to your current list
                        if not any(item['url'] == link for item in items):
                            items.append({
                                "sku": sku_val, 
                                "url": link, 
                                "price": "Pending", 
                                "last_updated": "Never"
                            })
                    st.session_state["items"] = items
                    st.success(f"Added {len(found_links)} potential resellers!")
                    st.rerun()
                else:
                    st.error("No resellers found. Try increasing search depth or checking Worldwide.")
        else:
            st.warning("Enter a SKU.")

    if st.button("🗑️ Clear List"):
        st.session_state["items"] = []
        st.rerun()

# --- 6. DISPLAY & ANALYSIS ---
watchlist = get_watchlist()

if len(watchlist) > 0:
    st.subheader(f"Current Watchlist ({len(watchlist)} stores)")
    df_preview = pd.DataFrame(watchlist)
    
    # Secure column display
    cols = [c for c in ["sku", "price", "last_updated", "url"] if c in df_preview.columns]
    st.dataframe(df_preview[cols], use_container_width=True)
    
    if st.button("🚀 Start Deep Scan Comparison"):
        progress = st.progress(0)
        timestamp = datetime.now().strftime("%m-%d %H:%M")
        
        for i, item in enumerate(watchlist):
            with st.status(f"Scanning store {i+1}/{len(watchlist)}: {item.get('url')[:40]}...") as status:
                price = run_browser_watch(item.get('url'), item.get('sku'))
                st.session_state["items"][i]["price"] = price
                st.session_state["items"][i]["last_updated"] = timestamp
                progress.progress((i + 1) / len(watchlist))
                status.update(label=f"Price Found: {price}", state="complete")
        
        st.success(f"Full report ready!")
        st.rerun()
else:
    st.info("Add a product to begin deep scanning for resellers.")
