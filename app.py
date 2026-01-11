import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib
import json
from datetime import date
from fpdf import FPDF
import time

st.set_page_config(page_title="Product Check App", layout="wide")

# --- 1. SHARED HELPERS ---

def normalize_items(items):
    """Ensures all items have valid keys/types."""
    clean = []
    for item in items:
        n = item.copy()
        try: n['qty'] = float(n.get('qty', 1))
        except: n['qty'] = 1.0
        try: n['price'] = float(n.get('price', 0))
        except: n['price'] = 0.0
        try: n['discount_val'] = float(n.get('discount_val', 0))
        except: n['discount_val'] = 0.0
        
        if 'discount_type' not in n: n['discount_type'] = '%'
        if 'desc' not in n: n['desc'] = ""
        if 'name' not in n or pd.isna(n['name']): n['name'] = ""
        
        # Calc Total (Excl GST line total)
        g = n['qty'] * n['price']
        d = g * (n['discount_val']/100) if n['discount_type'] == '%' else n['discount_val']
        n['total'] = g - d
        clean.append(n)
    return clean

def generate_search_labels(df):
    """Generates the 'Long String' labels for searching."""
    if df.empty: return df, None
    
    def col_ok(d, c): return not d[c].astype(str).str.strip().eq('').all()
    valid_cols = [c for c in df.columns if col_ok(df, c)]
    if not valid_cols: return df, None
    
    name_col = valid_cols[0]
    for c in valid_cols:
        if 'product' in c.lower() or 'model' in c.lower(): name_col = c; break
        
    forbidden = ['price', 'cost', 'date', 'category', 'srp', 'msrp', 'margin']
    
    def mk_lbl(row):
        m = str(row[name_col]) if pd.notnull(row[name_col]) else ""
        if m.lower() in ['nan','', 'none']: return None
        parts = [m.strip()]
        for c in valid_cols:
            if c != name_col and not any(k in c.lower() for k in forbidden):
                v = str(row[c]).strip()
                if v and v.lower() not in ['nan', 'none', '']: 
                    parts.append(v)
        return " | ".join(filter(None, parts))

    df['Search_Label'] = df.apply(mk_lbl, axis=1)
    return df, name_col

def extract_product_data(label, df_with_labels, name_col):
    """Parses a Long Label back into Name, Desc, Price."""
    if not label or df_with_labels.empty: return None
    
    match = df_with_labels[df_with_labels['Search_Label'] == label]
    if match.empty: return None
    row = match.iloc[0]
    
    p_name = str(row[name_col])
    
    p_price = 0.0
    p_cols = [c for c in df_with_labels.columns if any(x in c.lower() for x in ['price', 'msrp', 'srp', 'cost'])]
    for pc in p_cols:
        try:
            val = str(row[pc]).replace('A$', '').replace('$', '').replace(',', '').strip()
            if val and val.lower() != 'nan':
                p_price = float(val); break
        except: continue
        
    p_desc = ""
    d_cols = [c for c in df_with_labels.columns if any(x in c.lower() for x in ['long description', 'description', 'specs', 'detail'])]
    for dc in d_cols:
        val = str(row[dc])
        if val and val.lower() not in ['nan', 'none', '']:
            p_desc = val; break
            
    if not p_desc:
        parts = []
        forbidden = ['price', 'cost', 'date', 'category', 'srp', 'msrp', 'margin', 'search_label']
        for c in df_with_labels.columns:
            if c == name_col or any(k in c.lower() for k in forbidden): continue
            v = str(row[c]).strip()
            if v and v.lower() not in ['nan', 'none', '']:
                parts.append(f"{c}: {v}")
        p_desc = " | ".join(parts)

    return {"name": p_name, "desc": p_desc, "price": p_price}

# --- 2. CALLBACKS ---

def on_product_search_change():
    """Section 2 Callback"""
    lbl = st.session_state.get("q_search_product")
    if lbl:
        try:
            df = dm.get_all_products_df()
            df_lbl, name_col = generate_search_labels(df)
            data = extract_product_data(lbl, df_lbl, name_col)
            
            if data:
                st.session_state['input_name'] = data['name']
                st.session_state['input_desc'] = data['desc']
                st.session_state['input_price'] = data['price']
                st.session_state['input_qty'] = 1.0
        except Exception as e: print(e)

def add_line_item_callback():
    """Section 2 Button Callback"""
    name = st.session_state.get('input_name', '')
    if not name:
        st.toast("Name required!", icon="⚠️"); return

    item = {
        "name": name,
        "desc": st.session_state.get('input_desc', ''),
        "qty": st.session_state.get('input_qty', 1.0),
        "price": st.session_state.get('input_price', 0.0),
        "discount_val": st.session_state.get('input_disc_val', 0.0),
        "discount_type": st.session_state.get('input_disc_type', '%'),
        "total": 0
    }
    
    if 'quote_items' not in st.session_state: st.session_state['quote_items'] = []
    st.session_state['quote_items'].append(item)
    
    st.session_state['input_name'] = ""; st.session_state['input_desc'] = ""
    st.session_state['input_price'] = 0.0; st.session_state['input_qty'] = 1.0
    st.session_state['q_search_product'] = None
    st.toast("Item Added!")

def save_quote_callback():
    """SAFE SAVE: Runs before render to prevent API errors."""
    # 1. Validation
    if not st.session_state.get("q_client_input"):
        st.toast("Client Name Required!", icon="⚠️")
        return

    # 2. Get Items
    items = st.session_state.get('quote_items', [])
    if not items:
        st.toast("No items to save!", icon="⚠️")
        return
        
    # 3. Calculate Grand Total (Ex GST sum * 1.1)
    sub_ex = sum(i.get('total', 0) for i in items)
    grand_total = sub_ex * 1.10
    
    # 4. Prepare Payload
    payload = {
        "client_name": st.session_state.get("q_client_input"),
        "client_email": st.session_state.get("q_email_input"),
        "client_phone": st.session_state.get("q_phone_input"),
        "total_amount": grand_total,
        "expiration_date": str(st.session_state.get("q_expire_input")),
        "items": items
    }
    
    # 5. Save to DB
    dm.save_quote(payload, st.session_state['user'])
    
    # 6. Clear Inputs Safely
    st.session_state['quote_items'] = []
    st.session_state['input_name'] = ""
    
    st.toast("Quote Saved Successfully!", icon="✅")

# --- 3. PDF ENGINE ---
class QuotePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 20); self.cell(80, 10, 'MSI', 0, 0, 'L') 
        self.set_font('Arial', 'B', 16); self.cell(110, 10, 'Quote', 0, 1, 'R')
        self.ln(5)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Generated by Product Check App - MSI Confidential', 0, 0, 'C')

def create_pdf(quote_row):
    pdf = QuotePDF(); pdf.add_page(); pdf.set_auto_page_break(True, 15)
    items = normalize_items(json.loads(quote_row['items_json']))
    
    c_name = quote_row['client_name']
    c_email = quote_row.get('client_email', '')
    c_phone = str(quote_row.get('client_phone', '')) 
    qid = str(quote_row['quote_id'])
    dt = str(quote_row['created_at'])[:10]
    exp = str(quote_row.get('expiration_date', ''))
    
    sub = 0; disc_tot = 0
    for i in items:
        sub += i['total']
        g = i['qty']*i['price']; disc_tot += (g - i['total'])
    gst = sub * 0.10; grand = sub + gst
    
    pdf.set_font('Arial', '', 10); rx = 130
    pdf.set_xy(rx, 20); pdf.cell(30, 6, "Quote ref:", 0, 0); pdf.cell(30, 6, qid, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Issue date:", 0, 0); pdf.cell(30, 6, dt, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Expires:", 0, 0); pdf.cell(30, 6, exp, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Currency:", 0, 0); pdf.cell(30, 6, "AUD", 0, 1)
    pdf.ln(10)
    
    ys = pdf.get_y()
    pdf.set_font('Arial', 'B', 11); pdf.cell(90, 6, "Seller", 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.cell(90, 5, "MSI Australia", 0, 1)
    pdf.cell(90, 5, "Suite 304, Level 3, 63-79 Parramatta Rd", 0, 1)
    pdf.cell(90, 5, "Silverwater, NSW 2128, Australia", 0, 1)
    pdf.cell(90, 5, "Contact: Vincent Xu (vincentxu@msi.com)", 0, 1)
    
    pdf.set_xy(110, ys)
    pdf.set_font('Arial', 'B', 11); pdf.cell(80, 6, "Buyer", 0, 1)
    pdf.set_x(110); pdf.set_font('Arial', '', 10)
    pdf.cell(80, 5, c_name, 0, 1)
    pdf.set_x(110); pdf.cell(80, 5, f"Email: {c_email}", 0, 1)
    if c_phone: pdf.set_x(110); pdf.cell(80, 5, f"Phone: {c_phone}", 0, 1)
    pdf.ln(15)
    
    pdf.set_font('Arial', 'B', 12); pdf.cell(0, 10, "Line Items", 0, 1)
    pdf.set_font('Arial', 'B', 9); pdf.set_fill_color(245, 245, 245)
    pdf.cell(85, 8, "Item", 1, 0, 'L', True); pdf.cell(15, 8, "Qty", 1, 0, 'C', True)
    pdf.cell(25, 8, "Unit Price", 1, 0, 'R', True); pdf.cell(30, 8, "Discount", 1, 0, 'R', True)
    pdf.cell(35, 8, "Net Total", 1, 1, 'R', True)
    
    pdf.set_font('Arial', '', 9)
    for i in items:
        nm = i['name'][:42]+"..." if len(i['name'])>45 else i['name']
        ds = f"{i['discount_val']}%" if i['discount_type']=='%' else f"${i['discount_val']}"
        pdf.cell(85, 8, nm, 1, 0, 'L')
        pdf.cell(15, 8, str(int(i['qty'])), 1, 0, 'C')
        pdf.cell(25, 8, f"${i['price']:,.2f}", 1, 0, 'R')
        pdf.cell(30, 8, ds, 1, 0, 'R')
        pdf.cell(35, 8, f"${i['total']:,.2f}", 1, 1, 'R')
        if i['desc']:
            pdf.set_font('Arial', 'I', 8)
            pdf.cell(85, 6, f"   {i['desc'][:90]}", 'L', 0, 'L'); pdf.cell(105, 6, "", 'R', 1)
            pdf.set_font('Arial', '', 9)
    pdf.ln(5)
    pdf.set_x(120); pdf.cell(35, 6, "Subtotal (Ex GST):", 0, 0, 'R'); pdf.cell(35, 6, f"${sub:,.2f}", 0, 1, 'R')
    pdf.set_x(120); pdf.cell(35, 6, "Total Discount:", 0, 0, 'R'); pdf.cell(35, 6, f"-${disc_tot:,.2f}", 0, 1, 'R')
    pdf.set_x(120); pdf.cell(35, 6, "GST (10%):", 0, 0, 'R'); pdf.cell(35, 6, f"${gst:,.2f}", 0, 1, 'R')
    pdf.set_x(120); pdf.set_font('Arial', 'B', 10)
    pdf.cell(35, 8, "Grand Total:", 0, 0, 'R'); pdf.cell(35, 8, f"${grand:,.2f}", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1')

# --- AUTH ---
def hash_pw(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_login(u, p):
    try: users = dm.get_users()
    except: return False, "DB Error"
    if users.empty: return False, "No users"
    user = users[(users['username'] == u) & (users['password'] == hash_pw(p))]
    return (True, user.iloc[0]['role']) if not user.empty else (False, "Invalid")

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'user' not in st.session_state: st.session_state['user'] = ""
if 'quote_items' not in st.session_state: st.session_state['quote_items'] = []
# KEY FOR TABLE RESET
if 'table_key_id' not in st.session_state: st.session_state['table_key_id'] = 0

# Init Inputs
if 'input_name' not in st.session_state: st.session_state['input_name'] = ""
if 'input_desc' not in st.session_state: st.session_state['input_desc'] = ""
if 'input_price' not in st.session_state: st.session_state['input_price'] = 0.0
if 'input_qty' not in st.session_state: st.session_state['input_qty'] = 1.0
if 'input_disc_val' not in st.session_state: st.session_state['input_disc_val'] = 0.0
if 'input_disc_type' not in st.session_state: st.session_state['input_disc_type'] = '%'

def login_page():
    st.title("🔐 Login"); u = st.text_input("User"); p = st.text_input("Pass", type="password")
    if st.button("Sign In"):
        s, m = check_login(u, p)
        if s: st.session_state['logged_in'] = True; st.session_state['user'] = u; st.rerun()
        else: st.error(m)

def main_app():
    st.sidebar.title(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"): st.session_state['logged_in'] = False; st.rerun()
    menu = st.sidebar.radio("Navigate", ["Product Search & Browse", "Quote Generator", "Upload (Direct)", "Data Update (Direct)"])
    
    # 1. SEARCH
    if menu == "Product Search & Browse":
        st.header("🔎 Product Search")
        if st.button("Refresh"): dm.get_all_products_df.clear(); st.rerun()
        try: df = dm.get_all_products_df()
        except: df = pd.DataFrame()
        
        tab1, tab2 = st.tabs(["Search", "Browse"])
        with tab1:
            if not df.empty:
                df_lbl, name_col = generate_search_labels(df)
                if df_lbl.empty: st.warning("No valid data"); st.stop()
                
                df_lbl = df_lbl.dropna(subset=['Search_Label'])
                opts = sorted(df_lbl['Search_Label'].unique().tolist())
                
                c1, c2 = st.columns([8, 1])
                sel = c1.selectbox("Search", opts, index=None, key="s_main")
                if c2.button("Clear"): st.session_state["s_main"] = None; st.rerun()
                
                if sel:
                    st.divider()
                    res = df_lbl[df_lbl['Search_Label'] == sel]
                    for i, r in res.iterrows():
                        with st.expander(f"📦 {r[name_col]}", expanded=True):
                            hidden = ['price','cost','srp','msrp','search_label']
                            all_c = res.columns.tolist()
                            price_c = [c for c in all_c if any(k in c.lower() for k in hidden) and c!='Search_Label']
                            public = [c for c in all_c if c not in price_c and c!='Search_Label']
                            for c in public:
                                v = str(r[c]).strip()
                                if v and v.lower()!='nan': st.write(f"**{c}:** {r[c]}")
                            if price_c:
                                st.markdown("---")
                                if st.toggle("Show Price", key=f"t_{i}"):
                                    cols = st.columns(len(price_c))
                                    for idx, p in enumerate(price_c): cols[idx].metric(p, r[p])
            else: st.warning("Empty")
        with tab2:
            cats = dm.get_categories()
            if cats:
                cs = st.selectbox("Category", cats)
                if not df.empty and 'category' in df.columns:
                    cd = df[df['category'] == cs]
                    st.dataframe(cd, use_container_width=True)

    # 2. QUOTE
    elif menu == "Quote Generator":
        st.header("📝 Quotes")
        tab_create, tab_hist = st.tabs(["Create Quote", "History"])
        
        with tab_create:
            try: df = dm.get_all_products_df()
            except: df = pd.DataFrame()
            
            # Prepare Labels
            search_opts = []
            df_lbl = pd.DataFrame()
            name_col = None
            if not df.empty:
                df_lbl, name_col = generate_search_labels(df)
                if not df_lbl.empty:
                    df_lbl = df_lbl.dropna(subset=['Search_Label'])
                    search_opts = sorted(df_lbl['Search_Label'].unique().tolist())

            # 1. CLIENT
            st.subheader("1. Client Details")
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                q_client = c1.text_input("Client Name", key="q_client_input")
                q_email = c2.text_input("Client Email", key="q_email_input")
                q_phone = c3.text_input("Client Phone", key="q_phone_input") 
                c4, c5 = st.columns(2)
                q_date = c4.date_input("Date", date.today(), key="q_date_input")
                q_expire = c5.date_input("Expires", date.today(), key="q_expire_input")

            st.divider()

            # 2. ADD ITEM (SECTION 2)
            st.subheader("2. Add Line Item")
            
            st.selectbox(
                "Search Database (Auto-fill)", options=search_opts, index=None, 
                key="q_search_product", on_change=on_product_search_change
            )

            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                c1.text_input("Product Name", key="input_name")
                c2.text_input("Description", key="input_desc")
                c3, c4, c5, c6 = st.columns(4)
                c3.number_input("Qty", 1.0, step=1.0, key="input_qty")
                c4.number_input("Unit Price ($)", 0.0, key="input_price")
                c5.number_input("Discount", 0.0, key="input_disc_val")
                c6.selectbox("Type", ["%", "$"], key="input_disc_type")
                st.button("➕ Add Line Item", on_click=add_line_item_callback)

            st.divider()
            
            # 3. REVIEW (SECTION 3)
            st.subheader("3. Review Items")
            
            if st.session_state['quote_items']:
                st.session_state['quote_items'] = normalize_items(st.session_state['quote_items'])
                q_df = pd.DataFrame(st.session_state['quote_items'])
                
                # Combine options
                curr_names = q_df['name'].unique().tolist()
                comb_opts = sorted(list(set(search_opts + curr_names))) if search_opts else curr_names
                
                # DYNAMIC KEY forces reset when we increment it
                dyn_key = f"q_table_{st.session_state['table_key_id']}"
                
                edited = st.data_editor(
                    q_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    key=dyn_key,
                    column_config={
                        "name": st.column_config.SelectboxColumn("Item (Select to Auto-fill)", options=comb_opts, required=True, width="large"),
                        "desc": st.column_config.TextColumn("Description", width="medium"),
                        "qty": st.column_config.NumberColumn("Qty", min_value=1, required=True),
                        "price": st.column_config.NumberColumn("Price", format="$%.2f", required=True),
                        "discount_val": st.column_config.NumberColumn("Disc", min_value=0.0),
                        "discount_type": st.column_config.SelectboxColumn("Type", options=["%", "$"]),
                        "total": st.column_config.NumberColumn("Net", format="$%.2f", disabled=True)
                    }
                )
                
                # --- AUTO-DISTRIBUTE LOGIC ---
                items_save = []; trigger_refresh = False
                sub_ex = 0; tot_disc = 0
                
                for idx, row in edited.iterrows():
                    curr_name = str(row['name'])
                    
                    # IF NAME IS A LONG SEARCH STRING (contains pipe |), PARSE IT
                    if "|" in curr_name and curr_name in search_opts:
                        data = extract_product_data(curr_name, df_lbl, name_col)
                        if data:
                            row['name'] = data['name']
                            row['desc'] = data['desc']
                            row['price'] = data['price']
                            row['qty'] = 1.0
                            # FLAG TO RESET TABLE
                            trigger_refresh = True
                    
                    # Calc
                    q = float(row.get('qty', 1)); p = float(row.get('price', 0))
                    d = float(row.get('discount_val', 0)); t = row.get('discount_type', '%')
                    g = q * p
                    di = g * (d/100) if t == '%' else d
                    n = g - di
                    sub_ex += n; tot_disc += di
                    
                    r = row.to_dict(); r['total'] = n
                    items_save.append(r)
                
                # Update Session State
                st.session_state['quote_items'] = items_save
                
                # FORCE WIDGET RESET IF WE CHANGED DATA
                if trigger_refresh:
                    st.session_state['table_key_id'] += 1
                    st.rerun()

                gst = sub_ex*0.10; grand = sub_ex+gst
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Subtotal (Ex GST)", f"${sub_ex:,.2f}")
                m2.metric("Total Discount", f"${tot_disc:,.2f}")
                m3.metric("GST (10%)", f"${gst:,.2f}")
                m4.metric("Grand Total", f"${grand:,.2f}")
                
                c_a1, c_a2 = st.columns([1, 4])
                
                # SAVE BUTTON (USES CALLBACK)
                c_a1.button("💾 Save Quote", type="primary", on_click=save_quote_callback)
                
                if c_a2.button("Clear"): st.session_state['quote_items'] = []; st.rerun()
            else: st.info("No items.")

        with tab_hist:
            st.subheader("📜 History")
            if st.button("Refresh"): dm.get_quotes.clear(); st.rerun()
            hist = dm.get_quotes()
            if not hist.empty:
                hist = hist.sort_values(by="created_at", ascending=False)
                for i, r in hist.iterrows():
                    with st.expander(f"{r['created_at']} | {r['client_name']} | ${float(r['total_amount']):,.2f}"):
                        c1, c2, c3 = st.columns(3)
                        try:
                            pdf = create_pdf(r)
                            c1.download_button("📩 PDF", pdf, f"Quote_{r['quote_id']}.pdf", "application/pdf")
                        except: c1.error("Error")
                        if c2.button("✏️ Edit", key=f"e_{r['quote_id']}"):
                            st.session_state['quote_items'] = normalize_items(json.loads(r['items_json']))
                            
                            # PRE-FILL KEYS FOR EDITING
                            st.session_state['q_client_input'] = r['client_name']
                            st.session_state['q_email_input'] = r.get('client_email', '')
                            st.session_state['q_phone_input'] = r.get('client_phone', '')
                            
                            st.toast("Loaded!"); time.sleep(1)
                        if c3.button("🗑️ Delete", key=f"d_{r['quote_id']}"):
                            dm.delete_quote(r['quote_id'], st.session_state['user']); st.rerun()
            else: st.info("Empty")

    # 3. UPLOAD (Same)
    elif menu == "Upload (Direct)":
        st.header("📂 Upload"); c1, c2 = st.columns(2)
        with c1: cats = dm.get_categories(); cs = st.selectbox("Cat", cats if cats else ["Default"])
        with c2: 
            nc = st.text_input("New"); 
            if st.button("Add"): 
                if nc: dm.add_category(nc, st.session_state['user']); st.rerun()
        up = st.file_uploader("File", accept_multiple_files=True); hh = st.checkbox("Headers?", True)
        if up:
            for f in up:
                if st.button(f"Save {f.name}"):
                    try:
                        df = pd.read_csv(f, header=0 if hh else None) if f.name.endswith('csv') else pd.read_excel(f, header=0 if hh else None)
                        dm.save_products_dynamic(df.dropna(how='all'), cs, st.session_state['user'])
                        st.success("Saved"); time.sleep(1); st.rerun()
                    except Exception as e: st.error(str(e))

    # 4. UPDATE (Same)
    elif menu == "Data Update (Direct)":
        st.header("🔄 Update"); cats = dm.get_categories(); cs = st.selectbox("Cat", cats)
        up = st.file_uploader("File"); hh = st.checkbox("Headers?", True, key="uph")
        if up:
            df = pd.read_csv(up, header=0 if hh else None) if up.name.endswith('csv') else pd.read_excel(up, header=0 if hh else None)
            st.write(df.head(3)); k = st.selectbox("Key", list(df.columns))
            if st.button("Update"):
                r = dm.update_products_dynamic(df, cs, st.session_state['user'], k)
                st.success(f"Done. New: {r['new']}, EOL: {r['eol']}")

if st.session_state['logged_in']: main_app()
else: login_page()
