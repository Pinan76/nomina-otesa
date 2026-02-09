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
from email import encoders
from pypdf import PdfReader, PdfWriter
from streamlit_drawable_canvas import st_canvas
from datetime import datetime
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Nexus - Operadora de Trajes", layout="wide", page_icon="🧵")

# ==========================================
# 📧 CONFIGURACIÓN SEGURA (NUBE + LOCAL)
# ==========================================
if "email_password" in st.secrets:
    EMAIL_PASSWORD = st.secrets["email_password"]
    EMAIL_EMPRESA = st.secrets["email_empresa"]
    PASSWORD_ADMIN = st.secrets["admin_password"]
else:
    EMAIL_EMPRESA = "nomina@trajesespanoles.mx"
    EMAIL_PASSWORD = "OTE.R3c1b05" 
    PASSWORD_ADMIN = "OTE.Admin2026"

SERVIDOR_SMTP = "smtp.ionos.com"
PUERTO_SMTP = 587
# ==========================================

# --- 1. BARRA LATERAL ---
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=200)
    else:
        st.title("OTE")
    
    st.write("---")
    st.write("🔧 **Acceso Administrativo**")
    modo_admin = st.toggle("Soy Administrador")
    
    acceso_concedido = False
    if modo_admin:
        pass_input = st.text_input("Contraseña RRHH", type="password")
        if pass_input == PASSWORD_ADMIN:
            st.success("Acceso Concedido")
            acceso_concedido = True
        elif pass_input:
            st.error("Acceso Denegado")

# --- 2. INICIALIZACIÓN ---
if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False
if 'rfc_actual' not in st.session_state:
    st.session_state.rfc_actual = ""
if 'user_data' not in st.session_state:
    st.session_state.user_data = None

# --- 3. FUNCIONES TÉCNICAS ---

def limpiar_texto(texto):
    if not isinstance(texto, str): return str(texto)
    return texto.replace('\n', ' ').replace('\r', '').strip()

def buscar_archivo_inteligente(nombre_archivo_csv, rfc):
    """
    Estrategia de búsqueda blindada:
    1. Busca por nombre exacto.
    2. Si falla, busca cualquier PDF que tenga el RFC en el nombre.
    """
    # Opción A: Ruta exacta (La más rápida)
    ruta_exacta = os.path.join("recibos", nombre_archivo_csv)
    if os.path.exists(ruta_exacta):
        return ruta_exacta
    
    # Opción B: Búsqueda por RFC (El salvavidas)
    # Busca en la carpeta recibos cualquier archivo que contenga el RFC
    patron = os.path.join("recibos", f"*{rfc}*.pdf")
    coincidencias = glob.glob(patron)
    
    if coincidencias:
        return coincidencias[0] # Retorna el primero que encuentre
    
    return None

def generar_pdf_firmado(ruta_pdf_original, imagen_firma_numpy):
    POSICION_X = 460  
    POSICION_Y = 300 
    try:
        packet = io.BytesIO()
        can = pdf_canvas.Canvas(packet, pagesize=letter)
        img = Image.fromarray(imagen_firma_numpy.astype('uint8'), 'RGBA')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        can.drawImage(ImageReader(img_byte_arr), POSICION_X, POSICION_Y, width=150, height=60, mask='auto')
        can.setFont("Helvetica", 6)
        can.drawString(POSICION_X + 10, POSICION_Y - 10, "Firma Digital Nexus") 
        can.save()
        packet.seek(0)
        new_pdf = PdfReader(packet)
        existing_pdf = PdfReader(open(ruta_pdf_original, "rb"))
        output = PdfWriter()
        page = existing_pdf.pages[0]
        page.merge_page(new_pdf.pages[0])
        output.add_page(page)
        for i in range(1, len(existing_pdf.pages)):
            output.add_page(existing_pdf.pages[i])
        nombre_firmado = ruta_pdf_original.replace(".pdf", "_FIRMADO.pdf")
        with open(nombre_firmado, "wb") as f:
            output.write(f)
        return nombre_firmado
    except Exception as e:
        return None

def enviar_correo_con_copia_obligatoria(correo_empleado, ruta_pdf, nombre_empleado):
    nombre_limpio = limpiar_texto(nombre_empleado)
    nombre_archivo = os.path.basename(ruta_pdf)
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_EMPRESA
        msg['Subject'] = f"Recibo Firmado - {nombre_limpio}"
        destinatarios = []
        cuerpo = ""
        if correo_empleado:
            msg['To'] = correo_empleado
            msg['Cc'] = EMAIL_EMPRESA
            destinatarios = [correo_empleado, EMAIL_EMPRESA]
            cuerpo = f"Estimado/a {nombre_limpio},\n\nSe adjunta tu recibo firmado.\n\nAtte.\nOperadora de Trajes Españoles"
        else:
            msg['To'] = EMAIL_EMPRESA
            destinatarios = [EMAIL_EMPRESA]
            cuerpo = f"AVISO: El empleado {nombre_limpio} firmó (sin correo personal)."

        msg.attach(MIMEText(cuerpo, 'plain'))
        with open(ruta_pdf, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={nombre_archivo}")
        msg.attach(part)

        server = smtplib.SMTP(SERVIDOR_SMTP, PUERTO_SMTP)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL_EMPRESA, EMAIL_PASSWORD)
        server.sendmail(EMAIL_EMPRESA, destinatarios, msg.as_string())
        server.quit()
        return True, "Enviado con documento firmado"
    except Exception as e:
        return False, str(e)

def es_correo_valido(email):
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None

def guardar_contacto(rfc, email):
    file_dir = 'Directorio_Contactos.csv'
    if not os.path.exists(file_dir): pd.DataFrame(columns=['rfc', 'email', 'verificado']).to_csv(file_dir, index=False)
    df = pd.read_csv(file_dir)
    if rfc in df['rfc'].values: df.loc[df['rfc'] == rfc, 'email'] = email
    else: df = pd.concat([df, pd.DataFrame([{'rfc': rfc, 'email': email, 'verificado': True}])])
    df.to_csv(file_dir, index=False)

def registrar_firma(rfc, archivo):
    file_f = 'Estado_Firmas.csv'
    if not os.path.exists(file_f): pd.DataFrame(columns=['rfc', 'archivo', 'fecha']).to_csv(file_f, index=False)
    df = pd.read_csv(file_f)
    if not ((df['rfc'] == rfc) & (df['archivo'] == archivo)).any():
        nuevo = pd.DataFrame([{'rfc': rfc, 'archivo': archivo, 'fecha': datetime.now().strftime("%Y-%m-%d %H:%M")}])
        pd.concat([df, nuevo]).to_csv(file_f, index=False)

def gestionar_credenciales(rfc, password_input=None, modo="verificar"):
    file_cred = 'credenciales.csv'
    if not os.path.exists(file_cred): pd.DataFrame(columns=['rfc', 'password']).to_csv(file_cred, index=False)
    df = pd.read_csv(file_cred)
    if modo == "verificar": return not df[df['rfc'] == rfc].empty
    if modo == "login": return not df[(df['rfc'] == rfc) & (df['password'] == password_input)].empty
    if modo == "registro":
        pd.concat([df, pd.DataFrame([{'rfc': rfc, 'password': password_input}])]).to_csv(file_cred, index=False)

def extraer_datos_limpios(pdf_file):
    try:
        reader = PdfReader(pdf_file)
        texto = "".join([page.extract_text() for page in reader.pages])
        match = re.search(r'[A-Z]\d{5}\s*[-]?\s*([A-ZÁÉÍÓÚÑ\s]+)', texto)
        nombre = limpiar_texto(match.group(1)) if match else pdf_file.name.replace(".pdf", "")
        match_rfc = re.search(r'RFC:\s*([A-Z]{4}\d{6}[A-Z0-9]{3})', texto)
        rfc = match_rfc.group(1) if match_rfc else "N/A"
        return {"file": pdf_file.name, "name": nombre, "rfc": rfc}
    except: return {"file": pdf_file.name, "name": "Error Lectura", "rfc": "N/A"}

# --- 4. INTERFAZ PRINCIPAL ---

st.title("Operadora de Trajes Españoles")
st.caption("Sistema Nexus - Nómina Digital")

if acceso_concedido:
    tab1, tab2 = st.tabs(["👤 Portal Empleado (Vista Previa)", "⚙️ Panel RRHH"])
else:
    tab1, = st.tabs(["👤 Portal Empleado"])
    tab2 = None

# --- PESTAÑA 1: EMPLEADO ---
with tab1:
    if not st.session