# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import base64
import os
import re
import glob
import smtplib
import io
# Usamos libreria estandar robusta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pypdf import PdfReader, PdfWriter
from streamlit_drawable_canvas import st_canvas
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image

# --- 1. CONFIGURACION DE PAGINA ---
st.set_page_config(page_title="Nexus - OTE", layout="wide", page_icon=":necktie:")

# --- 2. INICIALIZACION DE ESTADO (CRITICO: SIEMPRE AL PRINCIPIO) ---
if 'admin' not in st.session_state: st.session_state.admin = False
if 'user' not in st.session_state: st.session_state.user = None
if 'autenticado' not in st.session_state: st.session_state.autenticado = False

# ==========================================
# 🔧 CONFIGURACION SEGURA
# ==========================================
SENDER_EMAIL = "nomina@trajesespanoles.mx" # SIN NOMBRE, SOLO CORREO
EMAIL_PASSWORD = "OTE.R3c1b05"
PASSWORD_ADMIN = "OTE.Admin2026"

if "email_password" in st.secrets:
    EMAIL_PASSWORD = st.secrets["email_password"]
    PASSWORD_ADMIN = st.secrets.get("admin_password", PASSWORD_ADMIN)

SERVIDOR_SMTP = "smtp.ionos.com"
PUERTO_SMTP = 587
# ==========================================

# --- FUNCION DE ENVIO 'A PRUEBA DE BALAS' ---
def enviar_correo_final(correo_destino, ruta_pdf, rfc_empleado):
    # Validar correo destino
    destinatario = SENDER_EMAIL
    if correo_destino and "@" in str(correo_destino):
        destinatario = str(correo_destino).strip()

    try:
        msg = MIMEMultipart()
        
        # --- ELIMINACION DE CARACTERES ILEGALES ---
        # 1. REMITENTE: Solo el correo, nada de "Operadora..."
        msg['From'] = SENDER_EMAIL 
        
        # 2. ASUNTO: Texto plano en Ingles/Espanol simple sin variables
        # (Aqui solia estar el error si el RFC tenia Ñ)
        msg['Subject'] = "Recibo de Nomina - Documento Firmado"
        
        msg['To'] = destinatario
        msg['Cc'] = SENDER_EMAIL

        # 3. CUERPO (Aqui SI podemos poner Ñ y acentos)
        rfc_limpio = rfc_empleado.replace("Ñ", "N")
        cuerpo = f"""Estimado colaborador,

Adjuntamos su recibo de nomina firmado correctamente.
RFC Referencia: {rfc_limpio}

Atentamente,
RRHH - Operadora de Trajes Espanoles
"""
        msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))

        # 4. ADJUNTO (Nombre generico para evitar error de codificacion)
        with open(ruta_pdf, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        
        # NOMBRE DE ARCHIVO SEGURO (Sin variables)
        part.add_header('Content-Disposition', 'attachment', filename="Recibo_Nomina_Firmado.pdf")
        msg.attach(part)

        # 5. CONEXION Y ENVIO
        server = smtplib.SMTP(SERVIDOR_SMTP, PUERTO_SMTP)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        
        destinatarios_lista = [destinatario, SENDER_EMAIL]
        server.sendmail(SENDER_EMAIL, destinatarios_lista, msg.as_string())
        server.quit()
        
        return True, "Enviado con exito"

    except Exception as e:
        return False, f"ERROR CRITICO: {str(e)}"

# --- FUNCIONES DE PDF ---
def buscar_archivo(u_file, u_rfc):
    # Intenta ruta directa
    if os.path.exists(f"recibos/{u_file}"): return f"recibos/{u_file}"
    # Intenta buscar por RFC
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
    
    # Toggle Admin
    modo_admin_activado = st.toggle("Modo Admin")
    
    if modo_admin_activado:
        pwd = st.text_input("Password", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("Acceso OK")
        else:
            st.session_state.admin = False
            if pwd: st.error("Error")
    else:
        st.session_state.admin = False

# PANEL PRINCIPAL
if st.session_state.admin:
    st.header("Panel Admin")
    uploaded = st.file_uploader("Subir Recibos", accept_multiple_files=True)
    if st.button("Procesar"):
        if uploaded:
            if not os.path.exists("recibos"): os.makedirs("recibos")
            db = []
            for f in uploaded:
                with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                db.append(extraer_info_pdf(f))
            pd.DataFrame(db).to_csv("Control_Maestro.csv", index=False)
            st.success("Cargado.")
    
    if os.path.exists("Control_Maestro.csv"):
        st.dataframe(pd.read_csv("Control_Maestro.csv"))

else:
    st.header("Portal Empleado")
    
    if not st.session_state.user:
        rfc_input = st.text_input("Ingresa tu RFC").upper()
        if st.button("Buscar"):
            if os.path.exists("Control_Maestro.csv"):
                df = pd.read_csv("Control_Maestro.csv")
                match = df[df['rfc'] == rfc_input]
                if not match.empty:
                    st.session_state.user = match.iloc[0].to_dict()
                    st.rerun()
                else:
                    st.error("RFC no encontrado.")
            else:
                st.warning("Sistema vacio.")
    else:
        u = st.session_state.user
        st.success(f"Hola: {u['name']}")
        
        pdf_path = buscar_archivo(u['file'], u['rfc'])
        
        if pdf_path:
            with open(pdf_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            
            # VISOR PDF (Usa <object> para mayor compatibilidad)
            st.markdown(f'<object data="data:application/pdf;base64,{b64}" type="application/pdf" width="100%" height="600px"><p>Descarga el PDF abajo.</p></object>', unsafe_allow_html=True)
            
            st.write("---")
            st.write("Firma aqui:")
            canvas = st_canvas(stroke_width=2, height=150, key="canvas")
            
            if st.button("Firmar y Enviar"):
                if canvas.image_data is not None:
                    path_firmado = firmar_pdf(pdf_path, canvas.image_data)
                    if path_firmado:
                        email_personal = None
                        if os.path.exists("Directorio_Contactos.csv"):
                            dfc = pd.read_csv("Directorio_Contactos.csv")
                            match_c = dfc[dfc['rfc'] == u['rfc']]
                            if not match_c.empty: email_personal = match_c.iloc[0]['email']
                        
                        # ENVIO FINAL
                        ok, msg = enviar_correo_final(email_personal, path_firmado, u['rfc'])
                        
                        if ok:
                            st.success("Enviado correctamente!")
                            st.balloons()
                        else:
                            st.error(msg)
                            st.write("Nota: El error 38 suele ser por caracteres especiales en el Asunto o Nombre de archivo. Hemos forzado nombres genericos para solucionarlo.")
        else:
            st.warning("PDF no encontrado.")
        
        st.write("---")
        with st.expander("Configurar Correo"):
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