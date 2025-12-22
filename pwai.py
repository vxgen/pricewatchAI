import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import sys
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. ROBUST SESSION INITIALIZATION ---
def get_watchlist():
    if "items" not in st.session_state or st.session_state["items"] is None:
        st.session_state["items"] = []
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

# --- 4. CORE FUNCTIONS ---

def google_search_api(query, worldwide=False):
    """Requirement: Australian Priority with Worldwide fallback."""
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return []
    
    # 'countryAU' restricts results specifically to Australia
    base_url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    
    if not worldwide:
        base_url += "&cr=countryAU"
    
    try:
        response = requests.get(base_url, timeout=10)
        items = response.json().get("items", [])
        return [item['link'] for item in items[:3]]
    except:
        return []

def analyze_with_vision(image_path, product_name):
    try:
        with open(image_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Find the price for {product_name}. Return ONLY the number (e.g. 150.00). If not found, return 'N/A'."},
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
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        page = context.new_page()
        try:
            try:
                stealth(page)
            except:
                pass
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
st.set_page_config(page_title="AU Price Watcher", layout="wide")

if not st.session_state.get("browser_installed"):
    install_playwright_browsers()

st.title("🛒 AI Price Watcher (Australia Priority)")

# Sidebar Logic
with st.sidebar:
    st.header("Search Settings")
    sku_val = st.text_input("SKU / Keywords", key="sku_input")
    
    # Worldwide Toggle
    is_worldwide = st.checkbox("Search Worldwide?", help="If unchecked, only Australian sites are searched.")
    
    url_val = st.text_input("Store URL (Optional)", key="url_input")
    
    if st.button("Add to Watchlist"):
        if sku_val:
            items = get_watchlist()
            with st.spinner(f"Searching {'Worldwide' if is_worldwide else 'Australia'}..."):
                found_links = [url_val] if url_val else google_search_api(sku_val, worldwide=is_worldwide)
                
                if found_links:
                    for link in found_links:
                        # Adding 'N/A' as placeholder price for the table
                        items.append({"sku": sku_val, "url": link, "price": "Pending"})
                    st.session_state["items"] = items
                    st.rerun()
                else:
                    if not is_worldwide:
                        st.warning("No AU links found. Try checking 'Search Worldwide'.")
                    else:
                        st.error("No links found.")
        else:
            st.warning("Enter a SKU.")

    if st.button("🗑️ Clear List"):
        st.session_state["items"] = []
        st.rerun()

# --- 6. DISPLAY & ANALYSIS ---
watchlist = get_watchlist()

if len(watchlist) > 0:
    st.subheader("Your Watchlist")
    
    # Show current list with Price column as requested
    df_preview = pd.DataFrame(watchlist)
    # Reordering columns for better view
    df_preview = df_preview[["sku", "price", "url"]]
    st.table(df_preview)
    
    if st.button("🚀 Start Scanning Prices"):
        results = []
        progress = st.progress(0)
        
        for i, item in enumerate(watchlist):
            with st.status(f"Scanning {item.get('sku')}...") as status:
                price = run_browser_watch(item.get('url'), item.get('sku'))
                
                # Update the original watchlist in session state
                st.session_state["items"][i]["price"] = price
                
                results.append({
                    "Product": item.get('sku'),
                    "Price": price,
                    "Source": item.get('url')
                })
                progress.progress((i + 1) / len(watchlist))
                status.update(label=f"Finished {item.get('sku')}", state="complete")
        
        st.divider()
        st.subheader("Final Comparison Table")
        st.dataframe(pd.DataFrame(results), use_container_width=True)
        # Final rerun to update the 'Pending' prices in the top table
        st.rerun()
else:
    st.info("Sidebar: Add a product to begin. Searches prioritize Australian retailers by default.")
