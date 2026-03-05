"""
Producto Real · Imagen de referencia → Nueva composición
---------------------------------------------------------
Sube una foto de un producto real (Frenadol, Almax, solar...)
y genera una nueva imagen o vídeo de marketing con ese producto.
Claude mejora el prompt automáticamente como director creativo.
"""

import streamlit as st
import anthropic
import fal_client
import requests
import tempfile
import os
import json
from PIL import Image
from io import BytesIO
from datetime import datetime

st.set_page_config(
    page_title="Producto Real · Farmacia Ads",
    page_icon="📦",
    layout="wide",
)

st.title("📦 Producto Real → Nueva composición")
st.caption("Sube una foto real del producto · Claude mejora el prompt · Flux Kontext o Kling generan el resultado")

# ─── Formatos BD ROWA ─────────────────────────────────────────────────────────

FORMATS = {
    "panorama": {"width": 1080, "height": 1920, "label": "Pantalla completa · 1080×1920"},
    "header":   {"width": 1080, "height": 350,  "label": "Cabecera · 1080×350"},
}

# ─── Prompts de sistema para Claude ──────────────────────────────────────────

CLAUDE_IMAGE = """Eres el director creativo de una farmacia en Canarias, España.
El usuario tiene una FOTO REAL de un producto farmacéutico y quiere colocarlo
en una nueva escena publicitaria. El modelo Flux Kontext usará la foto como referencia
y respetará el packaging, marca y colores exactos del producto.

Responde SIEMPRE en JSON puro (sin markdown):
{
  "formato": "panorama" | "header",
  "prompt_kontext": "...",
  "copy": "...",
  "explicacion": "..."
}

"formato":
  - "panorama" → 1080×1920 px, pantalla completa vertical.
  - "header"   → 1080×350 px, banner horizontal.
  - Si no especifica, elige el más adecuado.

"prompt_kontext":
  - SIEMPRE en inglés.
  - SIEMPRE empezar con: "Keep the product from the reference image exactly as it appears,
    preserving all packaging, labels, colors, logo and branding."
  - Luego describir la nueva escena de forma muy detallada y cinematográfica.
  - Incluir: "ample empty space for text overlay" si es promoción.
  - Terminar con: "commercial pharmacy advertisement, professional product photography, 4K."
  - Nunca inventar el nombre de la marca — el producto viene de la foto.

"copy": Texto publicitario en español, máx 2 líneas.
"explicacion": 1-2 frases describiendo la composición.

Contexto de escenas por producto:
- Solares: playa mediterránea, arena blanca, mar turquesa, verano.
- Piojos: cuarto de baño cálido, padre/madre con hijo, ambiente sereno.
- Analgésicos/antigripales: interior acogedor, invierno, familia.
- Vitaminas: naturaleza, amanecer, persona activa, energía.
- Ortopedia: exterior accesible, movilidad, independencia.
"""

CLAUDE_VIDEO = """Eres el director creativo de una farmacia en Canarias, España.
El usuario tiene una FOTO REAL de un producto y quiere crear un vídeo corto
de marketing donde ese producto se anima o aparece en una escena en movimiento.
El modelo Kling AI usará la foto como primer fotograma y la animará.

Responde SIEMPRE en JSON puro (sin markdown):
{
  "orientacion": "panorama" | "landscape",
  "prompt_video": "...",
  "copy": "...",
  "explicacion": "..."
}

"orientacion":
  - "panorama"  → 9:16 vertical, para pantallas BD ROWA portrait.
  - "landscape" → 16:9 horizontal. Solo si el usuario lo pide explícitamente.

"prompt_video":
  - SIEMPRE en inglés.
  - Describir el MOVIMIENTO que empieza desde la foto del producto.
  - Tipos de movimiento ideales: slow camera zoom in/out, gentle product rotation,
    background elements moving (waves, leaves, steam), camera pan across scene,
    person entering frame, light changing gradually.
  - Terminar con: "cinematic, smooth motion, professional pharmacy advertisement, 4K."
  - Nunca inventar marca — el producto viene de la foto de referencia.

"copy": Texto publicitario en español, máx 2 líneas.
"explicacion": 1-2 frases describiendo la animación propuesta.
"""

# ─── Setup ────────────────────────────────────────────────────────────────────

def init_state():
    if "historial" not in st.session_state:
        st.session_state.historial = []

@st.cache_resource
def get_claude():
    key = st.secrets.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        st.error("⚠️ Falta ANTHROPIC_API_KEY")
        st.stop()
    return anthropic.Anthropic(api_key=key)

def setup_fal():
    key = st.secrets.get("FAL_KEY") or os.getenv("FAL_KEY", "")
    if not key:
        st.error("⚠️ Falta FAL_KEY")
        st.stop()
    os.environ["FAL_KEY"] = key

def ask_claude(client, prompt, system):
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    return json.loads(raw)

def upload_image(img_bytes: bytes) -> str:
    """Sube imagen a fal.ai CDN y devuelve URL. Si falla, usa base64."""
    try:
        # Redimensionar si es muy grande (max 1500px) para evitar problemas
        img = Image.open(BytesIO(img_bytes))
        if max(img.size) > 1500:
            img.thumbnail((1500, 1500), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=90)
            img_bytes = buf.getvalue()

        # Subir a fal.ai CDN
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(img_bytes)
            tmp_path = f.name
        url = fal_client.upload_file(tmp_path)
        os.unlink(tmp_path)
        return url
    except Exception:
        # Fallback: base64 data URL
        import base64
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

def resize_to_bdrowa(img_bytes: bytes, formato: str) -> bytes:
    """Redimensiona y recorta al formato exacto BD ROWA."""
    fmt = FORMATS[formato]
    target_w, target_h = fmt["width"], fmt["height"]
    img = Image.open(BytesIO(img_bytes))
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h
    if img_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    elif img_ratio < target_ratio:
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    img = img.resize((target_w, target_h), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

def ts_filename(tipo: str, ext: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"bdrowa_{tipo}_{ts}.{ext}"

# ─── Interfaz ─────────────────────────────────────────────────────────────────

init_state()
claude_client = get_claude()
setup_fal()

# ── Panel izquierdo: subida de foto ───────────────────────────────────────────
col_izq, col_der = st.columns([1, 1])

with col_izq:
    st.markdown("### 📸 1. Foto del producto real")
    uploaded = st.file_uploader(
        "Sube la foto del producto (JPG, PNG)",
        type=["jpg", "jpeg", "png"],
        help="Foto clara del producto, preferiblemente con fondo neutro o blanco."
    )
    if uploaded:
        img_preview = Image.open(uploaded)
        st.image(img_preview, caption="Foto de referencia", use_container_width=True)

with col_der:
    st.markdown("### ✍️ 2. Describe la escena")
    prompt_usuario = st.text_area(
        "¿Qué quieres comunicar? (en español)",
        placeholder="Ej: Este protector solar en una playa mediterránea con arena blanca y mar azul, ambiente veraniego, espacio para poner precio",
        height=110,
    )

    tipo_contenido = st.radio(
        "Tipo de contenido:",
        ["🖼️ Imagen", "🎬 Vídeo"],
        horizontal=True,
    )
    es_video = tipo_contenido == "🎬 Vídeo"

    if es_video:
        duracion = st.radio(
            "Duración:",
            ["5 segundos (~€0.14)", "10 segundos (~€0.28)"],
            horizontal=True,
        )
        dur_val = "5" if "5" in duracion else "10"
        st.info("⏱️ El vídeo tarda 3-5 minutos en generarse.")
    else:
        formato_img = st.radio(
            "Formato de salida:",
            ["Panorama · 1080×1920 (pantalla completa)", "Header · 1080×350 (cabecera)"],
            horizontal=True,
        )
        fmt_key = "panorama" if "Panorama" in formato_img else "header"

# ── Botón de generación ───────────────────────────────────────────────────────
st.divider()
generar = st.button(
    "🚀 Generar con Claude + IA",
    type="primary",
    disabled=not (uploaded and prompt_usuario),
    use_container_width=True,
)

if generar and uploaded and prompt_usuario:

    # 1. Subir imagen de referencia a fal.ai
    with st.spinner("📤 Preparando imagen de referencia..."):
        uploaded.seek(0)
        img_bytes_orig = uploaded.read()
        image_url = upload_image(img_bytes_orig)

    # 2. Claude mejora el prompt
    with st.spinner("🧠 Claude diseñando la composición..."):
        try:
            sistema = CLAUDE_VIDEO if es_video else CLAUDE_IMAGE
            params = ask_claude(claude_client, prompt_usuario, sistema)
        except Exception as e:
            st.error(f"Error con Claude: {e}")
            st.stop()

    if es_video:
        orientacion  = params.get("orientacion", "panorama")
        prompt_ia    = params.get("prompt_video", "")
        copy_text    = params.get("copy", "")
        explicacion  = params.get("explicacion", "")
        aspect_ratio = "9:16" if orientacion == "panorama" else "16:9"
    else:
        fmt_key     = params.get("formato", fmt_key)
        prompt_ia   = params.get("prompt_kontext", "")
        copy_text   = params.get("copy", "")
        explicacion = params.get("explicacion", "")

    # Mostrar lo que Claude propone
    with st.expander("🧠 Ver propuesta de Claude", expanded=True):
        st.markdown(f"**Composición:** {explicacion}")
        st.markdown(f"**Copy sugerido:** _{copy_text}_")
        st.code(prompt_ia, language=None)

    # 3. Generar imagen o vídeo
    if es_video:
        with st.spinner("🎬 Generando vídeo con Kling AI (3-5 minutos, espera)..."):
            try:
                result = fal_client.subscribe(
                    "fal-ai/kling-video/v1.6/standard/image-to-video",
                    arguments={
                        "image_url": image_url,
                        "prompt": prompt_ia,
                        "duration": dur_val,
                        "aspect_ratio": aspect_ratio,
                    },
                )
                video_url = result["video"]["url"]
            except Exception as e:
                st.error(f"Error generando vídeo: {e}")
                st.exception(e)
                st.stop()

        with st.spinner("📥 Descargando vídeo..."):
            resp = requests.get(video_url, timeout=180)
            video_bytes = resp.content

        # Mostrar resultado
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Referencia original:**")
            st.image(img_bytes_orig, use_container_width=True)
        with c2:
            st.markdown("**Vídeo generado:**")
            st.video(video_bytes)

        filename = ts_filename(f"video_{orientacion}", "mp4")
        st.download_button(
            "⬇️ Descargar MP4 · Listo para BD ROWA",
            data=video_bytes,
            file_name=filename,
            mime="video/mp4",
            use_container_width=True,
        )

        # Guardar en historial
        st.session_state.historial.append({
            "tipo": "video",
            "thumb": img_bytes_orig,
            "video_bytes": video_bytes,
            "filename": filename,
            "copy": copy_text,
            "ts": datetime.now().strftime("%H:%M:%S"),
        })

    else:
        with st.spinner(f"🎨 Generando imagen con Flux Kontext (40-90 segundos)..."):
            try:
                result = fal_client.subscribe(
                    "fal-ai/flux-pro/kontext",
                    arguments={
                        "prompt": prompt_ia,
                        "image_url": image_url,
                    },
                )
                img_url = result["images"][0]["url"]
            except Exception as e:
                st.error(f"Error generando imagen: {e}")
                st.exception(e)
                st.stop()

        with st.spinner("📥 Descargando y ajustando formato BD ROWA..."):
            resp = requests.get(img_url, timeout=60)
            img_result = resize_to_bdrowa(resp.content, fmt_key)

        # Mostrar resultado
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Referencia original:**")
            st.image(img_bytes_orig, use_container_width=True)
        with c2:
            fmt_label = FORMATS[fmt_key]["label"]
            st.markdown(f"**Imagen generada · {fmt_label}:**")
            st.image(img_result, use_container_width=True)

        filename = ts_filename(fmt_key, "jpg")
        st.download_button(
            f"⬇️ Descargar {fmt_key.upper()} · Listo para BD ROWA",
            data=img_result,
            file_name=filename,
            mime="image/jpeg",
            use_container_width=True,
        )
        st.success(f"✅ Resolución exacta: {FORMATS[fmt_key]['width']}×{FORMATS[fmt_key]['height']} px")

        # Guardar en historial
        st.session_state.historial.append({
            "tipo": "imagen",
            "formato": fmt_key,
            "img_bytes": img_result,
            "filename": filename,
            "copy": copy_text,
            "ts": datetime.now().strftime("%H:%M:%S"),
        })

# ─── Historial de sesión ──────────────────────────────────────────────────────

if st.session_state.historial:
    st.divider()
    st.markdown("## 🗂️ Historial de esta sesión")
    st.caption("Todas las generaciones de esta sesión. Se borra al cerrar el navegador.")

    cols = st.columns(min(len(st.session_state.historial), 4))
    for i, item in enumerate(reversed(st.session_state.historial)):
        col = cols[i % 4]
        with col:
            st.markdown(f"**{item['ts']}**")
            if item["tipo"] == "imagen":
                st.image(item["img_bytes"], use_container_width=True)
                st.caption(f"{item['formato'].upper()} · _{item['copy']}_")
                st.download_button(
                    "⬇️ Descargar",
                    data=item["img_bytes"],
                    file_name=item["filename"],
                    mime="image/jpeg",
                    key=f"hist_dl_{i}",
                )
            else:
                st.image(item["thumb"], use_container_width=True)
                st.caption(f"Vídeo · _{item['copy']}_")
                st.download_button(
                    "⬇️ Descargar MP4",
                    data=item["video_bytes"],
                    file_name=item["filename"],
                    mime="video/mp4",
                    key=f"hist_dl_{i}",
                )
