"""
Farmacia Ads Studio
-------------------
Crea anuncios para pantallas BD ROWA usando IA (Claude + Flux).
Formatos soportados:
  - Panorama: 1080 x 1920 px (pantalla completa)
  - Header:   1080 x 350 px  (cabecera)
"""

import streamlit as st
import anthropic
import fal_client
import requests
from PIL import Image
from io import BytesIO
import json
import os
from datetime import datetime

# ─── Configuración de página ─────────────────────────────────────────────────

st.set_page_config(
    page_title="Farmacia Ads Studio",
    page_icon="💊",
    layout="centered",
)

st.markdown("""
<style>
    .block-container { max-width: 860px; padding-top: 2rem; }
    .stDownloadButton > button {
        background-color: #0066cc;
        color: white;
        border-radius: 8px;
        width: 100%;
        font-weight: bold;
    }
    .stDownloadButton > button:hover { background-color: #0052a3; }
    .format-tag {
        display: inline-block;
        background: #e8f0fe;
        color: #1a56db;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.82em;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ─── Formatos BD ROWA ─────────────────────────────────────────────────────────

FORMATS = {
    "panorama": {
        "width": 1080,
        "height": 1920,
        "label": "Pantalla completa · 1080×1920 px",
        # Para Flux: usamos directamente este ratio (9:16 portrait)
        "gen_width": 1080,
        "gen_height": 1920,
    },
    "header": {
        "width": 1080,
        "height": 350,
        "label": "Cabecera · 1080×350 px",
        # Flux genera landscape y luego recortamos al ratio correcto
        "gen_width": 1400,
        "gen_height": 455,
    },
}

# ─── Prompt de sistema para Claude ───────────────────────────────────────────

CLAUDE_SYSTEM = """Eres el director creativo de una farmacia en Canarias, España.
Tu tarea es interpretar los deseos del farmacéutico y convertirlos en parámetros
precisos para generar imágenes publicitarias con el modelo de imagen Flux de fal.ai.

Responde SIEMPRE en JSON puro (sin markdown, sin explicaciones fuera del JSON):
{
  "formato": "panorama" | "header",
  "prompt_flux": "...",
  "copy": "...",
  "explicacion": "..."
}

Definición de cada campo:

"formato":
  - "panorama" → pantalla completa vertical (1080×1920). Para campañas principales,
    productos estrella, composiciones con escena.
  - "header" → banner horizontal (1080×350). Para ofertas rápidas, recordatorios,
    información puntual.
  - Si el usuario no especifica, elige el más adecuado según el contenido.

"prompt_flux":
  - SIEMPRE en inglés, muy descriptivo y fotorrealista.
  - Estructura: [escena principal], [producto/sujeto], [detalles visuales],
    [iluminación], [estilo], [uso final].
  - SIEMPRE terminar con: "commercial pharmacy advertisement, high-end product
    photography, 4K, clean and professional."
  - Para personas: "no recognizable faces", "diverse people", "lifestyle photography".
  - Para promociones: añadir "ample empty space for text and price overlay".
  - Nunca marcas de competidores. Nunca caras reconocibles.

"copy":
  - Texto publicitario en español, máximo 2 líneas cortas.
  - Estilo directo y profesional.
  - Si hay descuento, incluirlo (ej: "20% dto. esta semana").

"explicacion":
  - 1-2 frases en español describiendo la composición visual propuesta.

─── CONTEXTO DE PRODUCTOS FRECUENTES ───

Protectores solares: escenas de playa mediterránea, familia en verano, piel luminosa.
Antigripales / vitaminas: ambiente de invierno, familia en casa, bienestar.
Piojos (antipiojos): cuarto de baño, madre/padre cuidando a hijo pequeño, ambiente limpio.
Sillas de ruedas / ortopedia: movilidad, independencia, espacios amplios y accesibles.
Almax / antiácidos: después de comida, bienestar digestivo, estilo minimalista.
Frendol / analgésicos: alivio, tranquilidad, personas activas.
Vitaminas / suplementos: energía, deporte, naturaleza.
Higiene bebé: ternura, limpieza, colores suaves.

─── EJEMPLOS DE INTERPRETACIÓN ───

Usuario: "Solar SPF50 panorama con oferta 20%"
Respuesta formato:
{
  "formato": "panorama",
  "prompt_flux": "Sunscreen bottle SPF50 on sandy Mediterranean beach, golden hour light, sea in background, turquoise water, sunglasses beside the bottle, warm tones, ample empty space at top for text overlay, commercial pharmacy advertisement, high-end product photography, 4K, clean and professional.",
  "copy": "Protégete este verano\n20% de descuento esta semana",
  "explicacion": "Producto en primer plano sobre arena de playa mediterránea, con luz cálida de atardecer y espacio superior para añadir el precio en la plataforma BD ROWA."
}

Usuario: "Campaña de piojos para niños, header"
{
  "formato": "header",
  "prompt_flux": "Bathroom scene, parent gently combing child's hair, warm bathroom lighting, clean white tiles, hair care products on shelf, caring and hygienic atmosphere, no recognizable faces, lifestyle photography, commercial pharmacy advertisement, high-end product photography, 4K, clean and professional.",
  "copy": "Campaña antipiojos\nSolución efectiva para toda la familia",
  "explicacion": "Escena de baño cálida con padre/madre peinando a su hijo, transmitiendo cuidado y solución sin alarmismo."
}
"""

# ─── Inicialización de estado ─────────────────────────────────────────────────

def init_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None


# ─── Clientes API ─────────────────────────────────────────────────────────────

@st.cache_resource
def get_anthropic_client():
    key = st.secrets.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        st.error("⚠️ Falta ANTHROPIC_API_KEY en `.streamlit/secrets.toml`")
        st.stop()
    return anthropic.Anthropic(api_key=key)


def setup_fal():
    key = st.secrets.get("FAL_KEY") or os.getenv("FAL_KEY", "")
    if not key:
        st.error("⚠️ Falta FAL_KEY en `.streamlit/secrets.toml`")
        st.stop()
    os.environ["FAL_KEY"] = key


# ─── Lógica de generación ─────────────────────────────────────────────────────

def ask_claude(client, prompt: str) -> dict:
    """Claude interpreta el prompt y devuelve parámetros de imagen."""
    response = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=1024,
        system=CLAUDE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    # Limpiar si Claude envuelve en markdown
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    return json.loads(raw)


def generate_image_flux(flux_prompt: str, formato: str) -> bytes:
    """Genera imagen con fal.ai Flux Pro y la ajusta al formato BD ROWA exacto."""
    fmt = FORMATS[formato]

    result = fal_client.run(
        "fal-ai/flux-pro/v1.1",
        arguments={
            "prompt": flux_prompt,
            "image_size": {
                "width": fmt["gen_width"],
                "height": fmt["gen_height"],
            },
            "num_images": 1,
            "safety_tolerance": "3",
            "output_format": "jpeg",
        },
    )

    image_url = result["images"][0]["url"]
    resp = requests.get(image_url, timeout=60)
    resp.raise_for_status()

    # Ajuste preciso al formato BD ROWA
    img = Image.open(BytesIO(resp.content))
    target_w, target_h = fmt["width"], fmt["height"]

    # Smart crop para mantener la composición central
    if img.size != (target_w, target_h):
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


def make_filename(formato: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"bdrowa_{formato}_{ts}.jpg"


# ─── Interfaz principal ───────────────────────────────────────────────────────

def main():
    init_state()
    claude_client = get_anthropic_client()
    setup_fal()

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 💊 Farmacia Ads Studio")
        st.caption("Pantallas BD ROWA · Farmacia La Oliva")
        st.divider()

        st.markdown("### 💡 Ejemplos rápidos")
        examples = [
            "Protector solar SPF50, escena de playa, panorama, oferta 20%",
            "Campaña antipiojos, niño en baño, header",
            "Almax, composición minimalista limpia, panorama",
            "Frendol alivio rápido, persona activa, header",
            "Silla de ruedas, independencia y movilidad, panorama",
            "Vitamina C efervescente para el invierno, panorama",
            "Gafas de sol y solar, lifestyle playa, panorama",
            "Oferta 2x1 en antigripales, banner rápido, header",
        ]
        for ex in examples:
            if st.button(ex, key=f"ex_{ex[:25]}", use_container_width=True):
                st.session_state.pending_prompt = ex
                st.rerun()

        st.divider()
        st.markdown("### 📐 Formatos BD ROWA")
        st.markdown("""
| Tipo | Dimensiones |
|---|---|
| Panorama | 1080 × 1920 px |
| Header | 1080 × 350 px |
| Archivos | JPG, PNG, PDF |
        """)
        st.divider()
        st.markdown("### 💬 Cómo usar")
        st.markdown("""
Escribe en el chat describiendo el anuncio que quieres:
- Producto
- Escena o ambiente
- Formato (panorama / header)
- Promoción si aplica

La IA interpreta, genera y te da el archivo listo para subir a BD ROWA.
        """)

    # ── Encabezado principal ──────────────────────────────────────────────────
    st.title("💊 Farmacia Ads Studio")
    st.caption("Crea anuncios para tus pantallas BD ROWA · Escribe lo que necesitas abajo")

    if not st.session_state.messages:
        st.info(
            "👋 **Empieza describiendo tu anuncio.** "
            "Por ejemplo: *'Protector solar SPF50 con escena de playa mediterránea, "
            "pantalla completa, con descuento del 20%'*"
        )

    # ── Historial de mensajes ─────────────────────────────────────────────────
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("image_bytes"):
                st.image(
                    msg["image_bytes"],
                    caption=FORMATS[msg["formato"]]["label"],
                    use_container_width=True,
                )
                st.download_button(
                    label=f"⬇️ Descargar {msg['formato'].upper()} · Listo para BD ROWA",
                    data=msg["image_bytes"],
                    file_name=msg["filename"],
                    mime="image/jpeg",
                    key=f"dl_{i}_{msg['filename']}",
                )

    # ── Input de chat ─────────────────────────────────────────────────────────
    pending = st.session_state.pop("pending_prompt", None)
    user_input = st.chat_input(
        "Describe tu anuncio... (producto, escena, formato, promoción)"
    )

    prompt = user_input or pending
    if not prompt:
        return

    # Mostrar mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generar respuesta
    with st.chat_message("assistant"):

        # 1. Claude interpreta el prompt
        with st.spinner("🧠 Interpretando con Claude..."):
            try:
                params = ask_claude(claude_client, prompt)
            except Exception as e:
                st.error(f"Error con Claude: {e}")
                return

        formato = params.get("formato", "panorama")
        flux_prompt = params.get("prompt_flux", "")
        copy_text = params.get("copy", "")
        explicacion = params.get("explicacion", "")
        fmt_label = FORMATS[formato]["label"]

        # Mostrar interpretación
        info_text = (
            f"**Formato:** {fmt_label}  \n"
            f"**Composición:** {explicacion}  \n"
            f"**Copy sugerido:** _{copy_text}_"
        )
        st.markdown(info_text)

        # 2. Flux genera la imagen
        with st.spinner(f"🎨 Generando imagen con Flux Pro ({fmt_label})..."):
            try:
                image_bytes = generate_image_flux(flux_prompt, formato)
            except Exception as e:
                st.error(f"Error generando imagen: {e}")
                return

        # 3. Mostrar imagen y botón de descarga
        st.image(
            image_bytes,
            caption=fmt_label,
            use_container_width=True,
        )
        filename = make_filename(formato)
        st.download_button(
            label=f"⬇️ Descargar {formato.upper()} · Listo para BD ROWA",
            data=image_bytes,
            file_name=filename,
            mime="image/jpeg",
            key=f"dl_new_{filename}",
        )

        st.success(f"✅ `{filename}` · Sube este archivo directamente a la plataforma BD ROWA")

        # Guardar en historial
        st.session_state.messages.append({
            "role": "assistant",
            "content": info_text,
            "image_bytes": image_bytes,
            "formato": formato,
            "filename": filename,
        })


if __name__ == "__main__":
    main()
