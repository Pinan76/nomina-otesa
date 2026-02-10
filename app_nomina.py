# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import base64
import os
import re
import glob
import smtplib
import io
# CAMBIO DE TECNOLOGÍA: Usamos la librería moderna que gestiona UTF-8 automático
from email.message import EmailMessage
from pypdf import PdfReader, PdfWriter
from streamlit_drawable_canvas import st_canvas
from datetime import datetime
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image

# --- CONFIGURACIÓN DE PÁGINA ---
# Usamos el shortcode :necktie: para evitar errores de iconos
st.set_page_config(page_title="Nexus - OTE", layout="wide", page_icon=":necktie:")

# ==========================================
# 📧 CONFIGURACIÓN
# ==========================================
# Solo leemos contraseñas de los secrets. El correo lo definimos FIJO abajo.
EMAIL_PASSWORD = "OTE.R3c1b05"
PASSWORD_ADMIN = "OTE.Admin2026"

if "email_password" in st.secrets:
    EMAIL_PASSWORD = st.secrets["email_password"]
    PASSWORD_ADMIN = st.secrets.get("admin_password", PASSWORD_ADMIN)

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
    st.write("Configuración")
    modo_admin = st.toggle("Soy Administrador")
    
    acceso_concedido = False
    if modo_admin:
        pass_input = st.text_input("Clave RRHH", type="password")
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

def limpieza_absoluta(texto):
    """
    Función de limpieza agresiva para nombres de archivo.
    Solo permite letras A-Z y números.
    """
    if not isinstance(texto, str): return "DOC"
    # Reemplazos manuales
    texto = texto.upper().replace("Ñ", "N")
    # Regex final: Solo A-Z y 0-9
    return re.sub(r'[^A-Z0-9]', '', texto)

def buscar_archivo_inteligente(nombre_archivo_csv, rfc):
    ruta_exacta = os.path.join("recibos", nombre_archivo_csv)
    if os.path.exists(ruta_exacta): return ruta_exacta
    if not os.path.exists("recibos"): return None
    patron = os.path.join("recibos", f"*{rfc}*.pdf")
    coincidencias = glob.glob(patron)
    if coincidencias: return coincidencias[0]
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

def enviar_correo_moderno(correo_empleado, ruta_pdf, nombre_empleado, rfc_empleado):
    # 1. Definimos el remitente AQUÍ DENTRO (Hardcoded para evitar errores externos)
    REMITENTE_SEGURO = "nomina@trajesespanoles.mx"
    
    # 2. Limpieza de datos
    rfc_safe = limpieza_absoluta(rfc_empleado)
    nombre_archivo = f"Recibo_{rfc_safe}.pdf"
    
    email_destino = None
    if correo_empleado and "@" in str(correo_empleado):
        email_destino = str(correo_empleado).strip()

    try:
        # 3. USAMOS LA LIBRERÍA MODERNA (EmailMessage)
        # Esta librería maneja UTF-8 automáticamente, adiós al error ASCII.
        msg = EmailMessage()
        msg['Subject'] = f"Recibo Nomina - {rfc_safe}"
        msg['From'] = REMITENTE_SEGURO
        
        cuerpo = ""
        
        if email_destino:
            msg['To'] = email_destino
            msg['Cc'] = REMITENTE_SEGURO
            
            # Texto del cuerpo
            cuerpo = f"""Estimado colaborador,

Adjunto enviamos tu recibo de nomina firmado.
RFC: {rfc_safe}

Atte.
Operadora de Trajes Espanoles (RRHH)
"""
        else:
            msg['To'] = REMITENTE_SEGURO
            cuerpo = f"AVISO: El empleado {rfc_safe} firmo el recibo (sin correo personal)."
        
        # Establecemos el contenido (UTF-8 es automático aquí)
        msg.set_content(cuerpo)

        # 4. Adjuntamos el PDF
        with open(ruta_pdf, 'rb') as f:
            file_data = f.read()
            # Esta función maneja la codificación del adjunto sola
            msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=nombre_archivo)

        # 5. Envío
        with smtplib.SMTP(SERVIDOR_SMTP, PUERTO_SMTP) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(REMITENTE_SEGURO, EMAIL_PASSWORD)
            server.send_message(msg) # send_message es más inteligente que sendmail
            
        return True, "Enviado correctamente"
    
    except Exception as e:
        return False, f"Error Tecnico: {str(e)}"

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
    def limpiar_basico(t): return t.replace('\n', ' ').strip()
    try:
        reader = PdfReader(pdf_file)
        texto = "".join([page.extract_text() for page in reader.pages])
        # Regex simplificado
        match = re.search(r'[A-Z]\d{5}\s*[-]?\s*([A-Z\s]+)', texto) 
        nombre = limpiar_basico(match.group(1)) if match else pdf_file.name.replace(".pdf", "")
        match_rfc = re.search(r'RFC:\s*([A-Z]{4}\d{6}[A-Z0-9]{3})', texto)
        rfc = match_rfc.group(1) if match_rfc else "N/A"
        return {"file": pdf_file.name, "name": nombre, "rfc": rfc}
    except: return {"file": pdf_file.name, "name": "Error Lectura", "rfc": "N/A"}

# --- 4. INTERFAZ PRINCIPAL ---

st.title("Operadora de Trajes Espanoles")
st.caption("Sistema Nexus - Nomina Digital")

if acceso_concedido:
    tab1, tab2 = st.tabs(["Portal Empleado", "Panel RRHH"])
else:
    tab1, = st.tabs(["Portal Empleado"])
    tab2 = None

# --- PESTAÑA 1: EMPLEADO ---
with tab1:
    if not st.session_state.autenticado:
        st.subheader("Acceso Personal")
        rfc_in = st.text_input("Ingresa tu RFC").upper()
        
        if rfc_in and os.path.exists('Control_Maestro.csv'):
            df_m = pd.read_csv('Control_Maestro.csv')
            emp = df_m[df_m['rfc'] == rfc_in]
            
            if not emp.empty:
                e = emp.iloc[0]
                st.info(f"Colaborador: **{e['name']}**")
                
                if not gestionar_credenciales(rfc_in):
                    p1 = st.text_input("Crear Password", type="password")
                    if st.button("Registrar"):
                        gestionar_credenciales(rfc_in, p1, "registro")
                        st.session_state.autenticado = True; st.session_state.rfc_actual = rfc_in; st.session_state.user_data = e; st.rerun()
                else:
                    p_log = st.text_input("Password", type="password")
                    if st.button("Entrar"):
                        if gestionar_credenciales(rfc_in, p_log, "login"):
                            st.session_state.autenticado = True; st.session_state.rfc_actual = rfc_in; st.session_state.user_data = e; st.rerun()
                        else: st.error("Clave incorrecta")
            else: st.warning("RFC no encontrado en base de datos.")
        elif rfc_in:
            st.error("Esperando carga de base de datos...")
            
    else:
        u = st.session_state.user_data
        st.success(f"Bienvenido: {u['name']}")
        c_izq, c_der = st.columns([2, 1])
        
        with c_izq:
            st.subheader("Tu Recibo")
            archivo_encontrado = buscar_archivo_inteligente(u['file'], u['rfc'])
            
            if archivo_encontrado:
                with open(archivo_encontrado, "rb") as f:
                    pdf_bytes = f.read()
                    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')

                st.markdown(f"**Visualizando archivo:** `{os.path.basename(archivo_encontrado)}`")
                
                # VISOR COMPATIBLE
                pdf_display = f'<object data="data:application/pdf;base64,{base64_pdf}" type="application/pdf" width="100%" height="800px"><p>Tu navegador no muestra PDFs. <a href="data:application/pdf;base64,{base64_pdf}" download>Descargalo aqui</a>.</p></object>'
                st.markdown(pdf_display, unsafe_allow_html=True)
                
                st.download_button(
                    label="DESCARGAR PDF",
                    data=pdf_bytes,
                    file_name=os.path.basename(archivo_encontrado),
                    mime="application/pdf",
                    use_container_width=True
                )
                
                st.write("---")
                st.write("**Firma Digital:**")
                canvas = st_canvas(stroke_width=2, height=150, key="f")
                
                if st.button("Firmar y Enviar"):
                    if canvas.image_data is not None:
                        with st.spinner("Procesando firma..."):
                            ruta_firmado = generar_pdf_firmado(archivo_encontrado, canvas.image_data)
                            if ruta_firmado:
                                registrar_firma(st.session_state.rfc_actual, os.path.basename(ruta_firmado))
                                correo_empleado = None
                                if os.path.exists('Directorio_Contactos.csv'):
                                    df_c = pd.read_csv('Directorio_Contactos.csv')
                                    match = df_c[df_c['rfc'] == st.session_state.rfc_actual]
                                    if not match.empty: correo_empleado = match.iloc[0]['email']
                                
                                # FUNCIÓN MODERNA
                                exito, msg = enviar_correo_moderno(correo_empleado, ruta_firmado, u['name'], u['rfc'])
                                
                                if exito:
                                    st.success("Listo! Recibo firmado enviado.")
                                    st.balloons()
                                else: st.error(f"Error envio: {msg}")
            else: 
                st.error("Archivo PDF no encontrado.")
                st.warning(f"Buscamos: {u['file']} o el RFC {u['rfc']}")
        
        with c_der:
            with st.expander("Configuracion", expanded=True):
                nc = st.text_input("Correo Personal")
                if st.button("Guardar Email"):
                    if es_correo_valido(nc):
                        guardar_contacto(st.session_state.rfc_actual, nc)
                        st.success("Guardado.")
                        st.rerun()
            if st.button("Salir"): st.session_state.autenticado = False; st.rerun()

# --- PESTAÑA 2: ADMIN ---
if acceso_concedido and tab2:
    with tab2:
        st.header("Panel Administrativo")
        
        with st.expander("Explorador de Archivos (DEBUG)", expanded=False):
            st.write("Archivos guardados actualmente:")
            if os.path.exists("recibos"):
                archivos_en_nube = os.listdir("recibos")
                if archivos_en_nube: st.write(archivos_en_nube)
                else: st.warning("Carpeta vacia.")
            else: st.error("Carpeta no existe.")

        if os.path.exists('Control_Maestro.csv'):
            df_m = pd.read_csv('Control_Maestro.csv')
            df_firmas = pd.read_csv('Estado_Firmas.csv') if os.path.exists('Estado_Firmas.csv') else pd.DataFrame(columns=['rfc'])
            firmados = df_m['rfc'].isin(df_firmas['rfc']).sum()
            c1, c2 = st.columns(2)
            c1.metric("Empleados Cargados", len(df_m)); c2.metric("Firmas Recibidas", firmados)
            
            st.subheader("Estado de Firmas")
            df_status = df_m[['name', 'rfc']].copy()
            df_status['Firmado'] = df_status['rfc'].isin(df_firmas['rfc']).map({True: 'SI', False: 'NO'})
            def color_rojo(val): return f'color: {"red" if val == "NO" else "green"}'
            st.dataframe(df_status.style.applymap(color_rojo, subset=['Firmado']), use_container_width=True)

        st.write("---")
        st.subheader("Carga de Nomina")
        uploaded = st.file_uploader("Subir PDFs Semanales", accept_multiple_files=True)
        
        if st.button("Procesar Archivos"):
            if uploaded:
                if not os.path.exists("recibos"): os.makedirs("recibos")
                datos = []
                for f in uploaded:
                    try:
                        with open(os.path.join("recibos", f.name), "wb") as out: out.write(f.getbuffer())
                        datos.append(extraer_datos_limpios(f))
                    except: pass
                if datos:
                    if os.path.exists('Control_Maestro.csv'):
                        df_ex = pd.read_csv('Control_Maestro.csv')
                        df_fin = pd.concat([df_ex, pd.DataFrame(datos)]).drop_duplicates(subset=['rfc'], keep='last')
                    else: df_fin = pd.DataFrame(datos)
                    df_fin.to_csv('Control_Maestro.csv', index=False)
                    st.success(f"Se cargaron {len(datos)} empleados.")
                    st.rerun()