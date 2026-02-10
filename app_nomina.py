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
st.set_page_config(page_title="Nexus - OTE", layout="wide", page_icon=":necktie:")

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
    return pd.read_csv('Bitacora_Firmas.csv')

def registrar_firma_db(rfc, nombre_archivo):
    df = cargar_db_firmas()
    # Verificar si ya existe para no duplicar
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
    # 1. Listar todos los archivos físicos (Lo que se debe firmar)
    archivos_fisicos = []
    if os.path.exists("recibos"):
        for f in os.listdir("recibos"):
            if f.endswith(".pdf"):
                # Extraer RFC del nombre del archivo (suponiendo estructura RE_Semana_RFC.pdf)
                # O buscamos dentro del archivo si el nombre no ayuda
                archivos_fisicos.append(f)
    
    df_archivos = pd.DataFrame(archivos_fisicos, columns=['Archivo'])
    
    # 2. Listar lo firmado
    df_firmados = cargar_db_firmas()
    
    # 3. Cruzar información
    # Marcamos como firmado si el archivo está en la bitácora
    df_status = df_archivos.copy()
    df_status['Firmado'] = df_status['Archivo'].isin(df_firmados['Archivo'])
    
    return df_status

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
    """Busca TODOS los recibos coincidentes con el RFC"""
    if not os.path.exists("recibos"): return []
    patron = f"recibos/*{rfc}*.pdf"
    rutas = glob.glob(patron)
    # Retornamos solo los nombres de archivo, ordenados del mas nuevo al mas viejo
    archivos = [os.path.basename(r) for r in rutas]
    archivos.sort(reverse=True) 
    return archivos

def firmar_pdf(ruta_orig, firma_bytes):
    try:
        packet = io.BytesIO()
        can = pdf_canvas.Canvas(packet, pagesize=letter)
        img = Image.fromarray(firma_bytes.astype('uint8'), 'RGBA')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        can.drawImage(ImageReader(img_buffer), 400, 300, width=150, height=60, mask='auto')
        can.drawString(356, 290, "Firma Digital") # Posicion ajustada
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
    if not os.path.exists(file_cred): pd.DataFrame(columns=['rfc', 'password']).to_csv(file_cred, index=False)
    df = pd.read_csv(file_cred)
    if modo == "verificar": return not df[df['rfc'] == rfc].empty
    if modo == "login": return not df[(df['rfc'] == rfc) & (df['password'] == password_input)].empty
    if modo == "registro":
        df = pd.concat([df, pd.DataFrame([{'rfc': rfc, 'password': password_input}])], ignore_index=True)
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
    if os.path.exists("logo.png"): st.image("logo.png", width=200)
    st.title("OTE V19.0")
    
    if st.toggle("Modo Admin"):
        pwd = st.text_input("Password Admin", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("OK")
        else:
            st.session_state.admin = False
    else: st.session_state.admin = False

# --- VISTA ADMIN (TABLERO DE CONTROL) ---
if st.session_state.admin:
    st.title("📊 Tablero de Control RRHH")
    
    tab1, tab2, tab3 = st.tabs(["📂 Cargar Nómina", "🚨 Pendientes de Firma", "📨 Bitácora"])
    
    with tab1:
        uploaded = st.file_uploader("Subir PDFs", accept_multiple_files=True)
        if st.button("Procesar"):
            if uploaded:
                if not os.path.exists("recibos"): os.makedirs("recibos")
                db = []
                for f in uploaded:
                    with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                    db.append(extraer_info_pdf(f))
                pd.DataFrame(db).to_csv("Control_Maestro.csv", index=False)
                st.success(f"Procesados {len(db)} archivos.")

    with tab2:
        st.subheader("Estado de Cumplimiento")
        df_status = obtener_status_global()
        
        if not df_status.empty:
            # Metricas
            total = len(df_status)
            firmados = df_status['Firmado'].sum()
            pendientes = total - firmados
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Recibos", total)
            c2.metric("Firmados", firmados)
            c3.metric("Pendientes", pendientes, delta_color="inverse")
            
            st.write("---")
            
            # Filtro de pendientes
            df_pendientes = df_status[df_status['Firmado'] == False].reset_index(drop=True)
            
            if not df_pendientes.empty:
                st.error(f"⚠️ Hay {len(df_pendientes)} recibos sin firmar.")
                st.dataframe(df_pendientes, use_container_width=True)
                
                st.write("#### Acciones")
                # Selector para enviar recordatorio
                archivo_a_recordar = st.selectbox("Seleccionar Archivo para Recordatorio", df_pendientes['Archivo'])
                
                if st.button("📢 Enviar Recordatorio al Empleado"):
                    # Intentamos extraer el RFC del nombre del archivo o de la base maestra
                    # Suponemos que tenemos Control_Maestro para buscar el RFC del archivo
                    rfc_destino = "DESCONOCIDO"
                    if os.path.exists("Control_Maestro.csv"):
                        df_m = pd.read_csv("Control_Maestro.csv")
                        match = df_m[df_m['file'] == archivo_a_recordar]
                        if not match.empty: rfc_destino = match.iloc[0]['rfc']
                    
                    # Buscar correo
                    email_destino = None
                    if os.path.exists("Directorio_Contactos.csv"):
                        df_c = pd.read_csv("Directorio_Contactos.csv")
                        match_c = df_c[df_c['rfc'] == rfc_destino]
                        if not match_c.empty: email_destino = match_c.iloc[0]['email']
                    
                    if email_destino:
                        cuerpo_alerta = f"Estimado colaborador,\n\nDetectamos que no ha firmado su recibo: {archivo_a_recordar}.\nPor favor ingrese al portal Nexus para firmarlo lo antes posible.\n\nAtte. RRHH"
                        ok, msg = enviar_correo_general(email_destino, "ALERTA: Recibo Pendiente", cuerpo_alerta)
                        if ok: st.success(f"Recordatorio enviado a {email_destino}")
                        else: st.error(f"Error enviando: {msg}")
                    else:
                        st.warning(f"El empleado con RFC {rfc_destino} no tiene correo registrado.")
            else:
                st.success("✅ ¡Todo al día! No hay pendientes.")
                
    with tab3:
        if os.path.exists("Bitacora_Firmas.csv"):
            st.dataframe(pd.read_csv("Bitacora_Firmas.csv"), use_container_width=True)

# --- VISTA EMPLEADO ---
else:
    st.header("Portal Empleado")
    
    if not st.session_state.user:
        rfc_input = st.text_input("Ingresa tu RFC").upper()
        if rfc_input:
            if os.path.exists("Control_Maestro.csv"):
                df_maestro = pd.read_csv("Control_Maestro.csv")
                # Verificamos si el RFC existe en CUALQUIER registro
                if rfc_input in df_maestro['rfc'].values:
                    # Lógica de Login
                    if gestion_credenciales(rfc_input, modo="verificar"):
                        st.info("Usuario detectado.")
                        pwd = st.text_input("Contraseña", type="password")
                        if st.button("Entrar"):
                            if gestionar_credenciales(rfc_input, pwd, modo="login"):
                                st.session_state.user = {'rfc': rfc_input, 'name': 'Colaborador'} # Simplificado
                                st.rerun()
                            else: st.error("Contraseña incorrecta")
                    else:
                        st.warning("Crea tu contraseña.")
                        new_p = st.text_input("Nueva Contraseña", type="password")
                        if st.button("Registrar"):
                            gestionar_credenciales(rfc_input, new_p, modo="registro")
                            st.session_state.user = {'rfc': rfc_input, 'name': 'Colaborador'}
                            st.rerun()
                else: st.error("RFC no encontrado.")
    
    else:
        # USUARIO DENTRO
        u = st.session_state.user
        st.success(f"Sesión RFC: {u['rfc']}")
        
        # --- SELECCION DE HISTORIAL ---
        mis_recibos = listar_recibos_empleado(u['rfc'])
        
        if mis_recibos:
            st.info(f"📂 Tienes {len(mis_recibos)} recibos disponibles.")
            
            # SELECTOR DE ARCHIVO
            archivo_seleccionado = st.selectbox("Selecciona el recibo que deseas ver/firmar:", mis_recibos)
            
            pdf_path = os.path.join("recibos", archivo_seleccionado)
            
            # Verificamos si ya está firmado en base de datos
            df_firmas = cargar_db_firmas()
            ya_firmado = ((df_firmas['RFC'] == u['rfc']) & (df_firmas['Archivo'] == archivo_seleccionado)).any()
            
            if ya_firmado:
                st.success("✅ Este recibo YA ESTÁ FIRMADO y enviado.")
            else:
                st.warning("⚠️ Este recibo está PENDIENTE de firma.")

            # VISOR
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            if pdf_viewer: pdf_viewer(input=pdf_bytes, width=700)
            
            # BOTON DE FIRMA (Solo si no está firmado, o permitir refirmar si se desea)
            if not ya_firmado:
                st.write("---")
                st.write("✍️ **Firma Digital:**")
                canvas = st_canvas(stroke_width=2, height=150, key="c")
                
                if st.button("Firmar Documento"):
                    if canvas.image_data is not None:
                        path_firmado = firmar_pdf(pdf_path, canvas.image_data)
                        if path_firmado:
                            # Buscar correo
                            email_p = None
                            if os.path.exists("Directorio_Contactos.csv"):
                                dfc = pd.read_csv("Directorio_Contactos.csv")
                                match = dfc[dfc['rfc'] == u['rfc']]
                                if not match.empty: email_p = match.iloc[0]['email']
                            
                            ok, msg = enviar_correo_general(
                                email_p if email_p else SENDER_EMAIL, 
                                f"Recibo Firmado - {u['rfc']}",
                                "Adjuntamos documento firmado.",
                                path_firmado,
                                "Recibo_Firmado.pdf"
                            )
                            
                            if ok:
                                registrar_firma_db(u['rfc'], archivo_seleccionado)
                                st.success("Firmado y Registrado correctamente.")
                                st.rerun() # Recargar para actualizar estatus
                            else:
                                st.error(f"Error envío: {msg}")
            
            st.download_button("Descargar PDF Original", pdf_bytes, file_name=archivo_seleccionado)

        else:
            st.warning("No se encontraron recibos asociados a tu RFC.")
            
        st.write("---")
        with st.expander("Configurar mi Correo"):
            new_email = st.text_input("Correo Personal")
            if st.button("Actualizar Correo"):
                file_c = "Directorio_Contactos.csv"
                if not os.path.exists(file_c): pd.DataFrame(columns=['rfc','email']).to_csv(file_c, index=False)
                dfc = pd.read_csv(file_c)
                dfc = dfc[dfc['rfc'] != u['rfc']]
                nuevo = pd.DataFrame([{'rfc': u['rfc'], 'email': new_email}])
                pd.concat([dfc, nuevo]).to_csv(file_c, index=False)
                st.success("Guardado")
        
        if st.button("Cerrar Sesión"):
            st.session_state.user = None
            st.rerun()