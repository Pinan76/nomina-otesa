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

# Configuración Inicial
try:
    from streamlit_pdf_viewer import pdf_viewer
except ImportError:
    pdf_viewer = None

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
RFC_EMPRESA = "OTE2107019N1" 
# ==========================================

# --- FUNCIONES DE BASE DE DATOS ---
def inicializar_db():
    # 1. Maestro
    if not os.path.exists('Control_Maestro.csv'):
        with open('Control_Maestro.csv', 'w') as f: f.write('file,name,rfc\n')
    
    # 2. Firmas
    if not os.path.exists('Bitacora_Firmas.csv'):
        pd.DataFrame(columns=['RFC', 'Archivo', 'Fecha_Firma', 'Estado']).to_csv('Bitacora_Firmas.csv', index=False)
        
    # 3. Correos (Directorio)
    if not os.path.exists('Directorio_Contactos.csv'):
        pd.DataFrame(columns=['rfc', 'email']).to_csv('Directorio_Contactos.csv', index=False)

    # 4. Bitácora de Envíos (NUEVO)
    if not os.path.exists('Bitacora_Envios.csv'):
        pd.DataFrame(columns=['Fecha', 'RFC', 'Destino', 'Estado', 'Detalle']).to_csv('Bitacora_Envios.csv', index=False)

inicializar_db()

def cargar_db_firmas(): return pd.read_csv('Bitacora_Firmas.csv')

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

def registrar_envio_correo(rfc, destino, estado, detalle):
    """Guarda el resultado del envío en la bitácora"""
    file_log = 'Bitacora_Envios.csv'
    nuevo = {
        'Fecha': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'RFC': rfc,
        'Destino': destino,
        'Estado': estado, # EXITOSO o FALLIDO
        'Detalle': detalle
    }
    df = pd.read_csv(file_log)
    df = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
    df.to_csv(file_log, index=False)

def obtener_status_global():
    if os.path.exists("Control_Maestro.csv"):
        try: df_maestro = pd.read_csv("Control_Maestro.csv")
        except: return pd.DataFrame()
    else: return pd.DataFrame()

    df_firmas = cargar_db_firmas()
    status_list = []
    
    for index, row in df_maestro.iterrows():
        archivo_rel = str(row['file'])
        if "_FIRMADO.pdf" in archivo_rel: continue

        rfc = str(row['rfc'])
        nombre = str(row['name'])
        
        estado = "❌ PENDIENTE"
        if not df_firmas.empty:
            coincidencia = df_firmas[(df_firmas['RFC'] == rfc) & (df_firmas['Archivo'] == archivo_rel)]
            if not coincidencia.empty: estado = "✅ FIRMADO"
        
        status_list.append({
            'Semana/Archivo': archivo_rel,
            'Empleado': nombre,
            'RFC': rfc,
            'Estado': estado
        })
    return pd.DataFrame(status_list)

# --- ESCANER INTELIGENTE ---
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
            lines = text.split('\n')
            
            # RFC
            todos_rfcs = re.findall(r'[A-Z&Ñ]{3,4}\s*\d{6}\s*[A-Z0-9]{3}', text)
            rfc_final = "DESCONOCIDO"
            for rfc in todos_rfcs:
                clean_rfc = rfc.replace(" ", "").strip()
                if clean_rfc != RFC_EMPRESA:
                    rfc_final = clean_rfc; break
            
            # NOMBRE
            nombre_final = "Colaborador"
            if rfc_final != "DESCONOCIDO":
                idx_rfc = -1
                for i, line in enumerate(lines):
                    if rfc_final in line.replace(" ", ""): idx_rfc = i; break
                
                if idx_rfc != -1:
                    candidatos = []
                    candidatos.append(lines[idx_rfc].replace(rfc_final, "").strip())
                    if idx_rfc > 0: candidatos.append(lines[idx_rfc-1].strip())
                    if idx_rfc < len(lines)-1: candidatos.append(lines[idx_rfc+1].strip())
                    
                    for cand in candidatos:
                        if len(cand) > 7 and any(c.isalpha() for c in cand):
                            if "RFC" not in cand and "CURP" not in cand:
                                nombre_final = cand; break
            
            if nombre_final == "Colaborador":
                base = os.path.basename(ruta_completa)
                if not base.startswith("RE_"):
                     nombre_final = base.replace(".pdf", "").replace("_", " ")

            db.append({"file": nombre_relativo, "name": nombre_final, "rfc": rfc_final})
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
    with open("Control_Maestro.csv", "w") as f: f.write("file,name,rfc\n")
    return True

# --- CORREO ---
def enviar_correo_general(destinatario, asunto, cuerpo, adjunto_path=None, nombre_adjunto=None, rfc_ref="N/A"):
    dest = SENDER_EMAIL
    if destinatario and "@" in str(destinatario): dest = str(destinatario).strip()
    
    try:
        msg = EmailMessage()
        msg['Subject'] = asunto
        msg['From'] = SENDER_EMAIL
        msg['To'] = dest
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
        
        # REGISTRAR EXITO
        registrar_envio_correo(rfc_ref, dest, "EXITOSO", "Enviado correctamente")
        return True, "Enviado"

    except Exception as e:
        # REGISTRAR ERROR
        registrar_envio_correo(rfc_ref, dest, "FALLIDO", str(e))
        return False, str(e)

# --- EMPLEADO ---
def listar_recibos_empleado_db(rfc):
    if not os.path.exists("Control_Maestro.csv"): return []
    try:
        df = pd.read_csv("Control_Maestro.csv")
        if df.empty: return []
        archivos = df[df['rfc'] == rfc]['file'].tolist()
        validos = []
        for f in archivos:
            if "_FIRMADO" in f: continue
            if os.path.exists(os.path.join("recibos", f)): validos.append(f)
        validos.sort(reverse=True)
        return validos
    except: return []

def firmar_pdf(ruta_orig, firma_bytes):
    try:
        packet = io.BytesIO()
        can = pdf_canvas.Canvas(packet, pagesize=letter)
        img = Image.fromarray(firma_bytes.astype('uint8'), 'RGBA')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        # Coordenadas OTESA
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
    if not os.path.exists(file_cred): pd.DataFrame(columns=['rfc', 'password']).to_csv(file_cred, index=False)
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
    st.title("OTESA V34.0")
    if st.toggle("Modo Admin"):
        pwd = st.text_input("Password", type="password")
        if pwd == PASSWORD_ADMIN:
            st.session_state.admin = True
            st.success("OK")
        else: st.session_state.admin = False
    else: st.session_state.admin = False

if st.session_state.admin:
    st.title("📊 Panel Admin")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🛠️ DB", "📂 Carga", "🚨 Firmas", "📧 Monitor de Correos", "👥 Usuarios"])
    
    with tab1:
        st.subheader("Mantenimiento")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Reconstruir Base de Datos", type="primary"):
                n = reconstruir_maestro_desde_archivos()
                st.success(f"Procesados: {n}")
                st.rerun()
        with c2:
            if st.button("🗑️ VACIAR SEMANA ANTERIOR"):
                purgar_semana_anterior()
                st.success("Limpio."); st.rerun()
        
        st.write("---")
        if os.path.exists("Control_Maestro.csv"):
            try:
                df = pd.read_csv("Control_Maestro.csv")
                df_ed = st.data_editor(df, column_config={"file":"Archivo","name":"Nombre","rfc":"RFC"}, disabled=["file"], use_container_width=True)
                if st.button("💾 Guardar Correcciones"):
                    df_ed.to_csv("Control_Maestro.csv", index=False)
                    st.success("Guardado.")
            except: pass

    with tab2:
        uploaded = st.file_uploader("Subir PDFs", accept_multiple_files=True)
        if st.button("Procesar Archivos"):
            if uploaded:
                if not os.path.exists("recibos"): os.makedirs("recibos")
                for f in uploaded:
                    with open(f"recibos/{f.name}", "wb") as w: w.write(f.getbuffer())
                st.success("Listo. Ve a 'DB' -> Reconstruir.")

    with tab3:
        st.subheader("Firmas")
        df_s = obtener_status_global()
        if not df_s.empty:
            st.dataframe(df_s, use_container_width=True)
            lp = df_s[df_s['Estado']=="❌ PENDIENTE"]
            if not lp.empty:
                sel = st.selectbox("Recordatorio:", lp['Semana/Archivo'])
                if st.button("Enviar Alerta"):
                    r = lp[lp['Semana/Archivo']==sel].iloc[0]['RFC']
                    m = None
                    if os.path.exists("Directorio_Contactos.csv"):
                        d = pd.read_csv("Directorio_Contactos.csv")
                        x = d[d['rfc']==r]
                        if not x.empty: m = x.iloc[0]['email']
                    
                    if m:
                        ok, msg = enviar_correo_general(m, "ALERTA", "Firma pendiente.", rfc_ref=r)
                        if ok: st.success("Enviado")
                        else: st.error(msg)
                    else: st.warning("Sin mail")
        else: st.info("Vacio")

    # --- PESTAÑA NUEVA: MONITOR DE CORREOS ---
    with tab4:
        st.subheader("Bitácora de Envíos")
        st.info("Aquí puedes ver si los correos salieron del servidor correctamente.")
        if os.path.exists('Bitacora_Envios.csv'):
            df_log = pd.read_csv('Bitacora_Envios.csv')
            # Ordenar por fecha descendente
            if not df_log.empty:
                df_log = df_log.sort_index(ascending=False)
                st.dataframe(df_log, use_container_width=True)
            else: st.info("No hay envíos registrados.")
            
            if st.button("Borrar Historial de Envíos"):
                pd.DataFrame(columns=['Fecha', 'RFC', 'Destino', 'Estado', 'Detalle']).to_csv('Bitacora_Envios.csv', index=False)
                st.rerun()
        else: st.write("El archivo de log se creará con el primer envío.")

    with tab5:
        if os.path.exists("Directorio_Contactos.csv"): st.dataframe(pd.read_csv("Directorio_Contactos.csv"))

else:
    st.header("Portal OTESA")
    if not st.session_state.user:
        rfc = st.text_input("RFC").upper()
        if rfc:
            if not os.path.exists("Control_Maestro.csv"): st.error("Error DB")
            else:
                try:
                    df = pd.read_csv("Control_Maestro.csv")
                    df['rfc_clean'] = df['rfc'].astype(str).str.replace(" ", "")
                    rfc_clean = rfc.replace(" ", "")
                    user = df[df['rfc_clean'] == rfc_clean]
                    if not user.empty:
                        nom = user.iloc[0]['name']
                        if gestionar_credenciales(rfc_clean, modo="verificar"):
                            st.info(f"Hola {nom}")
                            p = st.text_input("Pass", type="password")
                            if st.button("Entrar"):
                                if gestionar_credenciales(rfc_clean, p, modo="login"):
                                    st.session_state.user = {'rfc': rfc_clean, 'name': nom}
                                    st.rerun()
                                else: st.error("Mal Password")
                        else:
                            st.warning(f"Bienvenido {nom}. Registra Pass.")
                            n = st.text_input("Pass", type="password")
                            c = st.text_input("Confirmar", type="password")
                            if st.button("Registrar"):
                                if n==c and n:
                                    gestionar_credenciales(rfc_clean, n, modo="registro")
                                    st.session_state.user = {'rfc': rfc_clean, 'name': nom}
                                    st.rerun()
                                else: st.error("Error")
                    else: st.error("RFC no encontrado (Verifica con RRHH).")
                except Exception as e: st.error(f"Error sistema: {e}")
    else:
        u = st.session_state.user
        st.success(f"Hola: {u['name']}")
        
        # MOSTRAR Y CONFIGURAR CORREO PRIMERO SI NO EXISTE
        email_actual = "No registrado"
        if os.path.exists("Directorio_Contactos.csv"):
             d = pd.read_csv("Directorio_Contactos.csv")
             x = d[d['rfc']==u['rfc']]
             if not x.empty: email_actual = x.iloc[0]['email']
        
        st.caption(f"Correo registrado: {email_actual}")
        
        mis_r = listar_recibos_empleado_db(u['rfc'])
        if mis_r:
            df_f = cargar_db_firmas()
            pend = [r for r in mis_r if not ((df_f['RFC']==u['rfc']) & (df_f['Archivo']==r)).any()]
            firm = [r for r in mis_r if ((df_f['RFC']==u['rfc']) & (df_f['Archivo']==r)).any()]
            
            if pend:
                st.info(f"Pendientes: {len(pend)}")
                sel = st.selectbox("Firmar:", pend)
                yf = False
            elif firm:
                st.success("Todo listo.")
                if st.checkbox("Historial"):
                    sel = st.selectbox("Ver:", firm)
                    yf = True
                else: sel = None
            else: sel = None

            if sel:
                path = os.path.join("recibos", sel)
                with open(path, "rb") as f: b = f.read()
                if pdf_viewer: pdf_viewer(input=b, width=700)
                
                if not yf:
                    st.write("---")
                    canv = st_canvas(stroke_width=2, height=150, key=f"c_{sel}")
                    if st.button("Firmar y Enviar"):
                        if canvas.image_data is not None:
                            pf = firmar_pdf(path, canv.image_data)
                            if pf:
                                ok, t = enviar_correo_general(email_actual, f"Nomina {u['rfc']}", "Adjunto tu recibo correspondiente a la semana laborada y agardecemos tu aporte.", pf, "Nomina.pdf", rfc_ref=u['rfc'])
                                if ok:
                                    registrar_firma_db(u['rfc'], sel)
                                    st.success("Enviado")
                                    st.balloons()
                                    st.rerun()
                                else: st.error(t)
                st.download_button("Descargar", b, file_name=sel)
        else: st.warning("Sin recibos")

        st.write("---")
        with st.expander("Actualizar mi Correo"):
            m = st.text_input("Correo Personal")
            if st.button("Guardar Correo"):
                if "@" in m:
                    f = "Directorio_Contactos.csv"
                    d = pd.read_csv(f)
                    d = d[d['rfc'] != u['rfc']]
                    n = pd.DataFrame([{'rfc': u['rfc'], 'email': m}])
                    pd.concat([d, n]).to_csv(f, index=False)
                    st.success("Correo actualizado")
                    st.rerun()
        
        if st.button("Salir"):
            st.session_state.user = None
            st.rerun()