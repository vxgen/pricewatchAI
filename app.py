import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib
import json
from datetime import date
from fpdf import FPDF

st.set_page_config(page_title="Product Check App", layout="wide")

# --- DATA NORMALIZER ---
def normalize_items(items):
    """Ensures all items have required keys and valid types."""
    clean_items = []
    for item in items:
        new_item = item.copy()
        try: new_item['qty'] = float(new_item.get('qty', 1))
        except: new_item['qty'] = 1.0
        try: new_item['price'] = float(new_item.get('price', 0))
        except: new_item['price'] = 0.0
        try: new_item['discount_val'] = float(new_item.get('discount_val', 0))
        except: new_item['discount_val'] = 0.0
        
        if 'discount_type' not in new_item: new_item['discount_type'] = '%'
        if 'desc' not in new_item: new_item['desc'] = ""
        
        # Calculate Total
        gross = new_item['qty'] * new_item['price']
        if new_item['discount_type'] == '%':
            disc = gross * (new_item['discount_val'] / 100)
        else:
            disc = new_item['discount_val']
        new_item['total'] = gross - disc
        
        clean_items.append(new_item)
    return clean_items

# --- HELPER: FIND ROW BY LABEL ---
def find_product_row(label, df):
    """Reconstructs search logic to find the exact row from the dropdown label."""
    if df.empty: return None
    
    # Identify valid columns
    def col_ok(d, c): return not d[c].astype(str).str.strip().eq('').all()
    valid_cols = [c for c in df.columns if col_ok(df, c)]
    if not valid_cols: return None
    
    name_col = valid_cols[0]
    for c in valid_cols: 
        if 'product' in c.lower() or 'model' in c.lower(): name_col = c; break
    
    # Re-generate labels to match
    forbidden = ['price', 'cost', 'date', 'category', 'srp', 'msrp']
    def mk_lbl(row):
        m = str(row[name_col]) if pd.notnull(row[name_col]) else ""
        if m.lower() in ['nan','']: return "SKIP"
        p = [m.strip()]
        for c in valid_cols:
            if c!=name_col and not any(k in c.lower() for k in forbidden):
                v = str(row[c]).strip()
                if v and v.lower() not in ['nan','']: p.append(v)
        return " | ".join(filter(None, p))

    df['Label'] = df.apply(mk_lbl, axis=1)
    match = df[df['Label'] == label]
    if not match.empty:
        return match.iloc[0], name_col
    return None, name_col

# --- CALLBACKS ---
def on_product_select():
    """Section 2: Auto-fills inputs when search changes."""
    lbl = st.session_state.get("q_search_product")
    if lbl:
        try:
            df = dm.get_all_products_df()
            row, name_col = find_product_row(lbl, df)
            
            if row is not None:
                # 1. NAME
                st.session_state['input_name'] = str(row[name_col])
                
                # 2. PRICE (Robust Cleaning)
                price_val = 0.0
                p_cols = [c for c in df.columns if any(x in c.lower() for x in ['price', 'msrp', 'srp', 'cost'])]
                for pc in p_cols:
                    try:
                        val = str(row[pc]).replace('A$', '').replace('$', '').replace(',', '').strip()
                        if val and val.lower() != 'nan':
                            price_val = float(val); break
                    except: continue
                st.session_state['input_price'] = price_val
                
                # 3. DESCRIPTION (Aggressive Search)
                desc_val = ""
                # Look for specific keywords first
                d_cols = [c for c in df.columns if any(x in c.lower() for x in ['desc', 'spec', 'detail'])]
                for dc in d_cols:
                    val = str(row[dc])
                    if val and val.lower() not in ['nan', 'none', '']:
                        desc_val = val
                        break # Take the first valid description found
                
                st.session_state['input_desc'] = desc_val
        except Exception as e: print(e)

def add_line_item_callback():
    """Adds item from Section 2."""
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
    
    # Clear
    st.session_state['input_name'] = ""; st.session_state['input_desc'] = ""
    st.session_state['input_price'] = 0.0; st.session_state['input_qty'] = 1.0
    st.session_state['q_search_product'] = None
    st.toast("Item Added!")

# --- PDF GENERATOR ---
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
    
    # Header
    pdf.set_font('Arial', '', 10); rx = 130
    pdf.set_xy(rx, 20); pdf.cell(30, 6, "Quote ref:", 0, 0); pdf.cell(30, 6, qid, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Issue date:", 0, 0); pdf.cell(30, 6, dt, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Expires:", 0, 0); pdf.cell(30, 6, exp, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Currency:", 0, 0); pdf.cell(30, 6, "AUD", 0, 1)
    pdf.ln(10)
    
    # Seller
    ys = pdf.get_y()
    pdf.set_font('Arial', 'B', 11); pdf.cell(90, 6, "Seller", 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.cell(90, 5, "MSI Australia", 0, 1)
    pdf.cell(90, 5, "Suite 304, Level 3, 63-79 Parramatta Rd", 0, 1)
    pdf.cell(90, 5, "Silverwater, NSW 2128, Australia", 0, 1)
    pdf.cell(90, 5, "Contact: Vincent Xu (vincentxu@msi.com)", 0, 1)
    
    # Buyer
    pdf.set_xy(110, ys)
    pdf.set_font('Arial', 'B', 11); pdf.cell(80, 6, "Buyer", 0, 1)
    pdf.set_x(110); pdf.set_font('Arial', '', 10)
    pdf.cell(80, 5, c_name, 0, 1)
    pdf.set_x(110); pdf.cell(80, 5, f"Email: {c_email}", 0, 1)
    if c_phone: pdf.set_x(110); pdf.cell(80, 5, f"Phone: {c_phone}", 0, 1)
    pdf.ln(15)
    
    # Table
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
                def col_ok(d,c): return not d[c].astype(str).str.strip().eq('').all()
                vcols = [c for c in df.columns if col_ok(df, c)]
                if vcols:
                    name_col = vcols[0]
                    for c in vcols: 
                        if 'product' in c.lower() or 'model' in c.lower(): name_col = c; break
                    search_df = df.copy()
                    forbidden = ['price', 'cost', 'date', 'category', 'srp']
                    def mk_lbl(r):
                        m = str(r[name_col]) if pd.notnull(r[name_col]) else ""
                        p = [m.strip()]
                        for c in vcols:
                            if c!=name_col and not any(k in c.lower() for k in forbidden):
                                v = str(r[c]).strip()
                                if v and v.lower() not in ['nan','']: p.append(v)
                        return " | ".join(filter(None, p))
                    search_df['Search_Label'] = search_df.apply(mk_lbl, axis=1)
                    opts = sorted([x for x in search_df['Search_Label'].unique().tolist() if x])
                    c1, c2 = st.columns([8, 1])
                    sel = c1.selectbox("Search", opts, index=None, key="s_main")
                    if c2.button("Clear"): st.session_state["s_main"] = None; st.rerun()
                    if sel:
                        st.divider()
                        res = search_df[search_df['Search_Label'] == sel]
                        for i, r in res.iterrows():
                            with st.expander(f"📦 {r[name_col]}", expanded=True):
                                hidden = ['price','cost','srp','msrp']
                                all_c = res.columns.tolist()
                                price_c = [c for c in all_c if any(k in c.lower() for k in hidden)]
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
            
            # --- 1. CLIENT ---
            st.subheader("1. Client Details")
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                q_client = c1.text_input("Client Name", value=st.session_state.get('edit_client', ''))
                q_email = c2.text_input("Client Email", value=st.session_state.get('edit_email', ''))
                q_phone = c3.text_input("Client Phone", value=st.session_state.get('edit_phone', '')) 
                c4, c5 = st.columns(2)
                q_date = c4.date_input("Date", date.today())
                q_expire = c5.date_input("Expires", date.today())

            st.divider()

            # --- 2. ADD ITEM ---
            st.subheader("2. Add Line Item")
            
            # Label Logic
            search_opts = []
            if not df.empty:
                def col_ok(d,c): return not d[c].astype(str).str.strip().eq('').all()
                vcols = [c for c in df.columns if col_ok(df, c)]
                if vcols:
                    name_col = vcols[0]
                    for c in vcols: 
                        if 'product' in c.lower() or 'model' in c.lower(): name_col = c; break
                    search_df = df.copy()
                    forbidden = ['price', 'cost', 'date', 'category', 'srp']
                    def mk_lbl(r):
                        m = str(r[name_col]) if pd.notnull(r[name_col]) else ""
                        if m.lower() in ['nan','']: return None
                        p = [m.strip()]
                        for c in vcols:
                            if c!=name_col and not any(k in c.lower() for k in forbidden):
                                v = str(r[c]).strip()
                                if v and v.lower() not in ['nan','']: p.append(v)
                        return " | ".join(filter(None, p))
                    search_df['Label'] = search_df.apply(mk_lbl, axis=1)
                    search_opts = sorted([x for x in search_df['Label'].unique().tolist() if x])
            
            st.selectbox("Search (Auto-fill)", options=search_opts, index=None, key="q_search_product", on_change=on_product_select)

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
            
            # --- 3. REVIEW (AUTO-UPDATE) ---
            st.subheader("3. Review Items")
            if st.session_state['quote_items']:
                st.session_state['quote_items'] = normalize_items(st.session_state['quote_items'])
                q_df = pd.DataFrame(st.session_state['quote_items'])
                
                # Combine options for dropdown
                curr_names = q_df['name'].unique().tolist()
                comb_opts = sorted(list(set(search_opts + curr_names))) if search_opts else curr_names
                
                edited = st.data_editor(
                    q_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    key="editor_quote",
                    column_config={
                        "name": st.column_config.SelectboxColumn("Item", options=comb_opts, required=True, width="large"),
                        "desc": st.column_config.TextColumn("Desc", width="medium"),
                        "qty": st.column_config.NumberColumn("Qty", min_value=1, required=True),
                        "price": st.column_config.NumberColumn("Price", format="$%.2f", required=True),
                        "discount_val": st.column_config.NumberColumn("Disc", min_value=0.0),
                        "discount_type": st.column_config.SelectboxColumn("Type", options=["%", "$"]),
                        "total": st.column_config.NumberColumn("Net", format="$%.2f", disabled=True)
                    }
                )
                
                # RECALCULATE & DETECT CHANGES FOR AUTO-FILL
                sub_ex = 0; tot_disc = 0; items_save = []
                
                # We iterate through the EDITED dataframe
                for idx, row in edited.iterrows():
                    # 1. AUTO-FILL LOGIC
                    # Check if the name in the edited row matches a "Search Label" from the DB.
                    # If it does, we look up the details.
                    # To prevent overwriting manual edits, we only overwrite if the Price/Desc look "empty" or default
                    # OR if we simply enforce that selecting a DB item forces a DB load.
                    # Enforcing DB load on name match is safer for "Select from dropdown" behavior.
                    
                    # Note: row['name'] is what the user selected in the table dropdown.
                    # st.session_state['quote_items'][idx]['name'] is the OLD name before edit.
                    
                    old_name = st.session_state['quote_items'][idx]['name'] if idx < len(st.session_state['quote_items']) else ""
                    new_name = row['name']
                    
                    current_desc = str(row.get('desc', ''))
                    current_price = float(row.get('price', 0))
                    
                    # If name changed to something in our Search List, trigger lookup
                    if new_name != old_name and new_name in search_opts:
                        row_data, name_col = find_product_row(new_name, df)
                        if row_data is not None:
                            # Update Desc
                            d_val = ""
                            d_cols = [c for c in df.columns if any(x in c.lower() for x in ['desc', 'spec', 'detail'])]
                            for dc in d_cols:
                                val = str(row_data[dc])
                                if val and val.lower() not in ['nan','']: d_val = val; break
                            current_desc = d_val
                            
                            # Update Price
                            p_val = 0.0
                            p_cols = [c for c in df.columns if any(x in c.lower() for x in ['price', 'msrp', 'srp', 'cost'])]
                            for pc in p_cols:
                                try:
                                    v = str(row_data[pc]).replace('A$', '').replace('$', '').replace(',', '').strip()
                                    if v and v.lower()!='nan': p_val = float(v); break
                                except: continue
                            current_price = p_val
                            
                            # Default Qty
                            row['qty'] = 1.0
                            st.toast(f"Auto-filled: {new_name}")

                    # 2. CALC
                    q = float(row.get('qty', 1)); p = current_price
                    d = float(row.get('discount_val', 0)); t = row.get('discount_type', '%')
                    
                    g = q * p
                    di = g * (d/100) if t == '%' else d
                    n = g - di
                    
                    sub_ex += n; tot_disc += di
                    
                    # 3. SAVE BACK
                    r = row.to_dict()
                    r['name'] = new_name # Persist the new name
                    r['desc'] = current_desc
                    r['price'] = current_price
                    r['qty'] = q
                    r['total'] = n
                    items_save.append(r)
                
                # If we modified data (auto-filled), we need to update session state
                # But we can't trigger a rerun inside the render loop easily without infinite loop risk unless we check for diffs carefully.
                # However, Streamlit's data_editor output 'edited' IS the new state. 
                # We just processed it into 'items_save'. 
                # Ideally, we update st.session_state['quote_items'] = items_save
                # But we only want to RERUN if we actually changed desc/price to show the user the new values.
                
                # Let's check if we need to force a refresh (only if we did an Auto-Fill)
                needs_refresh = False
                if len(items_save) == len(st.session_state['quote_items']):
                    for i in range(len(items_save)):
                        # If description or price is different from what was in session state (meaning we updated it via logic above), trigger refresh
                        if items_save[i]['desc'] != st.session_state['quote_items'][i]['desc'] or \
                           items_save[i]['price'] != st.session_state['quote_items'][i]['price']:
                            needs_refresh = True
                            break
                
                # Update State
                st.session_state['quote_items'] = items_save
                
                if needs_refresh:
                    st.rerun()

                gst = sub_ex*0.10; grand = sub_ex+gst
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Subtotal (Ex GST)", f"${sub_ex:,.2f}")
                m2.metric("Total Discount", f"${tot_disc:,.2f}")
                m3.metric("GST (10%)", f"${gst:,.2f}")
                m4.metric("Grand Total", f"${grand:,.2f}")
                
                c_a1, c_a2 = st.columns([1, 4])
                if c_a1.button("💾 Save Quote", type="primary"):
                    if not q_client: st.error("Name req.")
                    else:
                        payload = {
                            "client_name": q_client, "client_email": q_email, "client_phone": q_phone,
                            "total_amount": grand, "expiration_date": str(q_expire), "items": items_save
                        }
                        dm.save_quote(payload, st.session_state['user'])
                        st.success("Saved!"); st.session_state['quote_items'] = []; st.session_state['input_name'] = ""
                        time.sleep(1); st.rerun()
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
                            st.session_state['edit_client'] = r['client_name']
                            st.session_state['edit_email'] = r.get('client_email', '')
                            # Load phone if available
                            try: st.session_state['edit_phone'] = r.get('client_phone', '') # This requires saving support in DM to work fully
                            except: pass
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
