# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import base64
import os
import re
import glob
import smtplib
import io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.header import Header
from email import encoders
from pypdf import PdfReader, PdfWriter
from streamlit_drawable_canvas import st_canvas
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Nexus - OTE", layout="wide", page_icon=":necktie:")

# --- 2. INICIALIZACIÓN DE VARIABLES DE ESTADO (ESTO ARREGLA EL ERROR ATTRIBUTEERROR) ---
if 'admin' not in st.session_state: st.session_state.admin = False
if 'user' not in st.session_state: st.session_state.user = None
if 'autenticado' not in st.session_state: st.session_state.autenticado = False

# ==========================================
# 🔧 ZONA DE SEGURIDAD CORREO (HARDCODED)
# ==========================================
SENDER_EMAIL_FIJO = "nomina@trajesespanoles.mx"
EMAIL_PASSWORD = "OTE.R3c1b05"
PASSWORD_ADMIN = "OTE.Admin2026"

# Sobrescribir con secrets si existen
if "email_password" in st.secrets:
    EMAIL_PASSWORD = st.secrets["email_password"]
    PASSWORD_ADMIN = st.secrets.get("admin_password", PASSWORD_ADMIN)

SERVIDOR_SMTP = "smtp.ionos.com"
PUERTO_SMTP = 587
# ==========================================

# --- FUNCIONES DE LIMPIEZA ---
def limpiar_texto_seguro(texto):
    """Elimina todo lo que no sea A-Z o 0-9"""
    if not isinstance(texto, str): return "DOC"
    # Convertimos a mayusculas y reemplazamos Ñ por N a la fuerza
    texto = texto.upper().replace("\u00D1", "N").replace("Ñ", "N")
    return re.sub(r'[^A-Z0-9]', '', texto)

# --- FUNCION DE ENVIO BLINDADA ---
def enviar_correo_nuclear(correo_destino, ruta_pdf, rfc_empleado):
    # 1. Preparar datos 100% seguros
    rfc_limpio = limpiar_texto_seguro(rfc_empleado)
    nombre_archivo_seguro = "Recibo_Nomina.pdf" # Nombre genérico para evitar errores

    # Validar destino
    if not correo_destino or "@" not in str(correo_destino):
        destinatario_final = SENDER_EMAIL_FIJO
        es_aviso = True
    else:
        destinatario_final = str(correo_destino).strip()
        es_aviso = False

    try:
        msg = MIMEMultipart()
        
        # --- ENCABEZADOS (HEADERS) ---
        # Remitente LIMPIO (Solo correo, sin nombre)
        msg['From'] = SENDER_EMAIL_FIJO 
        
        # Asunto con Header object para evitar error ASCII
        asunto = f"Recibo Nomina - {rfc_limpio}"
        msg['Subject'] = Header(asunto, 'utf-8')
        
        msg['To'] = destinatario_final
        msg['Cc'] = SENDER_EMAIL_FIJO

        # Cuerpo del mensaje
        if es_aviso:
            texto_cuerpo = f"AVISO DE SISTEMA: El empleado {rfc_limpio} firmo su recibo (No tiene correo registrado)."
        else:
            texto_cuerpo = f"""Estimado colaborador,

Adjuntamos su recibo de nomina firmado.
RFC: {rfc_limpio}

Atte.
Operadora de Trajes Espanoles
"""

        # Adjuntamos texto UTF-8
        msg.attach(MIMEText(texto_cuerpo, 'plain', 'utf-8'))

        # Adjuntamos PDF
        with open(ruta_pdf, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        
        # Header del adjunto seguro
        part.add_header('Content-Disposition', 'attachment', filename=nombre_archivo_seguro)
        msg.attach(part)

        # Conexión SMTP
        server = smtplib.SMTP(SERVIDOR_SMTP, PUERTO_SMTP)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SENDER_EMAIL_FIJO, EMAIL_PASSWORD)
        
        # Envio real
        destinatarios = [destinatario_final, SENDER_EMAIL_FIJO]
        server.sendmail(SENDER_EMAIL_FIJO, destinatarios, msg.as_string())
        server.quit()
        
        return True, "Enviado con exito"

    except Exception as e:
        return False, f"ERROR CRITICO: {str(e)}"

# --- OTRAS FUNCIONES ---
def buscar_archivo(u_file, u_rfc):
    if os.path.exists(f"recibos/{u_file}"): return f"recibos/{u_file}"
    files = glob.glob(f"recibos/*{u_rfc}*.pdf")
    return files[0] if files else None

def firmar_pdf(ruta_orig, firma_bytes):
    try:
        packet = io.BytesIO()
        can = pdf_canvas.Canvas(packet, pagesize=letter)
        img = Image.fromarray(firma_bytes.astype('uint8'), 'RGBA')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        can.drawImage(ImageReader(img_buffer), 460, 300, width=150, height=60, mask='auto')
        can.drawString(470, 290, "Firma Digital")
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
# INTERFAZ DE USUARIO
# ==========================================

# BARRA LATERAL
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=200)
    st.title("OTE")
    
    # Toggle de Admin
    modo_admin_activado = st.toggle("Modo Admin")
    
    # Lógica de Login Admin
    if modo_admin_activado:
        pwd = st.text_input("Password", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("Acceso Admin OK")
        else:
            st.session_state.admin = False
            if pwd: st.error("Password incorrecto")
    else:
        st.session_state.admin = False

# PANTALLA PRINCIPAL
if st.session_state.admin:
    st.header("Panel Admin")
    uploaded = st.file_uploader("Subir Recibos (PDF)", accept_multiple_files=True)
    if st.button("Procesar Archivos"):
        if uploaded:
            if not os.path.exists("recibos"): os.makedirs("recibos")
            db = []
            for f in uploaded:
                with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                db.append(extraer_info_pdf(f))
            pd.DataFrame(db).to_csv("Control_Maestro.csv", index=False)
            st.success("Base de datos actualizada.")
    
    if os.path.exists("Control_Maestro.csv"):
        st.dataframe(pd.read_csv("Control_Maestro.csv"))

else:
    st.header("Portal Empleado")
    
    # LOGIN EMPLEADO
    if not st.session_state.user:
        rfc_input = st.text_input("Ingresa tu RFC").upper()
        if st.button("Buscar Recibo"):
            if os.path.exists("Control_Maestro.csv"):
                df = pd.read_csv("Control_Maestro.csv")
                # Búsqueda exacta
                match = df[df['rfc'] == rfc_input]
                if not match.empty:
                    st.session_state.user = match.iloc[0].to_dict()
                    st.rerun()
                else:
                    st.error("RFC no encontrado en la nómina actual.")
            else:
                st.warning("El sistema aún no tiene datos cargados.")
    else:
        # EMPLEADO LOGUEADO
        u = st.session_state.user
        st.success(f"Bienvenido: {u['name']}")
        
        pdf_path = buscar_archivo(u['file'], u['rfc'])
        
        if pdf_path:
            with open(pdf_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            
            # Visor
            st.markdown(f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="600"></iframe>', unsafe_allow_html=True)
            
            # Firma
            st.write("---")
            st.write("Firma aqui:")
            canvas = st_canvas(stroke_width=2, height=150, key="canvas")
            
            if st.button("Firmar y Enviar"):
                if canvas.image_data is not None:
                    path_firmado = firmar_pdf(pdf_path, canvas.image_data)
                    if path_firmado:
                        # Buscar correo en directorio
                        email_personal = None
                        if os.path.exists("Directorio_Contactos.csv"):
                            dfc = pd.read_csv("Directorio_Contactos.csv")
                            match_c = dfc[dfc['rfc'] == u['rfc']]
                            if not match_c.empty: email_personal = match_c.iloc[0]['email']
                        
                        # ENVIO NUCLEAR
                        ok, msg = enviar_correo_nuclear(email_personal, path_firmado, u['rfc'])
                        
                        if ok:
                            st.success("✅ Enviado correctamente!")
                            st.balloons()
                        else:
                            st.error(msg)
        else:
            st.warning("No se encuentra el archivo PDF físico.")
        
        st.write("---")
        # Configurar correo
        with st.expander("Configurar mi Correo"):
            new_email = st.text_input("Nuevo Correo")
            if st.button("Guardar"):
                if "@" in new_email:
                    file_c = "Directorio_Contactos.csv"
                    if not os.path.exists(file_c): 
                        pd.DataFrame(columns=['rfc','email']).to_csv(file_c, index=False)
                    dfc = pd.read_csv(file_c)
                    dfc = dfc[dfc['rfc'] != u['rfc']]
                    nuevo = pd.DataFrame([{'rfc': u['rfc'], 'email': new_email}])
                    pd.concat([dfc, nuevo]).to_csv(file_c, index=False)
                    st.success("Guardado")
                    st.rerun()
        
        if st.button("Salir"):
            st.session_state.user = None
            st.rerun()