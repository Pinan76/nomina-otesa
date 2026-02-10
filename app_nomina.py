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

# Intentamos cargar el visor profesional
try:
    from streamlit_pdf_viewer import pdf_viewer
except ImportError:
    pdf_viewer = None

# --- 1. CONFIGURACION ---
st.set_page_config(page_title="OTESA - OTE", layout="wide", page_icon=":necktie:")

# Inicialización de estado
if 'admin' not in st.session_state: st.session_state.admin = False
if 'user' not in st.session_state: st.session_state.user = None

# ==========================================
# 🔧 CREDENCIALES (HARDCODED)
# ==========================================
SENDER_EMAIL = "nomina@trajesespanoles.mx"
EMAIL_PASSWORD = "OTE.R3c1b05" 
PASSWORD_ADMIN = "OTE.Admin2026"
SERVIDOR_SMTP = "smtp.ionos.com"
PUERTO_SMTP = 587
# ==========================================

# --- FUNCIONES DE BASE DE DATOS (FIRMADOS) ---
def cargar_db_firmas():
    if not os.path.exists('Bitacora_Firmas.csv'):
        df = pd.DataFrame(columns=['RFC', 'Archivo', 'Fecha_Firma', 'Estado'])
        df.to_csv('Bitacora_Firmas.csv', index=False)
        return df
    return pd.read_csv('Bitacora_Firmas.csv')

def registrar_firma_db(rfc, nombre_archivo):
    df = cargar_db_firmas()
    # Evitar duplicados
    if not ((df['RFC'] == rfc) & (df['Archivo'] == nombre_archivo)).any():
        nuevo = {
            'RFC': rfc,
            'Archivo': nombre_archivo,
            'Fecha_Firma': datetime.now().strftime("%Y-%m-%d %H:%M"),
            'Estado': 'FIRMADO'
        }
        df = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
        df.to_csv('Bitacora_Firmas.csv', index=False)

def obtener_status_global():
    """Compara archivos físicos vs base de datos de firmas"""
    if not os.path.exists("recibos"): return pd.DataFrame()
    
    # 1. Escanear carpeta física
    archivos_fisicos = [f for f in os.listdir("recibos") if f.endswith(".pdf")]
    
    data = []
    df_firmados = cargar_db_firmas()
    
    for archivo in archivos_fisicos:
        # Extraer RFC del nombre (Suponiendo que el PDF contiene el RFC en el nombre)
        # Intentamos extraerlo con regex del nombre del archivo si es posible
        match = re.search(r'[A-Z]{4}\d{6}[A-Z0-9]{3}', archivo)
        rfc_detectado = match.group(0) if match else "RFC_NO_DETECTADO"
        
        estado = "❌ PENDIENTE"
        if archivo in df_firmados['Archivo'].values:
            estado = "✅ FIRMADO"
            
        data.append({
            'Archivo': archivo,
            'RFC': rfc_detectado,
            'Estado': estado
        })
    
    return pd.DataFrame(data)

# --- FUNCIONES DE CORREO ---
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

# --- FUNCIONES DE EMPLEADO ---
def listar_recibos_empleado(rfc):
    if not os.path.exists("recibos"): return []
    # Busca cualquier PDF que contenga el RFC en su nombre
    patron = f"recibos/*{rfc}*.pdf"
    rutas = glob.glob(patron)
    archivos = [os.path.basename(r) for r in rutas]
    archivos.sort(reverse=True) # Los más recientes primero
    return archivos

def firmar_pdf(ruta_orig, firma_bytes):
    try:
        packet = io.BytesIO()
        can = pdf_canvas.Canvas(packet, pagesize=letter)
        img = Image.fromarray(firma_bytes.astype('uint8'), 'RGBA')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        # Posición de firma y texto (Ajuste 2cm izquierda solicitado)
        can.drawImage(ImageReader(img_buffer), 430, 250, width=150, height=60, mask='auto')
        can.drawString(430, 235, "Firma Digital Empleado")
        
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
    
    if modo == "verificar": 
        return not df[df['rfc'] == rfc].empty
    
    if modo == "login": 
        return not df[(df['rfc'] == rfc) & (df['password'] == password_input)].empty
    
    if modo == "registro":
        nuevo = pd.DataFrame([{'rfc': rfc, 'password': password_input}])
        df = pd.concat([df, nuevo], ignore_index=True)
        df.to_csv(file_cred, index=False)
        return True

def extraer_info_pdf(file):
    try:
        reader = PdfReader(file)
        text = reader.pages[0].extract_text()
        match = re.search(r'[A-Z]{4}\d{6}[A-Z0-9]{3}', text)
        rfc = match.group(0) if match else "DESCONOCIDO"
        name = file.name.replace(".pdf", "")
        return {"file": file.name, "name": name, "rfc": rfc}
    except: return {"file": file.name, "name": "Error", "rfc": "N/A"}

# ==========================================
# INTERFAZ
# ==========================================
with st.sidebar:
    if os.path.exists("logo.jpg"): st.image("logo.jpg", width=200)
    st.title("OTE V20.0")
    
    if st.toggle("Modo Admin"):
        pwd = st.text_input("Password Admin", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("Acceso Concedido")
        else:
            st.session_state.admin = False
            if pwd: st.error("Password incorrecto")
    else: st.session_state.admin = False

# --- PANEL ADMIN (RRHH) ---
if st.session_state.admin:
    st.title("📊 Tablero de Control RRHH")
    
    tab1, tab2, tab3 = st.tabs(["📂 Cargar Nómina", "🚨 Monitor de Firmas", "👥 Usuarios"])
    
    with tab1:
        st.write("Sube aquí los recibos PDF de la semana.")
        uploaded = st.file_uploader("Seleccionar Archivos", accept_multiple_files=True)
        if st.button("Procesar Archivos"):
            if uploaded:
                if not os.path.exists("recibos"): os.makedirs("recibos")
                db = []
                for f in uploaded:
                    # Guardar archivo físico
                    with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                    # Leer datos
                    db.append(extraer_info_pdf(f))
                
                # Guardar o actualizar maestro
                if os.path.exists("Control_Maestro.csv"):
                    df_old = pd.read_csv("Control_Maestro.csv")
                    df_new = pd.DataFrame(db)
                    df_final = pd.concat([df_old, df_new]).drop_duplicates(subset=['file'], keep='last')
                else:
                    df_final = pd.DataFrame(db)
                    
                df_final.to_csv("Control_Maestro.csv", index=False)
                st.success(f"✅ Procesados {len(db)} archivos nuevos.")

    with tab2:
        st.subheader("Estado de Cumplimiento")
        df_status = obtener_status_global()
        
        if not df_status.empty:
            col1, col2, col3 = st.columns(3)
            total = len(df_status)
            pendientes = len(df_status[df_status['Estado'] == "❌ PENDIENTE"])
            firmados = total - pendientes
            
            col1.metric("Total Recibos", total)
            col2.metric("Firmados", firmados)
            col3.metric("Pendientes", pendientes, delta_color="inverse")
            
            st.write("---")
            st.write("#### ⚠️ Lista de Pendientes")
            
            df_pendientes = df_status[df_status['Estado'] == "❌ PENDIENTE"]
            
            if not df_pendientes.empty:
                st.dataframe(df_pendientes, use_container_width=True)
                
                st.write("#### 📢 Enviar Alerta")
                archivo_alerta = st.selectbox("Seleccionar empleado a notificar:", df_pendientes['Archivo'])
                
                if st.button("Enviar Correo de Recordatorio"):
                    # 1. Buscar RFC del archivo
                    rfc_target = df_pendientes[df_pendientes['Archivo'] == archivo_alerta].iloc[0]['RFC']
                    
                    # 2. Buscar Email en directorio
                    email_target = None
                    if os.path.exists("Directorio_Contactos.csv"):
                        df_dir = pd.read_csv("Directorio_Contactos.csv")
                        match = df_dir[df_dir['rfc'] == rfc_target]
                        if not match.empty: 
                            email_target = match.iloc[0]['email']
                    
                    if email_target:
                        cuerpo = f"""Hola,
                        
Tienes un recibo de nómina pendiente de firma: {archivo_alerta}
Por favor ingresa al portal OTESA y fírmalo lo antes posible.

Atte. RRHH"""
                        ok, msg = enviar_correo_general(email_target, "ALERTA: Firma Pendiente", cuerpo)
                        if ok: st.success(f"Correo enviado a {email_target}")
                        else: st.error(f"Error: {msg}")
                    else:
                        st.warning(f"El RFC {rfc_target} no tiene correo registrado en el sistema.")
            else:
                st.success("🎉 ¡Felicidades! Todos los recibos están firmados.")
        else:
            st.info("No hay recibos cargados en el sistema.")

    with tab3:
        if os.path.exists("Directorio_Contactos.csv"):
            st.dataframe(pd.read_csv("Directorio_Contactos.csv"))
        else:
            st.info("Directorio vacío.")

# --- VISTA EMPLEADO ---
else:
    st.header("Portal Empleado")
    
    if not st.session_state.user:
        # LOGIN
        rfc_input = st.text_input("Ingresa tu RFC").upper()
        
        if rfc_input:
            # Validamos contra el maestro para ver si es empleado real
            es_empleado = False
            if os.path.exists("Control_Maestro.csv"):
                df_m = pd.read_csv("Control_Maestro.csv")
                if rfc_input in df_m['rfc'].values:
                    es_empleado = True
            
            if es_empleado:
                # Aquí estaba el error anterior (Corregido: gestionar_credenciales)
                if gestionar_credenciales(rfc_input, modo="verificar"):
                    # LOGIN
                    st.info(f"Hola {rfc_input}, ingresa tu contraseña.")
                    pwd = st.text_input("Contraseña", type="password")
                    if st.button("Entrar"):
                        if gestionar_credenciales(rfc_input, pwd, modo="login"):
                            st.session_state.user = {'rfc': rfc_input}
                            st.rerun()
                        else: st.error("Contraseña incorrecta")
                else:
                    # REGISTRO
                    st.warning("Usuario nuevo. Crea una contraseña.")
                    new_pwd = st.text_input("Nueva Contraseña", type="password")
                    conf_pwd = st.text_input("Confirmar Contraseña", type="password")
                    if st.button("Registrar"):
                        if new_pwd == conf_pwd and new_pwd:
                            gestionar_credenciales(rfc_input, new_pwd, modo="registro")
                            st.session_state.user = {'rfc': rfc_input}
                            st.rerun()
                        else: st.error("Error en contraseñas")
            else:
                st.error("RFC no encontrado en la base de datos de nómina.")

    else:
        # DENTRO DEL SISTEMA
        u = st.session_state.user
        st.success(f"Sesión activa: {u['rfc']}")
        
        # --- SELECCION DE RECIBO (HISTORIAL) ---
        mis_recibos = listar_recibos_empleado(u['rfc'])
        
        if mis_recibos:
            st.info(f"Tienes {len(mis_recibos)} recibos disponibles.")
            
            # Selector de archivo
            archivo_actual = st.selectbox("Selecciona el recibo:", mis_recibos)
            ruta_pdf = os.path.join("recibos", archivo_actual)
            
            # Verificar si ESTE archivo específico ya se firmó
            df_firmas = cargar_db_firmas()
            ya_firmado = ((df_firmas['RFC'] == u['rfc']) & (df_firmas['Archivo'] == archivo_actual)).any()
            
            if ya_firmado:
                st.success("✅ ESTE RECIBO YA ESTÁ FIRMADO.")
            else:
                st.warning("⚠️ PENDIENTE DE FIRMA.")
            
            # Visor
            with open(ruta_pdf, "rb") as f:
                pdf_bytes = f.read()
            
            if pdf_viewer:
                pdf_viewer(input=pdf_bytes, width=700)
            else:
                st.warning("Visor no disponible.")
            
            # Botón de firma (Solo si no está firmado)
            if not ya_firmado:
                st.write("---")
                st.write("✍️ **Firmar Documento:**")
                canvas = st_canvas(stroke_width=2, height=150, key=f"canvas_{archivo_actual}")
                
                if st.button("Firmar y Enviar"):
                    if canvas.image_data is not None:
                        path_firmado = firmar_pdf(ruta_pdf, canvas.image_data)
                        if path_firmado:
                            # Buscar correo del usuario
                            email_u = None
                            if os.path.exists("Directorio_Contactos.csv"):
                                dfd = pd.read_csv("Directorio_Contactos.csv")
                                m = dfd[dfd['rfc'] == u['rfc']]
                                if not m.empty: email_u = m.iloc[0]['email']
                            
                            ok, msg = enviar_correo_general(
                                email_u if email_u else SENDER_EMAIL,
                                f"Recibo Firmado - {archivo_actual}",
                                "Adjuntamos su documento firmado.",
                                path_firmado,
                                "Recibo_Firmado.pdf"
                            )
                            
                            if ok:
                                registrar_firma_db(u['rfc'], archivo_actual)
                                st.success("Firmado correctamente.")
                                st.rerun()
                            else:
                                st.error(f"Error envío: {msg}")
            
            st.download_button("Descargar PDF", pdf_bytes, file_name=archivo_actual)

        else:
            st.warning("No tienes recibos asignados.")
        
        st.write("---")
        with st.expander("Configurar Correo"):
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
                    st.rerun()
        
        if st.button("Cerrar Sesión"):
            st.session_state.user = None
            st.rerun()