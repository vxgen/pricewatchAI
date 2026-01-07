import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib

st.set_page_config(page_title="Product Check App", layout="wide")

# --- AUTH HELPERS ---
def hash_pw(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_login(username, password):
    users = dm.get_users()
    if users.empty: return False, "No users in DB"
    hashed = hash_pw(password)
    user = users[(users['username'] == username) & (users['password'] == hashed)]
    if not user.empty:
        status = user.iloc[0]['status']
        if status == 'active': return True, user.iloc[0]['role']
        if status == 'pending': return False, "Account pending approval"
    return False, "Invalid credentials"

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'user' not in st.session_state: st.session_state['user'] = ""

# --- LOGIN PAGE ---
def login_page():
    st.title("🔐 Login")
    tab1, tab2 = st.tabs(["Login", "Register"])
    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Sign In"):
            success, msg = check_login(u, p)
            if success:
                st.session_state['logged_in'] = True
                st.session_state['user'] = u
                dm.log_action(u, "Login", "Success")
                st.rerun()
            else:
                st.error(msg)
    with tab2:
        new_u = st.text_input("New Username")
        new_p = st.text_input("New Password", type="password")
        new_e = st.text_input("Email")
        if st.button("Register"):
            dm.register_user(new_u, hash_pw(new_p), new_e)
            st.success("Sent. Wait for approval.")

# --- MAIN APP ---
def main_app():
    st.sidebar.title(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"):
        st.session_state['logged_in'] = False
        st.rerun()
        
    menu = st.sidebar.radio("Navigate", ["Product Check", "Upload & Mapping"])
    
    # 1. PRODUCT CHECK
    if menu == "Product Check":
        st.header("🔎 Product Check")
        query = st.text_input("Search Product")
        if query:
            results = dm.search_products(query)
            if not results.empty:
                st.write(f"Found {len(results)} items")
                for i, row in results.iterrows():
                    name_display = row.get("Product Name", row.get("name", "Item"))
                    with st.expander(f"{name_display}"):
                        for col in results.columns:
                            # Hide system columns or price initially
                            if col not in ['category', 'last_updated', 'Price', 'price']:
                                st.write(f"**{col}:** {row[col]}")
                        
                        price_key = 'Price' if 'Price' in row else 'price'
                        if price_key in row:
                            if st.button("View Price", key=f"p_{i}"):
                                st.metric("Price", row[price_key])
            else:
                st.warning("No matches found.")

    # 2. UPLOAD & MAPPING
    elif menu == "Upload & Mapping":
        st.header("📂 File Upload & Schema Config")
        
        # --- TOP SECTION: CATEGORIES & SCHEMA MANAGEMENT ---
        c_left, c_right = st.columns([1, 1])
        
        with c_left:
            st.subheader("1. Category Selection")
            cats = dm.get_categories()
            cat_sel = st.selectbox("Select Category", cats)
            
            c_new, c_btn = st.columns([2,1])
            new_cat = c_new.text_input("New Category Name")
            if c_btn.button("Add Cat"):
                if new_cat:
                    dm.add_category(new_cat, st.session_state['user'])
                    st.success(f"Added '{new_cat}'")
                    st.rerun()

        with c_right:
            st.subheader("2. Target Column Setup")
            with st.expander("Manage 'Map To' Columns (Add/Edit/Delete)", expanded=False):
                current_schema = dm.get_schema()
                st.write(f"Current Target Columns: {current_schema}")
                
                # Add New Target Column
                c_add_col, c_add_btn = st.columns([2,1])
                new_col_name = c_add_col.text_input("Add Target Column")
                if c_add_btn.button("Add"):
                    if new_col_name:
                        dm.add_schema_column(new_col_name)
                        st.success("Column Added")
                        st.rerun()
                
                # Delete Target Column
                c_del_col, c_del_btn = st.columns([2,1])
                del_col_name = c_del_col.selectbox("Delete Column", ["Select..."] + current_schema)
                if c_del_btn.button("Delete"):
                    if del_col_name != "Select...":
                        dm.delete_schema_column(del_col_name)
                        st.success("Column Deleted")
                        st.rerun()

        st.divider()

        # --- BOTTOM SECTION: UPLOAD & MAP ---
        target_columns = dm.get_schema()
        if not target_columns:
            st.error("You have no Target Columns defined. Please add them in section 2 above.")
            return

        files = st.file_uploader("Upload Excel/CSV", accept_multiple_files=True)
        
        if files:
            for file in files:
                st.markdown(f"### Processing: {file.name}")
                if file.name.endswith('csv'): df = pd.read_csv(file)
                else: df = pd.read_excel(file)
                
                st.write("Preview:", df.head(3))
                
                st.info("Map the columns from your file (Dropdown) to your Target Columns (Bold Label)")
                
                mapping = {}
                cols = st.columns(3)
                
                # Available file columns + a "Skip" option
                file_cols = ["(Skip)"] + list(df.columns)
                
                for i, target_col in enumerate(target_columns):
                    # SMART INDEX LOGIC
                    # If target matches file column exactly, select it. 
                    # If NOT, select index 0 ("Skip").
                    default_idx = 0 
                    if target_col in df.columns:
                        default_idx = file_cols.index(target_col)
                    
                    with cols[i % 3]:
                        selected_col = st.selectbox(
                            f"Target: **{target_col}**", 
                            file_cols, 
                            index=default_idx,
                            key=f"{file.name}_{target_col}"
                        )
                        if selected_col != "(Skip)":
                            mapping[target_col] = selected_col
                
                if st.button(f"Format & Save {file.name}", key=f"btn_{file.name}"):
                    if not mapping:
                        st.error("Please map at least one column.")
                    else:
                        new_data = {}
                        for target, source in mapping.items():
                            new_data[target] = df[source]
                        
                        clean_df = pd.DataFrame(new_data)
                        dm.save_products_dynamic(clean_df, cat_sel, st.session_state['user'])
                        
                        output = BytesIO()
                        with pd.ExcelWriter(output) as writer:
                            clean_df.to_excel(writer, index=False)
                        st.download_button("Download Formatted", output.getvalue(), f"fmt_{file.name}.xlsx")
                        st.success("Saved & Ready")

if st.session_state['logged_in']:
    main_app()
else:
    login_page()
