# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import base64
import os
import re
import glob
import smtplib
import io
import shutil
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

# --- CONFIGURACION ---
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
        return pd.DataFrame()

    df_firmas = cargar_db_firmas()
    status_list = []
    
    for index, row in df_maestro.iterrows():
        archivo_rel = row['file']
        if "_FIRMADO.pdf" in archivo_rel: continue

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

# --- RECONSTRUCCION INTELIGENTE (CORREGIDA) ---
def reconstruir_maestro_desde_archivos():
    if not os.path.exists("recibos"): return 0
    
    # Busqueda recursiva en subcarpetas
    archivos = glob.glob("recibos/**/*.pdf", recursive=True)
    db = []
    
    for ruta_completa in archivos:
        try:
            nombre_relativo = os.path.relpath(ruta_completa, "recibos")
            if "_FIRMADO" in nombre_relativo: continue

            reader = PdfReader(ruta_completa)
            text = reader.pages[0].extract_text()
            
            # 1. Extracción de RFC (Regex Robusto)
            match_rfc = re.search(r'[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}', text)
            rfc = match_rfc.group(0) if match_rfc else "DESCONOCIDO"
            
            # 2. Extracción de NOMBRE (Lógica Híbrida)
            nombre_final = "Colaborador"
            
            # INTENTO A: Buscar etiqueta "Empleado:" dentro del PDF
            match_kw = re.search(r'(?:EMPLEADO|TRABAJADOR|NOMBRE)[:\.\s]+([A-ZÑ\s\.]+)', text)
            if match_kw:
                posible = match_kw.group(1).strip().split('\n')[0]
                # Validar que sea un nombre y no basura
                if len(posible) > 4 and sum(c.isdigit() for c in posible) < 2:
                    nombre_final = posible

            # INTENTO B: Si falló A, usar el NOMBRE DEL ARCHIVO (Limpio)
            # Esto soluciona el problema de raíz si el PDF no se deja leer bien.
            if nombre_final == "Colaborador":
                nombre_base = os.path.basename(ruta_completa).replace(".pdf", "")
                # Quitamos guiones y cosas raras
                nombre_limpio = nombre_base.replace("_", " ").replace("-", " ")
                # Si el nombre del archivo tiene letras, lo usamos
                if any(c.isalpha() for c in nombre_limpio):
                    nombre_final = nombre_limpio

            db.append({
                "file": nombre_relativo,
                "name": nombre_final, # Aquí guardamos el nombre real detectado
                "rfc": rfc
            })
        except: continue
            
    if db:
        df = pd.DataFrame(db)
        df.to_csv("Control_Maestro.csv", index=False)
        return len(db)
    return 0

def purgar_semana_anterior():
    if os.path.exists("recibos"):
        shutil.rmtree("recibos")
        os.makedirs("recibos")
    
    if os.path.exists("Control_Maestro.csv"):
        # Borramos el archivo y creamos uno vacío con encabezados
        with open("Control_Maestro.csv", "w") as f:
            f.write("file,name,rfc\n")
        
    return True

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
    try:
        df = pd.read_csv("Control_Maestro.csv")
        if df.empty: return []
        
        # Filtramos por RFC
        archivos_asignados = df[df['rfc'] == rfc]['file'].tolist()
        
        archivos_validos = []
        for f_rel in archivos_asignados:
            if "_FIRMADO" in f_rel: continue
            if os.path.exists(os.path.join("recibos", f_rel)):
                archivos_validos.append(f_rel)
        
        archivos_validos.sort(reverse=True)
        return archivos_validos
    except: return []

def firmar_pdf(ruta_orig, firma_bytes):
    try:
        packet = io.BytesIO()
        can = pdf_canvas.Canvas(packet, pagesize=letter)
        img = Image.fromarray(firma_bytes.astype('uint8'), 'RGBA')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        # COORDENADAS OTESA SOLICITADAS
        can.drawImage(ImageReader(img_buffer), 430, 250, width=150, height=60, mask='auto')
        can.drawString(430, 235, "Firma Digital")
        
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
    st.title("OTESA V28.0")
    
    if st.toggle("Modo Admin"):
        pwd = st.text_input("Password Admin", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("OK")
        else:
            st.session_state.admin = False
    else: st.session_state.admin = False

if st.session_state.admin:
    st.title("📊 Tablero OTESA - RRHH")
    
    tab1, tab2, tab3, tab4 = st.tabs(["🛠️ Base de Datos", "📂 Cargar Nómina", "🚨 Monitor de Firmas", "👥 Usuarios"])
    
    with tab1:
        st.subheader("Mantenimiento Semanal")
        col_a, col_b = st.columns(2)
        with col_a:
            st.info("Paso 1: Detectar Nombres y RFCs")
            if st.button("🔄 Reconstruir Base de Datos", type="primary"):
                with st.spinner("Indexando..."):
                    n = reconstruir_maestro_desde_archivos()
                    st.success(f"Indexados: {n} archivos.")
                    st.rerun()
        
        with col_b:
            st.error("⚠️ ZONA DE PELIGRO")
            if st.button("🗑️ VACIAR SEMANA ANTERIOR"):
                purgar_semana_anterior()
                st.success("Sistema limpio.")
                st.rerun()

        st.write("---")
        st.write("**Verificar Nombres Detectados:**")
        if os.path.exists("Control_Maestro.csv"):
            try:
                df = pd.read_csv("Control_Maestro.csv")
                # Permitir edición manual si el sistema falla
                df_edited = st.data_editor(df, num_rows="dynamic", use_container_width=True)
                if st.button("Guardar Correcciones Manuales"):
                    df_edited.to_csv("Control_Maestro.csv", index=False)
                    st.success("Base de datos actualizada manualmente.")
            except: st.error("Archivo DB vacío.")

    with tab2:
        uploaded = st.file_uploader("Subir PDFs", accept_multiple_files=True)
        if st.button("Procesar Archivos"):
            if uploaded:
                if not os.path.exists("recibos"): os.makedirs("recibos")
                for f in uploaded:
                    with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                st.success("Cargado. Ahora ve a 'Base de Datos' -> Reconstruir.")

    with tab3:
        st.subheader("Monitor de Firmas")
        df_status = obtener_status_global()
        if not df_status.empty:
            col1, col2 = st.columns(2)
            pend = len(df_status[df_status['Estado'] == "❌ PENDIENTE"])
            col1.metric("Pendientes", pend)
            col2.metric("Total", len(df_status))
            
            st.dataframe(df_status, use_container_width=True)
            
            lista_p = df_status[df_status['Estado'] == "❌ PENDIENTE"]
            if not lista_p.empty:
                sel = st.selectbox("Seleccionar moroso:", lista_p['Semana/Archivo'])
                if st.button("Enviar Alerta"):
                    rfc_t = lista_p[lista_p['Semana/Archivo'] == sel].iloc[0]['RFC']
                    mail_t = None
                    if os.path.exists("Directorio_Contactos.csv"):
                        dfd = pd.read_csv("Directorio_Contactos.csv")
                        m = dfd[dfd['rfc'] == rfc_t]
                        if not m.empty: mail_t = m.iloc[0]['email']
                    
                    if mail_t:
                        cuerpo = f"Hola,\nRecibo pendiente: {sel}.\nFirma en Nexus."
                        ok, msg = enviar_correo_general(mail_t, "ALERTA OTESA", cuerpo)
                        if ok: st.success("Enviado")
                        else: st.error(msg)
                    else: st.warning("Sin correo.")

    with tab4:
        if os.path.exists("Directorio_Contactos.csv"):
            st.dataframe(pd.read_csv("Directorio_Contactos.csv"))

else:
    st.header("Portal OTESA")
    
    if not st.session_state.user:
        rfc_input = st.text_input("Ingresa tu RFC").upper()
        if rfc_input:
            if not os.path.exists("Control_Maestro.csv"):
                st.error("Contacta a RRHH (DB Vacía).")
            else:
                try:
                    df_m = pd.read_csv("Control_Maestro.csv")
                    # Buscamos coincidencias
                    match_user = df_m[df_m['rfc'] == rfc_input]
                    
                    if not match_user.empty:
                        # Extraemos el nombre (ahora será el nombre del archivo si falló la lectura)
                        nombre_persona = match_user.iloc[0]['name']
                        
                        if gestionar_credenciales(rfc_input, modo="verificar"):
                            st.info(f"Hola **{nombre_persona}**.")
                            p = st.text_input("Contraseña", type="password")
                            if st.button("Entrar"):
                                if gestionar_credenciales(rfc_input, p, modo="login"):
                                    st.session_state.user = {'rfc': rfc_input, 'name': nombre_persona}
                                    st.rerun()
                                else: st.error("Incorrecto")
                        else:
                            st.warning(f"Bienvenido {nombre_persona}. Regístrate.")
                            n_p = st.text_input("Pass", type="password")
                            c_p = st.text_input("Confirmar", type="password")
                            if st.button("Registrar"):
                                if n_p == c_p and n_p:
                                    gestionar_credenciales(rfc_input, n_p, modo="registro")
                                    st.session_state.user = {'rfc': rfc_input, 'name': nombre_persona}
                                    st.rerun()
                                else: st.error("Error pass")
                    else: st.error("RFC no encontrado en nómina actual.")
                except: st.error("Error leyendo base de datos.")
    else:
        u = st.session_state.user
        st.success(f"Hola: {u['name']}")
        mis_recibos = listar_recibos_empleado_db(u['rfc'])
        
        if mis_recibos:
            df_f = cargar_db_firmas()
            pendientes = []
            firmados = []
            for r in mis_recibos:
                if ((df_f['RFC'] == u['rfc']) & (df_f['Archivo'] == r)).any():
                    firmados.append(r)
                else:
                    pendientes.append(r)
            
            if pendientes:
                st.info(f"Tienes {len(pendientes)} pendiente(s).")
                archivo_sel = st.selectbox("Selecciona:", pendientes)
                ya_firmado = False
            elif firmados:
                st.success("Todo firmado.")
                if st.checkbox("Ver historial"):
                    archivo_sel = st.selectbox("Historial:", firmados)
                    ya_firmado = True
                else: archivo_sel = None
            else: archivo_sel = None

            if archivo_sel:
                ruta_pdf = os.path.join("recibos", archivo_sel)
                
                with open(ruta_pdf, "rb") as f: bytes_pdf = f.read()
                
                if pdf_viewer: pdf_viewer(input=bytes_pdf, width=700)
                else: st.warning("No visor.")
                
                if not ya_firmado:
                    st.write("---")
                    st.write("Firma aquí:")
                    canvas = st_canvas(stroke_width=2, height=150, key=f"c_{archivo_sel}")
                    if st.button("Firmar y Enviar"):
                        if canvas.image_data is not None:
                            path = firmar_pdf(ruta_pdf, canvas.image_data)
                            if path:
                                m_u = None
                                if os.path.exists("Directorio_Contactos.csv"):
                                    d = pd.read_csv("Directorio_Contactos.csv")
                                    m = d[d['rfc'] == u['rfc']]
                                    if not m.empty: m_u = m.iloc[0]['email']
                                
                                ok, t = enviar_correo_general(m_u if m_u else SENDER_EMAIL, 
                                    f"Recibo Firmado {u['rfc']}", "Adjunto.", path, "Firmado.pdf")
                                if ok:
                                    registrar_firma_db(u['rfc'], archivo_sel)
                                    st.success("Listo")
                                    st.rerun()
                                else: st.error(t)
                
                st.download_button("Descargar", bytes_pdf, file_name=os.path.basename(archivo_sel))
        else: st.warning("Sin recibos.")

        st.write("---")
        with st.expander("Correo"):
            m = st.text_input("Nuevo Correo")
            if st.button("Guardar"):
                if "@" in m:
                    f = "Directorio_Contactos.csv"
                    if not os.path.exists(f): pd.DataFrame(columns=['rfc','email']).to_csv(f, index=False)
                    d = pd.read_csv(f)
                    d = d[d['rfc'] != u['rfc']]
                    n = pd.DataFrame([{'rfc': u['rfc'], 'email': m}])
                    pd.concat([d, n]).to_csv(f, index=False)
                    st.success("OK")
        
        if st.button("Salir"):
            st.session_state.user = None
            st.rerun()