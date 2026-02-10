# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import base64
import os
import re
import glob
import smtplib
import io
from datetime import datetime
from email.message import EmailMessage
from pypdf import PdfReader, PdfWriter
from streamlit_drawable_canvas import st_canvas
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image

try:
    from streamlit_pdf_viewer import pdf_viewer
except ImportError:
    pdf_viewer = None

# --- 1. CONFIGURACION ---
# CAMBIO DE NOMBRE: Nexus -> OTESA
st.set_page_config(page_title="OTESA - Nómina", layout="wide", page_icon=":necktie:")

if 'admin' not in st.session_state: st.session_state.admin = False
if 'user' not in st.session_state: st.session_state.user = None

# ==========================================
# 🔧 CREDENCIALES
# ==========================================
SENDER_EMAIL = "nomina@trajesespanoles.mx"
EMAIL_PASSWORD = "OTE.R3c1b05" 
PASSWORD_ADMIN = "OTE.Admin2026"
SERVIDOR_SMTP = "smtp.ionos.com"
PUERTO_SMTP = 587
# ==========================================

# --- FUNCIONES DE BASE DE DATOS ---
def cargar_db_firmas():
    if not os.path.exists('Bitacora_Firmas.csv'):
        df = pd.DataFrame(columns=['RFC', 'Archivo', 'Fecha_Firma', 'Estado'])
        df.to_csv('Bitacora_Firmas.csv', index=False)
        return df
    return pd.read_csv('Bitacora_Firmas.csv')

def registrar_firma_db(rfc, nombre_archivo_relativo):
    df = cargar_db_firmas()
    if not ((df['RFC'] == rfc) & (df['Archivo'] == nombre_archivo_relativo)).any():
        nuevo = {
            'RFC': rfc,
            'Archivo': nombre_archivo_relativo,
            'Fecha_Firma': datetime.now().strftime("%Y-%m-%d %H:%M"),
            'Estado': 'FIRMADO'
        }
        df = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
        df.to_csv('Bitacora_Firmas.csv', index=False)

def obtener_status_global():
    if os.path.exists("Control_Maestro.csv"):
        df_maestro = pd.read_csv("Control_Maestro.csv")
    else:
        files = glob.glob("recibos/**/*.pdf", recursive=True)
        archivos_relativos = [os.path.relpath(f, "recibos") for f in files]
        df_maestro = pd.DataFrame({'file': archivos_relativos, 'rfc': '?', 'name': 'Sin Indexar'})

    df_firmas = cargar_db_firmas()
    
    status_list = []
    for index, row in df_maestro.iterrows():
        archivo_rel = row['file']
        rfc = row['rfc']
        nombre = row['name']
        
        estado = "❌ PENDIENTE"
        if not df_firmas.empty:
            coincidencia = df_firmas[(df_firmas['RFC'] == rfc) & (df_firmas['Archivo'] == archivo_rel)]
            if not coincidencia.empty:
                estado = "✅ FIRMADO"
        
        status_list.append({
            'Semana/Archivo': archivo_rel,
            'Empleado': nombre,
            'RFC': rfc,
            'Estado': estado
        })
        
    return pd.DataFrame(status_list)

def reconstruir_maestro_desde_archivos():
    if not os.path.exists("recibos"): return 0
    archivos = glob.glob("recibos/**/*.pdf", recursive=True)
    db = []
    
    for ruta_completa in archivos:
        try:
            nombre_relativo = os.path.relpath(ruta_completa, "recibos")
            reader = PdfReader(ruta_completa)
            text = reader.pages[0].extract_text()
            match = re.search(r'[A-Z]{4}\d{6}[A-Z0-9]{3}', text)
            rfc = match.group(0) if match else "DESCONOCIDO"
            nombre_limpio = os.path.basename(ruta_completa).replace(".pdf", "").replace("_", " ")
            
            db.append({
                "file": nombre_relativo,
                "name": nombre_limpio,
                "rfc": rfc
            })
        except: continue
            
    if db:
        df = pd.DataFrame(db)
        df.to_csv("Control_Maestro.csv", index=False)
        return len(db)
    return 0

# --- CORREO ---
def enviar_correo_general(destinatario, asunto, cuerpo, adjunto_path=None, nombre_adjunto=None):
    try:
        msg = EmailMessage()
        msg['Subject'] = asunto
        msg['From'] = SENDER_EMAIL
        msg['To'] = destinatario
        msg.set_content(cuerpo)

        if adjunto_path:
            with open(adjunto_path, 'rb') as f:
                file_data = f.read()
                msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=nombre_adjunto)

        server = smtplib.SMTP(SERVIDOR_SMTP, PUERTO_SMTP)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True, "Enviado"
    except Exception as e:
        return False, str(e)

# --- FUNCIONES EMPLEADO ---
def listar_recibos_empleado_db(rfc):
    if not os.path.exists("Control_Maestro.csv"): return []
    df = pd.read_csv("Control_Maestro.csv")
    archivos_asignados = df[df['rfc'] == rfc]['file'].tolist()
    
    archivos_validos = []
    for f_relativo in archivos_asignados:
        ruta_completa = os.path.join("recibos", f_relativo)
        if os.path.exists(ruta_completa):
            archivos_validos.append(f_relativo)
    
    # Ordenamos: Recientes primero
    archivos_validos.sort(reverse=True)
    return archivos_validos

def firmar_pdf(ruta_orig, firma_bytes):
    try:
        packet = io.BytesIO()
        can = pdf_canvas.Canvas(packet, pagesize=letter)
        img = Image.fromarray(firma_bytes.astype('uint8'), 'RGBA')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        # --- NUEVAS COORDENADAS SOLICITADAS ---
        # Imagen: (430, 250)
        can.drawImage(ImageReader(img_buffer), 430, 250, width=150, height=60, mask='auto')
        # Texto: (430, 235)
        can.drawString(430, 235, "Firma Digital")
        # --------------------------------------
        
        can.save()
        packet.seek(0)
        new_pdf = PdfReader(packet)
        existing_pdf = PdfReader(open(ruta_orig, "rb"))
        output = PdfWriter()
        page = existing_pdf.pages[0]
        page.merge_page(new_pdf.pages[0])
        output.add_page(page)
        for i in range(1, len(existing_pdf.pages)):
            output.add_page(existing_pdf.pages[i])
        
        nombre_salida = ruta_orig.replace(".pdf", "_FIRMADO.pdf")
        with open(nombre_salida, "wb") as f:
            output.write(f)
        return nombre_salida
    except: return None

def gestionar_credenciales(rfc, password_input=None, modo="verificar"):
    file_cred = 'credenciales.csv'
    if not os.path.exists(file_cred): 
        pd.DataFrame(columns=['rfc', 'password']).to_csv(file_cred, index=False)
    
    df = pd.read_csv(file_cred)
    
    if modo == "verificar": return not df[df['rfc'] == rfc].empty
    if modo == "login": return not df[(df['rfc'] == rfc) & (df['password'] == password_input)].empty
    if modo == "registro":
        nuevo = pd.DataFrame([{'rfc': rfc, 'password': password_input}])
        df = pd.concat([df, nuevo], ignore_index=True)
        df.to_csv(file_cred, index=False)
        return True

# ==========================================
# INTERFAZ
# ==========================================
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=200)
    st.title("OTESA V24.0")
    
    if st.toggle("Modo Admin"):
        pwd = st.text_input("Password Admin", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("OK")
        else:
            st.session_state.admin = False
    else: st.session_state.admin = False

# --- PANEL ADMIN (RRHH) ---
if st.session_state.admin:
    st.title("📊 Tablero OTESA - RRHH")
    
    tab1, tab2, tab3, tab4 = st.tabs(["🛠️ Base de Datos", "📂 Cargar Nómina", "🚨 Monitor de Firmas", "👥 Usuarios"])
    
    with tab1:
        st.subheader("Indexación de Carpetas")
        st.info("Reconstruir DB para detectar subcarpetas.")
        
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔄 Reconstruir Base de Datos", type="primary"):
                with st.spinner("Escaneando..."):
                    cantidad = reconstruir_maestro_desde_archivos()
                    if cantidad > 0:
                        st.success(f"✅ Se indexaron {cantidad} recibos.")
                        st.rerun()
                    else: st.error("No se encontraron archivos.")
        
        with col_b:
            if os.path.exists("Control_Maestro.csv"):
                df = pd.read_csv("Control_Maestro.csv")
                st.write(f"Indexados: **{len(df)}**")
                st.dataframe(df, height=200)

    with tab2:
        uploaded = st.file_uploader("Subir PDFs", accept_multiple_files=True)
        if st.button("Procesar Archivos"):
            if uploaded:
                if not os.path.exists("recibos"): os.makedirs("recibos")
                for f in uploaded:
                    with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                st.success("Archivos subidos. Ahora reconstruye la DB.")

    with tab3:
        st.subheader("Cumplimiento OTESA")
        df_status = obtener_status_global()
        
        if not df_status.empty:
            col1, col2, col3 = st.columns(3)
            pendientes = len(df_status[df_status['Estado'] == "❌ PENDIENTE"])
            firmados = len(df_status[df_status['Estado'] == "✅ FIRMADO"])
            
            col1.metric("Total", len(df_status))
            col2.metric("Firmados", firmados)
            col3.metric("Pendientes", pendientes, delta_color="inverse")
            
            filtro = st.radio("Mostrar:", ["Pendientes", "Todos", "Firmados"], horizontal=True)
            if filtro == "Pendientes":
                df_show = df_status[df_status['Estado'] == "❌ PENDIENTE"]
            elif filtro == "Firmados":
                df_show = df_status[df_status['Estado'] == "✅ FIRMADO"]
            else:
                df_show = df_status
                
            st.dataframe(df_show, use_container_width=True)
            
            st.write("#### 📢 Cobranza de Firmas")
            lista_p = df_status[df_status['Estado'] == "❌ PENDIENTE"]
            
            if not lista_p.empty:
                seleccion = st.selectbox("Seleccionar empleado:", lista_p['Semana/Archivo'])
                
                if st.button("Enviar Alerta"):
                    rfc_target = lista_p[lista_p['Semana/Archivo'] == seleccion].iloc[0]['RFC']
                    email_target = None
                    if os.path.exists("Directorio_Contactos.csv"):
                        df_dir = pd.read_csv("Directorio_Contactos.csv")
                        match = df_dir[df_dir['rfc'] == rfc_target]
                        if not match.empty: email_target = match.iloc[0]['email']
                    
                    if email_target:
                        cuerpo = f"Hola,\nRecibo pendiente en OTESA: {seleccion}.\nFavor de firmar."
                        ok, msg = enviar_correo_general(email_target, "ALERTA OTESA: Firma Pendiente", cuerpo)
                        if ok: st.success(f"Alerta enviada a {email_target}")
                        else: st.error(msg)
                    else: st.warning("Sin correo registrado.")
        else: st.info("Base de datos vacía.")

    with tab4:
        if os.path.exists("Directorio_Contactos.csv"):
            st.dataframe(pd.read_csv("Directorio_Contactos.csv"))

# --- VISTA EMPLEADO ---
else:
    st.header("Portal OTESA")
    
    if not st.session_state.user:
        rfc_input = st.text_input("Ingresa tu RFC").upper()
        
        if rfc_input:
            if not os.path.exists("Control_Maestro.csv"):
                st.error("Contacta a RRHH (DB no encontrada).")
            else:
                df_m = pd.read_csv("Control_Maestro.csv")
                match_user = df_m[df_m['rfc'] == rfc_input]
                
                if not match_user.empty:
                    nombre_empleado = match_user.iloc[0]['name']
                    
                    if gestionar_credenciales(rfc_input, modo="verificar"):
                        st.info(f"Hola **{nombre_empleado}**, ingresa contraseña.")
                        pwd = st.text_input("Contraseña", type="password")
                        if st.button("Entrar"):
                            if gestionar_credenciales(rfc_input, pwd, modo="login"):
                                st.session_state.user = {'rfc': rfc_input, 'name': nombre_empleado}
                                st.rerun()
                            else: st.error("Incorrecto")
                    else:
                        st.warning(f"Bienvenido {nombre_empleado}. Crea tu contraseña.")
                        new_p = st.text_input("Nueva Contraseña", type="password")
                        conf_p = st.text_input("Confirmar", type="password")
                        if st.button("Registrar"):
                            if new_p == conf_p and new_p:
                                gestionar_credenciales(rfc_input, new_p, modo="registro")
                                st.session_state.user = {'rfc': rfc_input, 'name': nombre_empleado}
                                st.rerun()
                            else: st.error("No coinciden")
                else: st.error("RFC no encontrado.")

    else:
        u = st.session_state.user
        st.success(f"Empleado: {u['name']}")
        
        mis_recibos = listar_recibos_empleado_db(u['rfc'])
        
        if mis_recibos:
            # --- FILTRO: SOLO MOSTRAR PENDIENTES (SIMPLIFICACIÓN SOLICITADA) ---
            df_firmas = cargar_db_firmas()
            
            # Separamos los recibos en Pendientes y Firmados
            recibos_pendientes = []
            recibos_firmados = []
            
            for r in mis_recibos:
                if ((df_firmas['RFC'] == u['rfc']) & (df_firmas['Archivo'] == r)).any():
                    recibos_firmados.append(r)
                else:
                    recibos_pendientes.append(r)
            
            # Lógica de visualización:
            # Si hay pendientes, mostramos el selector SOLO con pendientes por defecto
            if recibos_pendientes:
                st.info(f"Tienes {len(recibos_pendientes)} recibo(s) pendiente(s) de firma.")
                archivo_actual = st.selectbox("Selecciona Recibo a Firmar:", recibos_pendientes)
                ya_firmado = False
            elif recibos_firmados:
                st.success("✅ ¡Felicidades! Estás al día. Todos tus recibos están firmados.")
                if st.checkbox("Ver historial de firmados"):
                    archivo_actual = st.selectbox("Recibos Anteriores:", recibos_firmados)
                    ya_firmado = True
                else:
                    archivo_actual = None
            else:
                archivo_actual = None

            # PROCESO DE FIRMA
            if archivo_actual:
                ruta_pdf = os.path.join("recibos", archivo_actual)
                
                with open(ruta_pdf, "rb") as f:
                    pdf_bytes = f.read()
                
                if pdf_viewer:
                    pdf_viewer(input=pdf_bytes, width=700)
                else: st.warning("Visor no disponible.")
                
                if not ya_firmado:
                    st.write("---")
                    st.write("✍️ **Firma Digital:**")
                    canvas = st_canvas(stroke_width=2, height=150, key=f"c_{archivo_actual}")
                    
                    if st.button("Firmar y Enviar"):
                        if canvas.image_data is not None:
                            path_firmado = firmar_pdf(ruta_pdf, canvas.image_data)
                            if path_firmado:
                                email_u = None
                                if os.path.exists("Directorio_Contactos.csv"):
                                    dfd = pd.read_csv("Directorio_Contactos.csv")
                                    m = dfd[dfd['rfc'] == u['rfc']]
                                    if not m.empty: email_u = m.iloc[0]['email']
                                
                                ok, msg = enviar_correo_general(
                                    email_u if email_u else SENDER_EMAIL,
                                    f"Recibo Firmado - {os.path.basename(archivo_actual)}",
                                    "Adjuntamos su documento firmado OTESA.",
                                    path_firmado,
                                    "Recibo_Firmado_OTESA.pdf"
                                )
                                
                                if ok:
                                    registrar_firma_db(u['rfc'], archivo_actual)
                                    st.success("Firmado correctamente.")
                                    st.rerun()
                                else: st.error(f"Error envío: {msg}")
                
                st.download_button("Descargar PDF", pdf_bytes, file_name=os.path.basename(archivo_actual))

        else:
            st.warning("No tienes recibos asignados.")
        
        st.write("---")
        with st.expander("Configurar mi Correo"):
            mail_in = st.text_input("Correo Personal")
            if st.button("Actualizar"):
                if "@" in mail_in:
                    f_con = "Directorio_Contactos.csv"
                    if not os.path.exists(f_con): pd.DataFrame(columns=['rfc','email']).to_csv(f_con, index=False)
                    dfc = pd.read_csv(f_con)
                    dfc = dfc[dfc['rfc'] != u['rfc']]
                    nuevo = pd.DataFrame([{'rfc': u['rfc'], 'email': mail_in}])
                    pd.concat([dfc, nuevo]).to_csv(f_con, index=False)
                    st.success("Actualizado")
        
        if st.button("Cerrar Sesión"):
            st.session_state.user = None
            st.rerun()