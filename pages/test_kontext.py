"""
Producto Real · Composición con producto real
----------------------------------------------
Pipeline:
  Imagen → rembg elimina fondo → Flux Pro genera escena → Pillow compone
  Vídeo  → Kling anima la foto del producto en la escena
"""

import streamlit as st
import anthropic
import fal_client
import requests
import tempfile
import os
import json
from PIL import Image, ImageFilter
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Producto Real · Farmacia Ads", page_icon="📦", layout="wide")
st.title("📦 Producto Real → Composición publicitaria")
st.caption("Sube la foto del producto · Claude diseña la escena · IA genera y compone el resultado final")

# ─── Formatos BD ROWA ─────────────────────────────────────────────────────────

FORMATS = {
    "panorama": {"width": 1080, "height": 1920, "label": "Pantalla completa · 1080×1920"},
    "header":   {"width": 1080, "height": 350,  "label": "Cabecera · 1080×350"},
}

# ─── Sistema Claude ───────────────────────────────────────────────────────────

CLAUDE_CAMPAIGN = """Eres el director creativo de una farmacia en Canarias, España.
El usuario tiene una FOTO REAL de un producto farmacéutico y quiere lanzar una GRAN CAMPAÑA MULTICANAL automática.

El flujo de tu trabajo es generar los textos directores para 4 piezas de contenido simultáneas:
  1. POSTER VERTICAL (1080x1920) para la pantalla del escaparate BD ROWA.
  2. BANNER WEB HORIZONTAL (1080x350) para la portada de la web de la farmacia.
  3. VÍDEO VERTICAL (1080x1920) para cartelería digital.
  4. COPY DE REDES SOCIALES listo para Instagram/Facebook.

Responde SIEMPRE en JSON puro (sin markdown, formato exacto):
{
  "poster_prompt": "...",
  "banner_prompt": "...",
  "video_prompt": "...",
  "poster_copy": "Slogan corto",
  "banner_copy": "Slogan corto",
  "social_copy": "Texto largo persuasivo...",
  "explicacion": "..."
}

--- REGLAS DE GENERACIÓN DE IMÁGENES (poster_prompt y banner_prompt) ---
- SIEMPRE en inglés, muy descriptivo.
- REGLA DE ORO DE IMAGEN: Composición asimétrica donde "the product is prominently placed in the foreground". No pidas un espacio "vacío", pide que el producto esté ahí posado prominentemente. El fondo opuesto debe estar "heavily blurred".
- Terminar imágenes con: "commercial advertisement, asymmetric composition, the product is prominently placed in the foreground, daylight studio, dramatic studio lighting on the product, shallow depth of field, heavily blurred background, 4K."

--- REGLAS DE GENERACIÓN DE VÍDEO (video_prompt) ---
- SIEMPRE en inglés. Es un prompt de Image-to-Video. 
- Describe el movimiento sutil desde la foto base (ej. "slow camera zoom", "gentle product rotation", "waves moving gently").
- Terminar vídeos con: "cinematic, smooth motion, professional pharmacy advertisement, 4K."

--- REGLAS DE COPY (Textos superpuestos en imágenes) ---
- poster_copy y banner_copy: MÁXIMO ABSOLUTO 2 a 5 PALABRAS. 
- NUNCA pongas punto final "." en estos eslóganes cortos.
- Ejemplo bueno: "Dulces sueños" o "Descanso total"

--- REGLAS SOCIAL COPY (Texto de feed) ---
- social_copy: Texto persuasivo, amigable y profesional para publicar en Instagram o Facebook.
- Usa 2 o 3 emojis relevantes. Incluye 3 hashtags comerciales, uno siempre debe ser #FarmaciaLaOliva.
- Longitud: 2 a 4 párrafos cortos.
"""

# ─── Helpers ──────────────────────────────────────────────────────────────────

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
        model="claude-sonnet-4-6", max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    for tag in ["```json", "```"]:
        if tag in raw:
            raw = raw.split(tag)[1].split("```")[0].strip()
            break
    return json.loads(raw)

def upload_to_fal(img_bytes: bytes) -> str:
    """Sube imagen a fal.ai CDN. Redimensiona si es muy grande."""
    img = Image.open(BytesIO(img_bytes))
    if max(img.size) > 1500:
        img.thumbnail((1500, 1500), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        img_bytes = buf.getvalue()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(img_bytes)
        tmp = f.name
    try:
        url = fal_client.upload_file(tmp)
    finally:
        os.unlink(tmp)
    return url

def remove_background(img_bytes: bytes) -> bytes:
    """Elimina el fondo usando rembg. Devuelve PNG con transparencia."""
    from rembg import remove
    return remove(img_bytes)

from PIL import ImageDraw, ImageFont
import urllib.request
import os

def generate_advertisement_with_subject(
    reference_image_bytes: bytes,
    prompt_escena: str,
    formato: str,
    copy_text: str = ""
) -> bytes:
    """Utiliza Flux Subject Reference para dibujar el producto directamente en la escena 3D."""
    
    fmt = FORMATS[formato]
    target_w, target_h = fmt["width"], fmt["height"]
    
    # 1. Subir la imagen de referencia (PNG sin fondo)
    ref_url = upload_to_fal(reference_image_bytes)
    
    # 2. Llamada mágica a Flux Subject
    # Le pedimos que genere la imagen completa, usando ref_url como identidad visual del objeto
    result = fal_client.subscribe(
        "fal-ai/flux-subject",
        arguments={
            "image_url": ref_url,
            "prompt": prompt_escena + ", perfect realistic lighting, organic integration of objects, photorealistic.",
            "image_size": "landscape_4_3" if formato == "header" else "portrait_16_9",
            "output_format": "jpeg"
        }
    )
    
    final_url = result["images"][0]["url"]
    resp = requests.get(final_url, timeout=60)
    resp.raise_for_status()
    
    scene = Image.open(BytesIO(resp.content)).convert("RGBA")
    
    # Asegurar tamaño exacto BD ROWA crop/resize
    ratio_s = scene.width / scene.height
    ratio_t = target_w / target_h
    if ratio_s > ratio_t:
        new_w = int(scene.height * ratio_t)
        left = (scene.width - new_w) // 2
        scene = scene.crop((left, 0, left + new_w, scene.height))
    else:
        new_h = int(scene.width / ratio_t)
        top = (scene.height - new_h) // 2
        scene = scene.crop((0, top, scene.width, top + new_h))
    scene = scene.resize((target_w, target_h), Image.LANCZOS)

    # 3. Text Overlay / Copy Text render
    if copy_text:
        try:
            font_path = "/tmp/Roboto-Bold.ttf"
            if not os.path.exists(font_path):
                urllib.request.urlretrieve("https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf", font_path)
            font_size = int(target_h * 0.035) if formato == "panorama" else int(target_h * 0.12)
            font = ImageFont.truetype(font_path, font_size)
        except:
            font = ImageFont.load_default()
            
        # Add translucent gradient banner for readability behind text
        overlay = Image.new('RGBA', scene.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        banner_h = int(target_h * 0.25) if formato == "panorama" else int(target_h * 0.45)
        d.rectangle([0, 0, target_w, banner_h], fill=(0, 0, 0, 110))
        scene = Image.alpha_composite(scene, overlay)
        
        draw = ImageDraw.Draw(scene)
        
        try:
            bbox = draw.textbbox((0, 0), copy_text, font=font, align="center")
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except AttributeError:
            text_w, text_h = draw.textsize(copy_text, font=font)
        
        text_x = (target_w - text_w) // 2
        text_y = int(target_h * 0.06)
        
        draw.text((text_x + 3, text_y + 3), copy_text, font=font, fill=(0, 0, 0, 200), align="center")
        draw.text((text_x, text_y), copy_text, font=font, fill=(255, 255, 255, 255), align="center")

    final = Image.new("RGB", (target_w, target_h), (255, 255, 255))
    final.paste(scene, mask=scene.split()[3])
    buf = BytesIO()
    final.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def ts_filename(tag: str, ext: str) -> str:
    return f"bdrowa_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

# ─── Interfaz ─────────────────────────────────────────────────────────────────

init_state()
claude_client = get_claude()
setup_fal()

col_izq, col_der = st.columns([1, 1])

with col_izq:
    st.markdown("### 📸 1. Foto del producto real")
    uploaded = st.file_uploader(
        "Sube la foto del producto (JPG, PNG)",
        type=["jpg", "jpeg", "png"],
    )
    url_prod = st.text_input(
        "O pega una URL de imagen (alternativa a subir archivo)",
        placeholder="https://ejemplo.com/producto.jpg",
    )
    # Previsualizar
    if uploaded:
        st.image(Image.open(uploaded), caption="Referencia", use_container_width=True)
    elif url_prod:
        try:
            _hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            _r = requests.get(url_prod, timeout=10, headers=_hdrs)
            _r.raise_for_status()
            st.image(Image.open(BytesIO(_r.content)), caption="Referencia (URL)", use_container_width=True)
        except Exception as _e:
            st.warning(f"No se pudo cargar la imagen: {_e}")

with col_der:
    st.markdown("### ✍️ 2. Describe la idea de la campaña")
    prompt_usuario = st.text_area(
        "¿Qué quieres comunicar? (en español)",
        placeholder="Ej: Campaña de verano fresca y dinámica para Isdin, familia en la playa, queremos destacar la protección total 50+",
        height=120,
    )
    
    st.info("🪄 **Generación Multicanal:** Con un solo clic se creará el Póster Vertical, el Banner Web, el Vídeo Animado y el Texto para Redes Sociales.")

st.divider()
_tiene_imagen = bool(uploaded or url_prod)
generar = st.button(
    "🚀 Generar Campaña Completa (≈ 3 minutos)",
    type="primary",
    disabled=not (_tiene_imagen and prompt_usuario),
    use_container_width=True,
)

if generar and _tiene_imagen and prompt_usuario:
    if uploaded:
        uploaded.seek(0)
        img_bytes_orig = uploaded.read()
    else:
        with st.spinner("⬇️ Descargando imagen desde URL..."):
            try:
                _hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                _resp = requests.get(url_prod, timeout=15, headers=_hdrs)
                _resp.raise_for_status()
                img_bytes_orig = _resp.content
            except Exception as _e:
                st.error(f"Error descargando imagen: {_e}")
                st.stop()

    # ── Generación de Campaña Multicanal ─────────────────────────────────
    with st.spinner("🧠 Claude diseñando la estrategia de la campaña..."):
        try:
            params = ask_claude(claude_client, prompt_usuario, CLAUDE_CAMPAIGN)
        except Exception as e:
            st.error(f"Error con Claude: {e}")
            st.stop()

    poster_prompt = params.get("poster_prompt", "")
    banner_prompt = params.get("banner_prompt", "")
    video_prompt  = params.get("video_prompt", "")
    poster_copy   = params.get("poster_copy", "")
    banner_copy   = params.get("banner_copy", "")
    social_copy   = params.get("social_copy", "")
    explicacion   = params.get("explicacion", "")

    with st.expander("🧠 Estrategia de Campaña de Claude", expanded=True):
        st.markdown(f"**Justificación:** {explicacion}")
        st.markdown(f"**Copy para Redes:**\n\n{social_copy}")

    # Paso 2: Aislar fondo original para limpiar referencia
    with st.spinner("✂️ Limpiando la foto de referencia (rembg) para evitar distorsiones..."):
        try:
            product_cutout = remove_background(img_bytes_orig)
            
            # IMPORTANTE: Muchos modelos de Subject Reference (como Flux) se vuelven locos
            # o distorsionan la imagen si reciben un PNG con canal Alfa transparente.
            # Debemos pegarlo sobre un fondo sólido (blanco) antes de enviarlo a la IA.
            cutout_img = Image.open(BytesIO(product_cutout)).convert("RGBA")
            solid_bg = Image.new("RGB", cutout_img.size, (255, 255, 255))
            solid_bg.paste(cutout_img, mask=cutout_img.split()[3])
            
            buf = BytesIO()
            solid_bg.save(buf, format="JPEG", quality=95)
            product_clean_jpeg = buf.getvalue()
            
        except Exception as e:
            st.error(f"Error preparando fondo de referencia: {e}")
            st.stop()

    with st.spinner("📤 Subiendo foto de referencia segura a servidores..."):
        try:
            ref_url = upload_to_fal(product_clean_jpeg)
        except Exception as e:
            st.error(f"Error subiendo referencia: {e}")
            st.stop()

    # Paso 3: Generar Poster, Banner y Video en Paralelo
    import concurrent.futures

    def generate_poster():
        return generate_advertisement_with_subject(
            reference_image_bytes=product_clean_jpeg,
            prompt_escena=poster_prompt,
            formato="panorama",
            copy_text=poster_copy
        )

    def generate_banner():
        return generate_advertisement_with_subject(
            reference_image_bytes=product_clean_jpeg,
            prompt_escena=banner_prompt,
            formato="header",
            copy_text=banner_copy
        )

    def generate_video():
        result = fal_client.subscribe(
            "fal-ai/kling-video/v1.6/standard/image-to-video",
            arguments={
                "image_url": ref_url,
                "prompt": video_prompt,
                "duration": "5",
                "aspect_ratio": "9:16",
            },
        )
        video_url_res = result["video"]["url"]
        return requests.get(video_url_res, timeout=180).content

    with st.spinner("🎨 Generando todas las piezas visuales en paralelo (Póster, Banner y Vídeo)... Esto tomará unos 3 minutos."):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_poster = executor.submit(generate_poster)
            future_banner = executor.submit(generate_banner)
            future_video  = executor.submit(generate_video)
            
            try:
                poster_bytes = future_poster.result()
                banner_bytes = future_banner.result()
                video_bytes  = future_video.result()
            except Exception as e:
                st.error(f"Falló la generación concurrente: {e}")
                st.stop()

    st.divider()    
    st.markdown("## ✅ Dashboard de Campaña Multicanal")
    
    st.info("💬 **Copia este texto para tus redes sociales (Instagram/Facebook)**:")
    st.code(social_copy, language="markdown")

    st.markdown("### 🖼️ Piezas Visuales")
    c1, c2, c3 = st.columns([1, 1, 1])
    
    with c1:
        st.markdown("**1. PÓSTER VERTICAL (BD ROWA)**")
        st.image(poster_bytes, use_container_width=True)
        fn_poster = ts_filename("panorama", "jpg")
        st.download_button("⬇️ Descargar JPGE 1080x1920", poster_bytes, fn_poster, "image/jpeg", use_container_width=True)

    with c2:
        st.markdown("**2. BANNER HORIZONTAL (WEB)**")
        st.image(banner_bytes, use_container_width=True)
        fn_banner = ts_filename("header", "jpg")
        st.download_button("⬇️ Descargar JPGE 1080x350", banner_bytes, fn_banner, "image/jpeg", use_container_width=True)
        
    with c3:
        st.markdown("**3. VÍDEO VERTICAL (BD ROWA)**")
        st.video(video_bytes)
        fn_vid = ts_filename("video_panorama", "mp4")
        st.download_button("⬇️ Descargar MP4 1080x1920", video_bytes, fn_vid, "video/mp4", use_container_width=True)

    # El historial se puede guardar como un resumen
    st.session_state.historial.append({
        "tipo": "campaña", "thumb": img_bytes_orig,
        "ts": datetime.now().strftime("%H:%M:%S"),
        "copy": social_copy[:30] + "..."
    })

# ─── Historial de sesión ──────────────────────────────────────────────────────

if st.session_state.historial:
    st.divider()
    st.markdown("## 🗂️ Historial de esta sesión")
    n = min(len(st.session_state.historial), 4)
    cols = st.columns(n)
    for i, item in enumerate(reversed(st.session_state.historial)):
        with cols[i % n]:
            st.markdown(f"**{item['ts']}**")
            if item.get("tipo") == "campaña":
                st.image(item["thumb"], use_container_width=True)
                st.caption(f"Campaña Múltiple · _{item.get('copy', '')[:30]}..._")
            elif item.get("tipo") == "imagen":
                st.image(item["img_bytes"], use_container_width=True)
                st.caption(f"{item.get('formato', '').upper()} · _{item.get('copy', '')[:30]}..._")
                st.download_button("⬇️", item["img_bytes"], item["filename"],
                                   "image/jpeg", key=f"h_{i}")
            else:
                st.image(item["thumb"], use_container_width=True)
                st.caption(f"Vídeo · _{item.get('copy', '')[:30]}..._")
                st.download_button("⬇️ MP4", item.get("video_bytes", b""), item.get("filename", "video.mp4"),
                                   "video/mp4", key=f"h_{i}")
