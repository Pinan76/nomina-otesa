# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import base64
import os
import re
import glob
import smtplib
import io
# Librería moderna para manejo automático de codificación
from email.message import EmailMessage
from pypdf import PdfReader, PdfWriter
from streamlit_drawable_canvas import st_canvas
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image

# --- 1. CONFIGURACION DE PAGINA ---
st.set_page_config(page_title="Nexus - OTE", layout="wide", page_icon=":necktie:")

# --- 2. INICIALIZACION DE ESTADO ---
if 'admin' not in st.session_state: st.session_state.admin = False
if 'user' not in st.session_state: st.session_state.user = None
if 'autenticado' not in st.session_state: st.session_state.autenticado = False

# ==========================================
# 🛑 ZONA BLINDADA (BYPASS DE SECRETS)
# ==========================================
# Escribimos las credenciales DIRECTAMENTE aquí para evitar que
# el archivo de configuración de la nube meta basura o caracteres raros.

SENDER_EMAIL = "nomina@trajesespanoles.mx"
EMAIL_PASSWORD = "OTE.R3c1b05"  # <--- CONTRASEÑA CORRECTA Y CORTA (SIN Ñ)
PASSWORD_ADMIN = "OTE.Admin2026"

SERVIDOR_SMTP = "smtp.ionos.com"
PUERTO_SMTP = 587
# ==========================================

# --- FUNCION DE LIMPIEZA TOTAL ---
def limpiar_todo(texto):
    """Deja solo letras y números. Convierte Ñ->N."""
    if not isinstance(texto, str): return "DOC"
    # Mapa de reemplazo manual
    mapa = {"Ñ":"N", "ñ":"n", "Á":"A", "É":"E", "Í":"I", "Ó":"O", "Ú":"U", "á":"a", "é":"e", "í":"i", "ó":"o", "ú":"u"}
    texto_limpio = texto.upper()
    for k, v in mapa.items():
        texto_limpio = texto_limpio.replace(k, v)
    return re.sub(r'[^A-Z0-9]', '', texto_limpio)

# --- FUNCION DE ENVIO DEFINITIVA ---
def enviar_correo_final(correo_destino, ruta_pdf, rfc_empleado):
    # 1. Limpieza de datos
    rfc_safe = limpiar_todo(rfc_empleado)
    nombre_archivo = "Recibo_Nomina.pdf" # Nombre genérico seguro
    
    # 2. Validar destino
    if correo_destino and "@" in str(correo_destino):
        destinatario = str(correo_destino).strip()
    else:
        destinatario = SENDER_EMAIL # Se envía a sí mismo si no hay correo
    
    # DEBUG EN PANTALLA (Para ver qué contraseña se está usando realmente)
    st.caption(f"⚙️ Debug: Usando cuenta {SENDER_EMAIL} (Pass len: {len(EMAIL_PASSWORD)})")

    try:
        # Creación del mensaje con EmailMessage (Maneja UTF-8 nativo)
        msg = EmailMessage()
        msg['Subject'] = f"Recibo Nomina - {rfc_safe}"
        msg['From'] = SENDER_EMAIL
        msg['To'] = destinatario
        msg['Cc'] = SENDER_EMAIL

        # Cuerpo del mensaje
        cuerpo = f"""Estimado colaborador,

Adjuntamos su recibo de nomina correspondiente.
RFC Referencia: {rfc_safe}

Atte.
RRHH - Operadora de Trajes Espanoles
"""
        msg.set_content(cuerpo)

        # Adjunto
        with open(ruta_pdf, 'rb') as f:
            file_data = f.read()
            msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=nombre_archivo)

        # CONEXIÓN Y ENVÍO
        server = smtplib.SMTP(SERVIDOR_SMTP, PUERTO_SMTP)
        server.ehlo()
        server.starttls()
        server.ehlo()
        
        # LOGIN (Aquí fallaba antes por leer la contraseña incorrecta)
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        
        server.send_message(msg)
        server.quit()
        
        return True, "Enviado con éxito"

    except Exception as e:
        return False, f"ERROR TÉCNICO: {str(e)}"

# --- FUNCIONES AUXILIARES ---
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
# INTERFAZ
# ==========================================
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=200)
    st.title("OTE V13.0")
    
    modo_admin_activado = st.toggle("Modo Admin")
    if modo_admin_activado:
        pwd = st.text_input("Password", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("Acceso OK")
        else:
            st.session_state.admin = False
            if pwd: st.error("Error")
    else: st.session_state.admin = False

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
                else: st.error("RFC no encontrado.")
            else: st.warning("Sistema vacío.")
    else:
        u = st.session_state.user
        st.success(f"Hola: {u['name']}")
        pdf_path = buscar_archivo(u['file'], u['rfc'])
        
        if pdf_path:
            with open(pdf_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            
            # VISOR PDF MEJORADO
            st.markdown(f'<object data="data:application/pdf;base64,{b64}" type="application/pdf" width="100%" height="600px"><p>Descarga abajo.</p></object>', unsafe_allow_html=True)
            
            st.write("---")
            st.write("Firma aquí:")
            canvas = st_canvas(stroke_width=2, height=150, key="canvas")
            
            if st.button("Firmar y Enviar"):
                if canvas.image_data is not None:
                    path_firmado = firmar_pdf(pdf_path, canvas.image_data)
                    if path_firmado:
                        email_p = None
                        if os.path.exists("Directorio_Contactos.csv"):
                            dfc = pd.read_csv("Directorio_Contactos.csv")
                            match_c = dfc[dfc['rfc'] == u['rfc']]
                            if not match_c.empty: email_p = match_c.iloc[0]['email']
                        
                        # ENVIO
                        ok, msg = enviar_correo_final(email_p, path_firmado, u['rfc'])
                        if ok:
                            st.success("Enviado correctamente!")
                            st.balloons()
                        else: st.error(msg)
        else: st.warning("PDF no encontrado.")
        
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