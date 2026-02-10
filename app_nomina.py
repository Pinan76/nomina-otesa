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

# 🛑 RFC DE LA EMPRESA A IGNORAR (Para que no se confunda)
RFC_EMPRESA = "OTE2107019N1" 
# ==========================================

# --- BASE DE DATOS ---
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
    else: return pd.DataFrame()

    df_firmas = cargar_db_firmas()
    status_list = []
    
    for index, row in df_maestro.iterrows():
        archivo_rel = row['file']
        if "_FIRMADO.pdf" in archivo_rel: continue

        rfc = row['rfc']
        nombre = row['name']
        
        estado = "❌ PENDIENTE"
        if not df_firmas.empty:
            # Coincidencia estricta
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

# --- RECONSTRUCCION CON FILTRO DE EMPRESA ---
def reconstruir_maestro_desde_archivos():
    if not os.path.exists("recibos"): return 0
    
    archivos = glob.glob("recibos/**/*.pdf", recursive=True)
    db = []
    
    for ruta_completa in archivos:
        try:
            nombre_relativo = os.path.relpath(ruta_completa, "recibos")
            if "_FIRMADO" in nombre_relativo: continue

            reader = PdfReader(ruta_completa)
            text = reader.pages[0].extract_text()
            
            # --- CORRECCIÓN CRÍTICA: BUSCAR TODOS LOS RFCs ---
            # Buscamos todas las coincidencias de RFC en el texto
            todos_los_rfcs = re.findall(r'[A-Z&Ñ]{3,4}\s*\d{6}\s*[A-Z0-9]{3}', text)
            
            rfc_final = "DESCONOCIDO"
            
            # Iteramos sobre los RFCs encontrados
            for rfc_encontrado in todos_los_rfcs:
                rfc_limpio = rfc_encontrado.replace(" ", "").strip()
                # SI EL RFC NO ES EL DE LA EMPRESA, ENTONCES ES EL DEL EMPLEADO
                if rfc_limpio != RFC_EMPRESA:
                    rfc_final = rfc_limpio
                    break 
            
            # --- NOMBRE INTELIGENTE ---
            nombre_final = "Colaborador"
            
            # 1. Intentar sacar del nombre del archivo (Más confiable si el PDF es imagen)
            nombre_base = os.path.basename(ruta_completa).replace(".pdf", "")
            # Limpieza: Quitamos guiones bajos y códigos comunes
            nombre_limpio = nombre_base.replace("_", " ").replace("-", " ")
            # Quitamos palabras técnicas del nombre de archivo si existen
            nombre_limpio = re.sub(r'RE\s*\d+', '', nombre_limpio)
            nombre_limpio = re.sub(r'Semanal\s*\d+', '', nombre_limpio)
            
            if len(nombre_limpio) > 3:
                nombre_final = nombre_limpio.strip()

            db.append({
                "file": nombre_relativo,
                "name": nombre_final,
                "rfc": rfc_final
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
        # Resetear maestro
        with open("Control_Maestro.csv", "w") as f: f.write("file,name,rfc\n")
    return True

# --- CORREO ---
def enviar_correo_general(destinatario, asunto, cuerpo, adjunto_path=None, nombre_adjunto=None):
    dest_final = SENDER_EMAIL
    if destinatario and "@" in str(destinatario): dest_final = str(destinatario).strip()
    try:
        msg = EmailMessage()
        msg['Subject'] = asunto
        msg['From'] = SENDER_EMAIL
        msg['To'] = dest_final
        msg['Cc'] = SENDER_EMAIL
        msg.set_content(cuerpo)
        if adjunto_path:
            with open(adjunto_path, 'rb') as f:
                msg.add_attachment(f.read(), maintype='application', subtype='pdf', filename=nombre_adjunto)
        server = smtplib.SMTP(SERVIDOR_SMTP, PUERTO_SMTP)
        server.ehlo(); server.starttls(); server.ehlo()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True, "Enviado con éxito"
    except Exception as e: return False, str(e)

# --- EMPLEADO ---
def listar_recibos_empleado_db(rfc):
    if not os.path.exists("Control_Maestro.csv"): return []
    try:
        df = pd.read_csv("Control_Maestro.csv")
        if df.empty: return []
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
        # Coordenadas (430, 250)
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
        with open(nombre_salida, "wb") as f: output.write(f)
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
    st.title("OTESA V32.0")
    if st.toggle("Modo Admin"):
        pwd = st.text_input("Password", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("OK")
        else: st.session_state.admin = False
    else: st.session_state.admin = False

if st.session_state.admin:
    st.title("📊 Panel Admin")
    
    tab1, tab2, tab3, tab4 = st.tabs(["🛠️ Base de Datos", "📂 Cargar Nómina", "🚨 Monitor", "👥 Usuarios"])
    
    with tab1:
        st.subheader("Gestión de Datos (Filtro Anti-Empresa Activo)")
        st.info(f"El sistema ignorará automáticamente el RFC: {RFC_EMPRESA} para encontrar al empleado.")
        
        col_a, col_b = st.columns([1, 1])
        with col_a:
            if st.button("🔄 Reconstruir Base de Datos", type="primary"):
                with st.spinner("Re-escaneando sin RFC de empresa..."):
                    n = reconstruir_maestro_desde_archivos()
                    st.success(f"Procesados: {n}")
                    st.rerun()
        
        with col_b:
            if st.button("🗑️ VACIAR SEMANA ANTERIOR"):
                purgar_semana_anterior()
                st.success("Limpio.")
                st.rerun()

        st.write("---")
        st.write("**Verificar Datos Detectados:**")
        if os.path.exists("Control_Maestro.csv"):
            try:
                df = pd.read_csv("Control_Maestro.csv")
                df_edited = st.data_editor(
                    df,
                    column_config={
                        "file": "Archivo",
                        "rfc": "RFC (Debe ser del empleado)",
                        "name": "Nombre"
                    },
                    disabled=["file"],
                    num_rows="dynamic",
                    use_container_width=True
                )
                if st.button("💾 Guardar Correcciones Manuales"):
                    df_edited.to_csv("Control_Maestro.csv", index=False)
                    st.success("Guardado.")
            except: st.error("Error DB.")

    with tab2:
        st.write("Carga de Archivos")
        uploaded = st.file_uploader("Subir PDFs", accept_multiple_files=True)
        if st.button("Procesar Archivos"):
            if uploaded:
                if not os.path.exists("recibos"): os.makedirs("recibos")
                for f in uploaded:
                    with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                st.success("Subido. Ahora dale a Reconstruir.")

    with tab3:
        st.subheader("Monitor")
        df_s = obtener_status_global()
        if not df_s.empty:
            st.dataframe(df_s, use_container_width=True)
            lista_p = df_s[df_s['Estado'] == "❌ PENDIENTE"]
            if not lista_p.empty:
                sel = st.selectbox("Recordatorio:", lista_p['Semana/Archivo'])
                if st.button("Enviar Alerta"):
                    rfc_t = lista_p[lista_p['Semana/Archivo'] == sel].iloc[0]['RFC']
                    mail_t = None
                    if os.path.exists("Directorio_Contactos.csv"):
                        dfd = pd.read_csv("Directorio_Contactos.csv")
                        m = dfd[dfd['rfc'] == rfc_t]
                        if not m.empty: mail_t = m.iloc[0]['email']
                    
                    if mail_t:
                        c = f"Recibo pendiente: {sel}. Firma en Nexus."
                        ok, ms = enviar_correo_general(mail_t, "ALERTA OTESA", c)
                        if ok: st.success("Enviado")
                        else: st.error(ms)
                    else: st.warning("Sin correo")
        else: st.info("Sin datos.")

    with tab4:
        if os.path.exists("Directorio_Contactos.csv"):
            st.dataframe(pd.read_csv("Directorio_Contactos.csv"))

else:
    st.header("Portal OTESA")
    
    if not st.session_state.user:
        rfc_input = st.text_input("Ingresa tu RFC").upper()
        if rfc_input:
            if not os.path.exists("Control_Maestro.csv"):
                st.error("Error DB.")
            else:
                try:
                    df_m = pd.read_csv("Control_Maestro.csv")
                    match_user = df_m[df_m['rfc'] == rfc_input]
                    
                    if not match_user.empty:
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
                            st.warning(f"Bienvenido {nombre_persona}. Crea Pass.")
                            n = st.text_input("Pass", type="password")
                            c = st.text_input("Confirmar", type="password")
                            if st.button("Registrar"):
                                if n == c and n:
                                    gestionar_credenciales(rfc_input, n, modo="registro")
                                    st.session_state.user = {'rfc': rfc_input, 'name': nombre_persona}
                                    st.rerun()
                                else: st.error("Error")
                    else: 
                        st.error(f"RFC no encontrado. (El sistema ignoró {RFC_EMPRESA}, pero no encontró el tuyo. Pide a Admin corrección manual).")
                except: st.error("Error leyendo DB.")
    else:
        u = st.session_state.user
        st.success(f"Hola: {u['name']}")
        
        mis_recibos = listar_recibos_empleado_db(u['rfc'])
        if mis_recibos:
            df_f = cargar_db_firmas()
            pendientes = []
            firmados = []
            for r in mis_recibos:
                if ((df_f['RFC'] == u['rfc']) & (df_f['Archivo'] == r)).any(): firmados.append(r)
                else: pendientes.append(r)
            
            if pendientes:
                st.info(f"Pendientes: {len(pendientes)}")
                archivo_sel = st.selectbox("Firmar:", pendientes)
                ya_firmado = False
            elif firmados:
                st.success("Todo firmado.")
                if st.checkbox("Historial"):
                    archivo_sel = st.selectbox("Ver:", firmados)
                    ya_firmado = True
                else: archivo_sel = None
            else: archivo_sel = None

            if archivo_sel:
                ruta_pdf = os.path.join("recibos", archivo_sel)
                with open(ruta_pdf, "rb") as f: b = f.read()
                if pdf_viewer: pdf_viewer(input=b, width=700)
                else: st.warning("No visor")
                
                if not ya_firmado:
                    st.write("---")
                    canvas = st_canvas(stroke_width=2, height=150, key=f"c_{archivo_sel}")
                    if st.button("Firmar y Enviar"):
                        if canvas.image_data is not None:
                            with st.spinner("Enviando..."):
                                path = firmar_pdf(ruta_pdf, canvas.image_data)
                                if path:
                                    m_u = None
                                    if os.path.exists("Directorio_Contactos.csv"):
                                        d = pd.read_csv("Directorio_Contactos.csv")
                                        m = d[d['rfc'] == u['rfc']]
                                        if not m.empty: m_u = m.iloc[0]['email']
                                    
                                    cuerpo = f"Recibo semana trabajada.\nRFC: {u['rfc']}\n\nAtte. RRHH OTESA"
                                    ok, t = enviar_correo_general(m_u, f"Recibo {u['rfc']}", cuerpo, path, "Recibo_Nomina.pdf")
                                    if ok:
                                        registrar_firma_db(u['rfc'], archivo_sel)
                                        st.balloons()
                                        st.success("Enviado")
                                        st.rerun()
                                    else: st.error(t)
                st.download_button("Descargar", b, file_name=os.path.basename(archivo_sel))
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
                    st.rerun()
        if st.button("Salir"):
            st.session_state.user = None
            st.rerun()