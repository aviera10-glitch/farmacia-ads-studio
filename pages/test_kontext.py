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

CLAUDE_IMAGEN = """Eres el director creativo de una farmacia en Canarias, España.
El usuario tiene una FOTO REAL de un producto farmacéutico. El flujo de trabajo es:
  1. rembg elimina el fondo de la foto del producto → queda solo el producto recortado.
  2. Flux Pro genera la ESCENA de fondo (sin el producto — se añadirá después).
  3. Pillow compone el producto recortado encima de la escena generada.

Tu tarea: interpretar lo que quiere el usuario y devolver los parámetros para generar la escena de fondo.

Responde SIEMPRE en JSON puro (sin markdown):
{
  "formato": "panorama" | "header",
  "prompt_escena": "...",
  "posicion": "inferior-centro" | "inferior-izquierda" | "inferior-derecha" | "centro",
  "escala": 0.25,
  "copy": "...",
  "explicacion": "..."
}

"formato":
  - "panorama" → 1080×1920, pantalla completa vertical.
  - "header"   → 1080×350, banner horizontal.

"prompt_escena":
  - SIEMPRE en inglés, muy descriptivo.
  - REGLA DE ORO DE COMPOSICIÓN: Debes crear un ESPACIO NEGATIVO MASIVO (massive empty negative space) en primer plano o en el centro.
  - Debe incluir SIEMPRE: "A minimalist product display podium/pedestal in the center foreground for product placement, with the [DESCRIBE BACKGROUND SCENE] acting strictly as a heavily blurred backdrop."
  - Estilo fotorrealista, estudio fotográfico comercial, iluminación profesional.
  - Terminar con: "commercial advertisement background, professional photography, shallow depth of field, heavily blurred background, clear studio podium in foreground, 4K."
  - Para personas: "out of focus people in far background, no recognizable faces".

"posicion": dónde poner el producto en la escena:
  - "inferior-centro" → centrado en la parte inferior (mesas, mostradores)
  - "inferior-izquierda" → izquierda-abajo (composiciones asimétricas)
  - "inferior-derecha" → derecha-abajo
  - "centro" → centro de la imagen (para headers o cuando el fondo es neutro)

"escala": qué fracción del ancho de la imagen debe ocupar el producto. Entre 0.15 y 0.45.
  - 0.20 → producto pequeño, escena protagonista
  - 0.30 → equilibrado (recomendado)
  - 0.40 → producto grande, protagonista

"copy": Texto publicitario para estampar en la imagen. MÁXIMO ABSOLUTO 2 a 5 PALABRAS.
  - Eres el mejor copywriter del mundo.
  - Solo frases cortísimas, de impacto. Una o dos palabras por línea.
  - NUNCA escribas más de 5 palabras. Si te pasas de 5 palabras, la campaña fracasará.
  - Ejemplo malo: "Duerme rápido y despierta con energía."
  - Ejemplo bueno: "Dulces sueños." o "Descanso total."
"explicacion": 1-2 frases describiendo la composición.

─── EJEMPLOS ───

Usuario: "Chica en campus universitario con amigos comiendo y riendo, se toma un comprimido efervescente en vaso, caja en la mesa, panorama"
{
  "formato": "panorama",
  "prompt_escena": "Bright university cafeteria, out of focus people in far background laughing and eating together, no recognizable faces, warm natural daylight from large windows, massive empty negative space on a wooden table in the foreground, commercial advertisement background, professional photography, shallow depth of field, heavily blurred background, clear empty foreground, 4K.",
  "posicion": "inferior-centro",
  "escala": 0.28,
  "copy": "El alivio que te deja disfrutar\nAlmax 500mg · Efervescente",
  "explicacion": "Campus universitario de fondo muy desenfocado. La caja de producto será la única protagonista nítida en la gran mesa vacía frontal."
}

Usuario: "Playa mediterránea de verano, familia, solar, panorama, oferta 20%"
{
  "formato": "panorama",
  "prompt_escena": "Beautiful Mediterranean beach with white sand and turquoise water, out of focus people in far background playing, golden hour warm light, massive empty negative space on the sand in the foreground, commercial advertisement background, professional photography, shallow depth of field, heavily blurred background, clear empty foreground, 4K.",
  "posicion": "inferior-izquierda",
  "escala": 0.30,
  "copy": "Protégete este verano\n20% de descuento esta semana",
  "explicacion": "Playa mediterránea veraniega al fondo. El producto reinará en la amplia arena vacía del primer plano con profundidad de campo."
}
"""

CLAUDE_VIDEO = """Eres el director creativo de una farmacia en Canarias, España.
El usuario tiene una FOTO del producto y quiere un vídeo corto donde Kling AI
anima esa foto, creando movimiento cinematográfico.

Responde SIEMPRE en JSON puro (sin markdown):
{
  "orientacion": "panorama" | "landscape",
  "prompt_video": "...",
  "copy": "...",
  "explicacion": "..."
}

"prompt_video":
  - SIEMPRE en inglés. Describe el movimiento que empieza desde la foto.
  - Tipos: slow camera zoom, gentle product rotation, background elements moving
    (waves, leaves, steam, bokeh), light changing, person entering frame.
  - Terminar con: "cinematic, smooth motion, professional pharmacy advertisement, 4K."
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

def generate_scene_flux(prompt: str, formato: str) -> bytes:
    """Genera la escena de fondo con Flux Pro."""
    fmt = FORMATS[formato]
    if formato == "panorama":
        size = {"width": 1080, "height": 1920}
    else:
        size = {"width": 1400, "height": 455}

    result = fal_client.subscribe(
        "fal-ai/flux-pro/v1.1",
        arguments={
            "prompt": prompt,
            "image_size": size,
            "num_images": 1,
            "safety_tolerance": "3",
            "output_format": "jpeg",
        },
    )
    url = result["images"][0]["url"]
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content

from PIL import ImageDraw, ImageFont
import urllib.request
import os

def compose_product_on_scene(
    scene_bytes: bytes,
    product_png_bytes: bytes,
    formato: str,
    posicion: str,
    escala: float,
    prompt_escena: str,
    copy_text: str = "",
) -> bytes:
    """Compone el producto recortado encima de la escena."""
    fmt = FORMATS[formato]
    target_w, target_h = fmt["width"], fmt["height"]

    # Preparar escena al tamaño exacto BD ROWA
    scene = Image.open(BytesIO(scene_bytes)).convert("RGBA")
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

    # Preparar producto recortado
    product = Image.open(BytesIO(product_png_bytes)).convert("RGBA")
    prod_w = int(target_w * escala)
    prod_h = int(prod_w * product.height / product.width)
    product = product.resize((prod_w, prod_h), Image.LANCZOS)

    # Calcular posición
    margin_x = int(target_w * 0.05)
    margin_y = int(target_h * 0.04)

    pos_map = {
        "inferior-centro":    ((target_w - prod_w) // 2, target_h - prod_h - margin_y),
        "inferior-izquierda": (margin_x, target_h - prod_h - margin_y),
        "inferior-derecha":   (target_w - prod_w - margin_x, target_h - prod_h - margin_y),
        "centro":             ((target_w - prod_w) // 2, (target_h - prod_h) // 2),
    }
    x, y = pos_map.get(posicion, pos_map["inferior-centro"])

    # Sombra básica para guiar a la IA
    drop_shadow = Image.new("RGBA", (prod_w + 40, prod_h + 40), (0, 0, 0, 0))
    drop_layer = Image.new("RGBA", (prod_w, int(prod_h * 0.15)), (0, 0, 0, 100))
    drop_shadow.paste(drop_layer, (20, 20))
    drop_shadow = drop_shadow.filter(ImageFilter.GaussianBlur(8))
    scene.paste(drop_shadow, (x - 20, y + int(prod_h * 0.85) - 20), drop_shadow)

    # Pegar producto original
    scene.paste(product, (x, y), product)

    # Convertir a JPEG (Montaje bruto)
    rough_img = Image.new("RGB", (target_w, target_h), (255, 255, 255))
    rough_img.paste(scene, mask=scene.split()[3])
    buf = BytesIO()
    rough_img.save(buf, format="JPEG", quality=95)
    rough_bytes = buf.getvalue()

    # --- Refinamiento mágico con Fal AI (Image-to-Image) ---
    try:
        rough_url = upload_to_fal(rough_bytes)
        result = fal_client.subscribe(
            "fal-ai/flux/dev/image-to-image",
            arguments={
                "image_url": rough_url,
                "prompt": prompt_escena + ", perfect realistic lighting, organic integration of objects, soft natural shadows directly on the surface, strictly NO new faces or complex objects in the foreground, photorealistic.",
                "strength": 0.20, # Baja variación: mantiene el producto intacto pero lo funde con el espacio 3D
                "image_size": "landscape_4_3" if formato == "header" else "portrait_9_16",
                "num_inference_steps": 28,
            }
        )
        refined_url = result["images"][0]["url"]
        resp_ref = requests.get(refined_url, timeout=60)
        resp_ref.raise_for_status()
        scene = Image.open(BytesIO(resp_ref.content)).convert("RGBA")
        scene = scene.resize((target_w, target_h), Image.LANCZOS)
    except Exception as e:
        print(f"Error en fal image-to-image blending, usando versión bruta: {e}")
        scene = rough_img.convert("RGBA")

    # 4. Text Overlay / Copy Text render
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
            # Fallback for older Pillow
            text_w, text_h = draw.textsize(copy_text, font=font)
        
        text_x = (target_w - text_w) // 2
        text_y = int(target_h * 0.06)
        
        # Draw shadow
        draw.text((text_x + 3, text_y + 3), copy_text, font=font, fill=(0, 0, 0, 200), align="center")
        # Draw text
        draw.text((text_x, text_y), copy_text, font=font, fill=(255, 255, 255, 255), align="center")

    # Convertir a JPEG
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
    st.markdown("### ✍️ 2. Describe la escena")
    prompt_usuario = st.text_area(
        "¿Qué quieres comunicar? (en español)",
        placeholder="Ej: Chica joven en campus universitario con amigos, comiendo y riendo, se toma un comprimido efervescente en vaso, caja en la mesa, panorama",
        height=120,
    )
    tipo = st.radio("Tipo de contenido:", ["🖼️ Imagen", "🎬 Vídeo"], horizontal=True)
    es_video = tipo == "🎬 Vídeo"

    if es_video:
        dur = st.radio("Duración:", ["5 seg (~€0.14)", "10 seg (~€0.28)"], horizontal=True)
        dur_val = "5" if "5" in dur else "10"
        st.info("⏱️ El vídeo tarda 3-5 minutos.")
    else:
        st.info("🔧 **Cómo funciona:** rembg recorta el producto → Flux genera la escena → se componen automáticamente.")

st.divider()
_tiene_imagen = bool(uploaded or url_prod)
generar = st.button(
    "🚀 Generar con Claude + IA",
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

    if es_video:
        # ── Modo Vídeo: Kling image-to-video ─────────────────────────────────
        with st.spinner("🧠 Claude diseñando el movimiento..."):
            params = ask_claude(claude_client, prompt_usuario, CLAUDE_VIDEO)

        orientacion  = params.get("orientacion", "panorama")
        prompt_video = params.get("prompt_video", "")
        copy_text    = params.get("copy", "")
        explicacion  = params.get("explicacion", "")
        aspect_ratio = "9:16" if orientacion == "panorama" else "16:9"

        with st.expander("🧠 Propuesta de Claude", expanded=True):
            st.markdown(f"**Animación:** {explicacion}")
            st.markdown(f"**Copy:** _{copy_text}_")

        with st.spinner("📤 Subiendo foto de referencia..."):
            image_url = upload_to_fal(img_bytes_orig)

        with st.spinner(f"🎬 Generando vídeo con Kling AI ({dur_val}s) — 3-5 minutos..."):
            try:
                result = fal_client.subscribe(
                    "fal-ai/kling-video/v1.6/standard/image-to-video",
                    arguments={
                        "image_url": image_url,
                        "prompt": prompt_video,
                        "duration": dur_val,
                        "aspect_ratio": aspect_ratio,
                    },
                )
                video_url = result["video"]["url"]
            except Exception as e:
                st.error(f"Error generando vídeo: {e}")
                st.exception(e)
                st.stop()

        video_bytes = requests.get(video_url, timeout=180).content

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Referencia:**")
            st.image(img_bytes_orig, use_container_width=True)
        with c2:
            st.markdown("**Vídeo generado:**")
            st.video(video_bytes)

        filename = ts_filename(f"video_{orientacion}", "mp4")
        st.download_button("⬇️ Descargar MP4 · BD ROWA", video_bytes, filename, "video/mp4", use_container_width=True)

        st.session_state.historial.append({
            "tipo": "video", "thumb": img_bytes_orig,
            "video_bytes": video_bytes, "filename": filename,
            "copy": copy_text, "ts": datetime.now().strftime("%H:%M:%S"),
        })

    else:
        # ── Modo Imagen: pipeline 3 pasos ─────────────────────────────────────

        # Paso 1: Claude diseña
        with st.spinner("🧠 Claude diseñando la composición..."):
            try:
                params = ask_claude(claude_client, prompt_usuario, CLAUDE_IMAGEN)
            except Exception as e:
                st.error(f"Error con Claude: {e}")
                st.stop()

        fmt_key     = params.get("formato", "panorama")
        prompt_esc  = params.get("prompt_escena", "")
        posicion    = params.get("posicion", "inferior-centro")
        escala      = float(params.get("escala", 0.30))
        copy_text   = params.get("copy", "")
        explicacion = params.get("explicacion", "")

        with st.expander("🧠 Propuesta de Claude", expanded=True):
            st.markdown(f"**Composición:** {explicacion}")
            st.markdown(f"**Copy:** _{copy_text}_")
            st.markdown(f"**Posición producto:** `{posicion}` · **Escala:** `{int(escala*100)}%` del ancho")

        # Paso 2: Eliminar fondo del producto
        with st.spinner("✂️ Eliminando fondo del producto (rembg)..."):
            try:
                product_cutout = remove_background(img_bytes_orig)
            except Exception as e:
                st.error(f"Error eliminando fondo: {e}")
                st.stop()

        # Paso 3: Generar escena con Flux Pro
        fmt_label = FORMATS[fmt_key]["label"]
        with st.spinner(f"🎨 Generando escena con Flux Pro ({fmt_label})..."):
            try:
                scene_bytes = generate_scene_flux(prompt_esc, fmt_key)
            except Exception as e:
                st.error(f"Error generando escena: {e}")
                st.stop()

        # Paso 4: Componer
        with st.spinner("🖼️ Integrando producto orgánicamente (IA Image-to-Image)..."):
            try:
                final_bytes = compose_product_on_scene(
                    scene_bytes, product_cutout, fmt_key, posicion, escala, prompt_esc, copy_text
                )
            except Exception as e:
                st.error(f"Error en composición: {e}")
                st.stop()

        # Resultado
        st.divider()
        st.markdown("## ✅ Resultado")

        t1, t2, t3 = st.columns(3)
        with t1:
            st.markdown("**Producto original:**")
            st.image(img_bytes_orig, use_container_width=True)
        with t2:
            st.markdown("**Escena generada:**")
            st.image(scene_bytes, use_container_width=True)
        with t3:
            st.markdown(f"**Composición final · {fmt_label}:**")
            st.image(final_bytes, use_container_width=True)

        filename = ts_filename(fmt_key, "jpg")
        st.download_button(
            f"⬇️ Descargar {fmt_key.upper()} · Listo para BD ROWA",
            final_bytes, filename, "image/jpeg", use_container_width=True,
        )
        st.success(f"✅ Resolución exacta: {FORMATS[fmt_key]['width']}×{FORMATS[fmt_key]['height']} px")

        st.session_state.historial.append({
            "tipo": "imagen", "formato": fmt_key,
            "img_bytes": final_bytes, "filename": filename,
            "copy": copy_text, "ts": datetime.now().strftime("%H:%M:%S"),
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
            if item["tipo"] == "imagen":
                st.image(item["img_bytes"], use_container_width=True)
                st.caption(f"{item['formato'].upper()} · _{item['copy']}_")
                st.download_button("⬇️", item["img_bytes"], item["filename"],
                                   "image/jpeg", key=f"h_{i}")
            else:
                st.image(item["thumb"], use_container_width=True)
                st.caption(f"Vídeo · _{item['copy']}_")
                st.download_button("⬇️ MP4", item["video_bytes"], item["filename"],
                                   "video/mp4", key=f"h_{i}")
