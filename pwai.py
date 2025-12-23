import streamlit as st
import pandas as pd
import gspread
import hashlib
import os, base64, requests, subprocess, time, random
from google.oauth2 import service_account
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote_plus
from PIL import Image
from playwright.sync_api import sync_playwright
from openai import OpenAI

# --- 1. USER AUTHENTICATION & GOOGLE SHEETS ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def load_user_db():
    try:
        client = get_gspread_client()
        sheet = client.open("PriceWatchAI").worksheet("users")
        
        all_values = sheet.get_all_values()
        expected = ['username', 'password', 'is_active']
        
        # Self-Healing: If sheet is empty or headers are wrong, fix it
        if not all_values or all_values[0] != expected:
            sheet.clear()
            sheet.insert_row(expected, 1)
            return sheet, pd.DataFrame(columns=expected)

        if len(all_values) == 1:
            return sheet, pd.DataFrame(columns=expected)
            
        data = sheet.get_all_records()
        return sheet, pd.DataFrame(data)
    except Exception as e:
        st.error(f"⚠️ Link Error: {e}")
        return None, pd.DataFrame()

def check_login(u, p):
    sheet, df = load_user_db()
    if df.empty: return False, "No users found in database."
    user_row = df[df['username'] == u]
    if not user_row.empty:
        if user_row.iloc[0]['password'] == hash_password(p):
            if str(user_row.iloc[0]['is_active']).strip().upper() == "TRUE":
                return True, "Success"
            return False, "Your account is pending manual approval."
    return False, "Invalid username or password."

def register_user(u, p):
    res = load_user_db()
    if res[0] is None: return False, "Database connection failed."
    sheet, df = res
    if not df.empty and u in df['username'].astype(str).values:
        return False, "Username already exists."
    try:
        sheet.append_row([u, hash_password(p), "FALSE"])
        return True, "Registration sent! Admin must approve in Google Sheets."
    except Exception as e:
        return False, f"Error writing to sheet: {e}"

# --- 2. CORE APP INITIALIZATION ---
def get_watchlist():
    if "items" not in st.session_state:
        st.session_state["items"] = []
    return st.session_state["items"]

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

def install_browsers():
    if not st.session_state["browser_installed"]:
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except: pass

# --- 3. API & SEARCH LOGIC ---
SAPI_KEY = st.secrets.get("SCRAPERAPI_KEY") 
client_ai = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY"))

def get_store_name(url):
    try: return urlparse(url).netloc.replace("www.", "")
    except: return "Store"

def google_search_paginated(query, start_index=1, worldwide=False, blacklist=[]):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    cx = st.secrets.get("GOOGLE_CX")
    if not api_key or not cx: return []
    all_links = []
    base_url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={quote_plus(query)}&start={start_index}"
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
    return all_links

# --- 4. VISION & SCAN ENGINE ---
def analyze_with_vision(image_path, product_name):
    try:
        with Image.open(image_path) as img:
            img.thumbnail((800, 800)) 
            temp_p = f"v_{os.getpid()}.jpg"
            img.save(temp_p, "JPEG", quality=60)
        with open(temp_p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
        res = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [{"type": "text", "text": f"Price for {product_name}? Numeric only."}, 
                      {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
            max_tokens=50
        )
        if os.path.exists(temp_p): os.remove(temp_p)
        return res.choices[0].message.content.strip()
    except: return "AI Error"

def run_browser_watch(url, product_name):
    proxy = f"http://api.scraperapi.com?api_key={SAPI_KEY}&url={quote_plus(url)}&render=true&country_code=au"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(proxy, timeout=95000, wait_until="networkidle")
            time.sleep(5) 
            path = f"s_{os.getpid()}.png"
            page.screenshot(path=path)
            price = analyze_with_vision(path, product_name)
            with Image.open(path) as img:
                t_path = f"t_{os.getpid()}.png"
                img.crop((img.size[0]/4, 50, 3*img.size[0]/4, 450)).save(t_path)
            with open(t_path, "rb") as f:
                img_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
            for f in [path, t_path]: 
                if os.path.exists(f): os.remove(f)
            return price, img_b64
        except: return "Timeout", None
        finally: browser.close()

# --- 5. UI SETUP & LOGIN ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_browsers()

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("🔒 PriceWatchAI Access")
    t1, t2 = st.tabs(["Login", "Register"])
    with t1:
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                success, msg = check_login(u, p)
                if success:
                    st.session_state["logged_in"] = True
                    st.session_state["user"] = u
                    st.rerun()
                else: st.error(msg)
    with t2:
        with st.form("register"):
            nu, np = st.text_input("Username"), st.text_input("Password", type="password")
            if st.form_submit_button("Register", use_container_width=True):
                if nu and np:
                    ok, m = register_user(nu, np)
                    if ok: st.success(m)
                    else: st.error(m)
    st.stop()

# --- 6. MAIN APP LOGIC (LOADED ONLY AFTER LOGIN) ---
st.sidebar.success(f"User: {st.session_state['user']}")
if st.sidebar.button("Logout"):
    st.session_state["logged_in"] = False
    st.rerun()

with st.sidebar:
    st.header("Search Settings")
    with st.form("search_form"):
        bulk_input = st.text_input("Product Search")
        exclude_domains = st.text_input("Exclude Domains")
        is_worldwide = st.checkbox("Worldwide Search")
        st.divider()
        m_sku, m_url = st.text_input("Manual Name"), st.text_input("Manual URL")
        submit = st.form_submit_button("Search & Add")

    if submit:
        watchlist = get_watchlist()
        if m_sku and m_url:
            watchlist.append({"sku": m_sku, "url": m_url, "price": "Pending", "last_updated": "Never", "img_url": None})
        if bulk_input:
            st.session_state["last_query"] = bulk_input
            blist = [b.strip() for b in exclude_domains.split(",") if b.strip()]
            for start in [1, 11]:
                links = google_search_paginated(bulk_input, start, is_worldwide, blist)
                for l in links:
                    if not any(item['url'] == l for item in watchlist):
                        watchlist.append({"sku": bulk_input, "url": l, "price": "Pending", "last_updated": "Never", "img_url": None})
            st.session_state["next_start"] = 21
        st.session_state["items"] = watchlist
        st.rerun()

    if "last_query" in st.session_state and len(get_watchlist()) > 0:
        if st.button("🔍 Load 20 More Stores", use_container_width=True):
            query = st.session_state["last_query"]
            start = st.session_state["next_start"]
            with st.spinner("Fetching..."):
                for s in [start, start + 10]:
                    links = google_search_paginated(query, s, is_worldwide)
                    for l in links:
                        if not any(item['url'] == l for item in st.session_state["items"]):
                            st.session_state["items"].append({"sku": query, "url": l, "price": "Pending", "last_updated": "Never", "img_url": None})
            st.session_state["next_start"] += 20
            st.rerun()

    if st.button("🗑️ Clear Records", use_container_width=True):
        st.session_state["items"] = []
        st.session_state.pop("last_query", None)
        st.rerun()

# --- 7. TABLE DISPLAY ---
watchlist = get_watchlist()
if watchlist:
    df = pd.DataFrame(watchlist)
    df.insert(0, "Seq", range(1, len(df) + 1))
    st.metric("Total Stores Found", len(df))
    
    event = st.dataframe(
        df[["Seq", "img_url", "sku", "price", "last_updated", "url"]],
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row",
        column_config={
            "Seq": st.column_config.NumberColumn("Seq", width=30),
            "img_url": st.column_config.ImageColumn("Product", width="small"),
            "url": st.column_config.LinkColumn("Store Link")
        }
    )
    
    rows = event.selection.rows
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🚀 Run Deep Scan on Selected", use_container_width=True):
            if rows:
                status = st.empty()
                prog = st.progress(0)
                for i, idx in enumerate(rows):
                    item = st.session_state["items"][idx]
                    status.info(f"Scanning {i+1}/{len(rows)}: {get_store_name(item['url'])}")
                    p, img = run_browser_watch(item['url'], item['sku'])
                    aedt = (datetime.utcnow() + timedelta(hours=11)).strftime("%H:%M")
                    st.session_state["items"][idx].update({"price": p, "img_url": img, "last_updated": aedt})
                    prog.progress((i + 1) / len(rows))
                st.rerun()
    with c2:
        if rows:
            csv = df.iloc[rows].to_csv(index=False).encode('utf-8')
            st.download_button("📥 Export CSV", data=csv, file_name="prices.csv", use_container_width=True)
    with c3:
        if st.button("❌ Remove Selected", use_container_width=True):
            st.session_state["items"] = [item for j, item in enumerate(st.session_state["items"]) if j not in rows]
            st.rerun()
else:
    st.info("Watchlist empty. Search for a product in the sidebar.")
