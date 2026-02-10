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
        return df
    return pd.read_csv('Bitacora_Firmas.csv')

def registrar_firma_db(rfc, nombre_archivo_relativo):
    df = cargar_db_firmas()
    # nombre_archivo_relativo vendrá como "Recibos Nom_01/Juan.pdf"
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
    # 1. Si existe el maestro, usamos el maestro como referencia
    if os.path.exists("Control_Maestro.csv"):
        df_maestro = pd.read_csv("Control_Maestro.csv")
    else:
        # Si no, escaneamos recursivamente
        files = glob.glob("recibos/**/*.pdf", recursive=True)
        # Convertimos rutas completas a rutas relativas (ej. "Recibos Nom_01/Archivo.pdf")
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
            # Buscamos coincidencia exacta de ruta relativa
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

# --- FUNCION DE RECONSTRUCCION RECURSIVA ---
def reconstruir_maestro_desde_archivos():
    """Busca en TODAS las subcarpetas de 'recibos'"""
    if not os.path.exists("recibos"): return 0
    
    # BUSQUEDA RECURSIVA (La clave es el recursive=True)
    archivos = glob.glob("recibos/**/*.pdf", recursive=True)
    db = []
    
    for ruta_completa in archivos:
        try:
            # Obtenemos la ruta relativa para guardarla limpia (ej: "Recibos Nom_01/Juan.pdf")
            nombre_relativo = os.path.relpath(ruta_completa, "recibos")
            
            reader = PdfReader(ruta_completa)
            text = reader.pages[0].extract_text()
            
            # Buscar RFC
            match = re.search(r'[A-Z]{4}\d{6}[A-Z0-9]{3}', text)
            rfc = match.group(0) if match else "DESCONOCIDO"
            
            # Limpieza de nombre para visualización
            nombre_limpio = os.path.basename(ruta_completa).replace(".pdf", "").replace("_", " ")
            
            db.append({
                "file": nombre_relativo, # Guardamos la ruta con subcarpeta
                "name": nombre_limpio,
                "rfc": rfc
            })
        except:
            continue
            
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
    
    # Filtramos por RFC
    archivos_asignados = df[df['rfc'] == rfc]['file'].tolist()
    
    # Validamos existencia física (construyendo la ruta completa)
    archivos_validos = []
    for f_relativo in archivos_asignados:
        ruta_completa = os.path.join("recibos", f_relativo)
        if os.path.exists(ruta_completa):
            archivos_validos.append(f_relativo) # Retornamos la ruta relativa ("Subcarpeta/Archivo.pdf")
            
    # Ordenamos para que salgan (probablemente) por semana si los nombres ayudan
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
        
        can.drawImage(ImageReader(img_buffer), 400, 300, width=150, height=60, mask='auto')
        can.drawString(356, 290, "Firma Digital")
        
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
        
        # Guardar firmado en la misma carpeta original
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
    st.title("OTE V23.0 (Multi-Semana)")
    
    if st.toggle("Modo Admin"):
        pwd = st.text_input("Password Admin", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("Acceso OK")
        else:
            st.session_state.admin = False
    else: st.session_state.admin = False

# --- PANEL ADMIN ---
if st.session_state.admin:
    st.title("📊 Tablero de Control RRHH")
    
    tab1, tab2, tab3, tab4 = st.tabs(["🛠️ Base de Datos", "📂 Cargar Nómina", "🚨 Monitor de Firmas", "👥 Usuarios"])
    
    with tab1:
        st.subheader("Indexación de Carpetas")
        st.info("Usa esto para detectar archivos en subcarpetas (ej: Recibos Nom_01, Nom_02...)")
        
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔄 Reconstruir Base de Datos (Escanear Todo)", type="primary"):
                with st.spinner("Escaneando subcarpetas..."):
                    cantidad = reconstruir_maestro_desde_archivos()
                    if cantidad > 0:
                        st.success(f"✅ Se indexaron {cantidad} recibos de todas las carpetas.")
                        st.rerun()
                    else:
                        st.error("No se encontraron PDFs en 'recibos' ni sus subcarpetas.")
        
        with col_b:
            if os.path.exists("Control_Maestro.csv"):
                df = pd.read_csv("Control_Maestro.csv")
                st.write(f"Total Indexado: **{len(df)} registros**")
                st.dataframe(df, height=200)

    with tab2:
        st.write("Carga manual de archivos (se guardan en raíz 'recibos' por defecto).")
        uploaded = st.file_uploader("Subir PDFs", accept_multiple_files=True)
        if st.button("Procesar Archivos"):
            if uploaded:
                if not os.path.exists("recibos"): os.makedirs("recibos")
                # Solo para mantener la logica, aunque lo ideal es reconstruir
                for f in uploaded:
                    with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                st.success("Archivos subidos. Ahora ve a 'Base de Datos' y dale a Reconstruir.")

    with tab3:
        st.subheader("Estado de Cumplimiento por Semana")
        df_status = obtener_status_global()
        
        if not df_status.empty:
            col1, col2, col3 = st.columns(3)
            pendientes = len(df_status[df_status['Estado'] == "❌ PENDIENTE"])
            firmados = len(df_status[df_status['Estado'] == "✅ FIRMADO"])
            
            col1.metric("Total Documentos", len(df_status))
            col2.metric("Firmados", firmados)
            col3.metric("Pendientes", pendientes, delta_color="inverse")
            
            # Filtros
            filtro = st.radio("Mostrar:", ["Todos", "Pendientes", "Firmados"], horizontal=True)
            if filtro == "Pendientes":
                df_show = df_status[df_status['Estado'] == "❌ PENDIENTE"]
            elif filtro == "Firmados":
                df_show = df_status[df_status['Estado'] == "✅ FIRMADO"]
            else:
                df_show = df_status
                
            st.dataframe(df_show, use_container_width=True)
            
            st.write("#### 📢 Alerta de Cobranza")
            lista_p = df_status[df_status['Estado'] == "❌ PENDIENTE"]
            
            if not lista_p.empty:
                # El valor del selectbox es el archivo relativo (ej: Nom_01/Juan.pdf)
                seleccion = st.selectbox("Seleccionar moroso:", lista_p['Semana/Archivo'])
                
                if st.button("Enviar Recordatorio"):
                    rfc_target = lista_p[lista_p['Semana/Archivo'] == seleccion].iloc[0]['RFC']
                    email_target = None
                    if os.path.exists("Directorio_Contactos.csv"):
                        df_dir = pd.read_csv("Directorio_Contactos.csv")
                        match = df_dir[df_dir['rfc'] == rfc_target]
                        if not match.empty: email_target = match.iloc[0]['email']
                    
                    if email_target:
                        cuerpo = f"Hola,\nTienes un recibo pendiente: {seleccion}.\nIngresa a Nexus para firmar."
                        ok, msg = enviar_correo_general(email_target, "ALERTA: Firma Pendiente", cuerpo)
                        if ok: st.success(f"Enviado a {email_target}")
                        else: st.error(msg)
                    else: st.warning("Sin correo registrado.")
        else:
            st.info("Base de datos vacía.")

    with tab4:
        if os.path.exists("Directorio_Contactos.csv"):
            st.dataframe(pd.read_csv("Directorio_Contactos.csv"))

# --- VISTA EMPLEADO ---
else:
    st.header("Portal Empleado")
    
    if not st.session_state.user:
        rfc_input = st.text_input("Ingresa tu RFC").upper()
        
        if rfc_input:
            if not os.path.exists("Control_Maestro.csv"):
                st.error("Base de datos no encontrada. Contacta a RRHH.")
            else:
                df_m = pd.read_csv("Control_Maestro.csv")
                # Buscamos si el RFC existe en CUALQUIER recibo
                match_user = df_m[df_m['rfc'] == rfc_input]
                
                if not match_user.empty:
                    # Tomamos el nombre del primer registro
                    nombre_empleado = match_user.iloc[0]['name']
                    
                    if gestionar_credenciales(rfc_input, modo="verificar"):
                        st.info(f"Hola **{nombre_empleado}**, ingresa tu contraseña.")
                        pwd = st.text_input("Contraseña", type="password")
                        if st.button("Entrar"):
                            if gestionar_credenciales(rfc_input, pwd, modo="login"):
                                st.session_state.user = {'rfc': rfc_input, 'name': nombre_empleado}
                                st.rerun()
                            else: st.error("Contraseña incorrecta")
                    else:
                        st.warning(f"Bienvenido {nombre_empleado}. Crea tu contraseña.")
                        new_p = st.text_input("Nueva Contraseña", type="password")
                        conf_p = st.text_input("Confirmar", type="password")
                        if st.button("Registrar"):
                            if new_p == conf_p and new_p:
                                gestionar_credenciales(rfc_input, new_p, modo="registro")
                                st.session_state.user = {'rfc': rfc_input, 'name': nombre_empleado}
                                st.rerun()
                            else: st.error("Error en contraseñas")
                else:
                    st.error("RFC no encontrado.")

    else:
        u = st.session_state.user
        st.success(f"Bienvenido: {u['name']} ({u['rfc']})")
        
        mis_recibos = listar_recibos_empleado_db(u['rfc'])
        
        if mis_recibos:
            st.info(f"📂 Tienes {len(mis_recibos)} recibos disponibles en historial.")
            
            # Selector de archivo (Muestra la ruta relativa, ej: "Recibos Nom_01/Juan.pdf")
            archivo_relativo = st.selectbox("Selecciona el recibo a visualizar:", mis_recibos)
            
            # Construir ruta completa para abrir
            ruta_pdf = os.path.join("recibos", archivo_relativo)
            
            df_firmas = cargar_db_firmas()
            ya_firmado = ((df_firmas['RFC'] == u['rfc']) & (df_firmas['Archivo'] == archivo_relativo)).any()
            
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
            
            if not ya_firmado:
                st.write("---")
                st.write("✍️ **Firmar Documento:**")
                # Clave única para el canvas basada en el archivo seleccionado
                canvas = st_canvas(stroke_width=2, height=150, key=f"c_{archivo_relativo}")
                
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
                                f"Recibo Firmado - {os.path.basename(archivo_relativo)}",
                                "Adjuntamos su documento firmado.",
                                path_firmado,
                                "Recibo_Firmado.pdf"
                            )
                            
                            if ok:
                                # Guardamos el nombre relativo en la BD
                                registrar_firma_db(u['rfc'], archivo_relativo)
                                st.success("Firmado correctamente.")
                                st.rerun()
                            else: st.error(f"Error envío: {msg}")
            
            st.download_button("Descargar PDF", pdf_bytes, file_name=os.path.basename(archivo_relativo))

        else:
            st.warning("No tienes recibos asignados en ninguna carpeta.")
        
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