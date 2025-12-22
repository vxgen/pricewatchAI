import streamlit as st
import pandas as pd
import base64
import os
import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from openai import OpenAI

# Initialize Clients
# Add your keys to Streamlit Secrets or Environment Variables
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")

client = OpenAI(api_key=OPENAI_KEY)

def google_search_api(query):
    """Requirement #3: Conduct Google search for product links using official API."""
    url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    response = requests.get(url).json()
    items = response.get("items", [])
    # Return the first 3 relevant links
    return [item['link'] for item in items[:3]]

def analyze_with_vision(image_path, product_name):
    """Requirement #5: Vision-based price analysis."""
    with open(image_path, "rb") as f:
        base64_img = base64.b64encode(f.read()).decode('utf-8')
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": f"Extract the current price for {product_name}. Return ONLY the number (e.g. 49.99)."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
            ]
        }]
    )
    return response.choices[0].message.content

def run_browser_watch(url, product_name):
    """Requirement #5 & #6: Automated navigation and screenshot fallback."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        stealth_sync(page)
        
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Requirement #6: Fallback to internal search if landing page is generic
            # (Checks for common search input selectors)
            search_input = page.locator('input[type="search"], input[name="q"]').first
            if search_input.is_visible():
                search_input.fill(product_name)
                search_input.press("Enter")
                page.wait_for_load_state("networkidle")

            # Requirement #5: Screenshot analysis
            path = f"snap_{os.getpid()}.png"
            page.screenshot(path=path)
            price = analyze_with_vision(path, product_name)
            os.remove(path)
            return price
        except Exception as e:
            return f"Error: {str(e)}"
        finally:
            browser.close()

# --- STREAMLIT UI ---
st.set_page_config(page_title="Pro Price Watcher", layout="wide")
st.title("🛒 AI-Powered Price Comparison")



# Requirements #1 & #2
with st.sidebar:
    sku = st.text_input("Product Name / SKU")
    manual_url = st.text_input("Manual Link (Optional)")
    if st.button("Add Product"):
        if "items" not in st.session_state: st.session_state.items = []
        
        # Requirement #3: Align search if no manual link
        links = [manual_url] if manual_url else google_search_api(sku)
        for link in links:
            st.session_state.items.append({"sku": sku, "url": link})

# Requirement #4: Comparison Table
if "items" in st.session_state:
    if st.button("Update Price Comparison"):
        results = []
        for entry in st.session_state.items:
            price = run_browser_watch(entry['url'], entry['sku'])
            results.append({"SKU": entry['sku'], "Price": price, "URL": entry['url']})
        
        st.table(pd.DataFrame(results))
