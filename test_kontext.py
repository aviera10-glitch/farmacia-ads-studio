"""
TEST · Flux Kontext — Imagen de referencia → Nueva composición
--------------------------------------------------------------
Sube una foto de un producto real (Frenadol, Almax, solar...)
y genera una nueva imagen de marketing con ese producto en la escena
que describes.

Ejecutar: streamlit run test_kontext.py
"""

import streamlit as st
import fal_client
import requests
import os
from PIL import Image
from io import BytesIO
from datetime import datetime

st.set_page_config(
    page_title="TEST · Flux Kontext",
    page_icon="🧪",
    layout="wide",
)

st.title("🧪 TEST · Imagen de referencia → Nueva composición")
st.caption("Prueba de Flux Kontext antes de integrar en la app principal")

# ─── Setup fal.ai ─────────────────────────────────────────────────────────────

def setup_fal():
    key = st.secrets.get("FAL_KEY") or os.getenv("FAL_KEY", "")
    if not key:
        st.error("⚠️ Falta FAL_KEY en `.streamlit/secrets.toml`")
        st.stop()
    os.environ["FAL_KEY"] = key

setup_fal()

# ─── Interfaz ─────────────────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.markdown("### 1. Foto del producto real")
    uploaded = st.file_uploader(
        "Sube una foto del producto (JPG, PNG)",
        type=["jpg", "jpeg", "png"],
        help="Foto clara del producto, preferiblemente sobre fondo blanco o neutro"
    )
    if uploaded:
        img = Image.open(uploaded)
        st.image(img, caption="Foto de referencia subida", use_container_width=True)

with col2:
    st.markdown("### 2. Describe la nueva escena")
    prompt = st.text_area(
        "Prompt en español (la app lo traduce automáticamente):",
        placeholder="Ej: Este producto en una playa mediterránea con arena blanca y mar azul, luz de verano cálida, espacio para texto arriba",
        height=120,
    )

    st.markdown("### 3. Configuración")
    model = st.selectbox(
        "Modelo a probar:",
        [
            "fal-ai/flux-pro/kontext — Mejor calidad, preserva producto (€0.04)",
            "fal-ai/flux-pro/kontext/max — Máxima calidad, más fiel al original (€0.08)",
        ]
    )
    model_id = "fal-ai/flux-pro/kontext" if "kontext —" in model else "fal-ai/flux-pro/kontext/max"

    formato = st.radio(
        "Formato de salida:",
        ["Panorama · 1080×1920 (pantalla completa)", "Header · 1080×350 (cabecera)"],
        horizontal=True,
    )
    is_panorama = "Panorama" in formato

    strength = st.slider(
        "Fidelidad al producto original (0 = libre, 1 = muy fiel):",
        min_value=0.1, max_value=1.0, value=0.85, step=0.05,
        help="Valores altos mantienen mejor el producto. Si queda muy rígido, baja un poco."
    )

# ─── Generación ───────────────────────────────────────────────────────────────

st.divider()
generate = st.button("🚀 Generar imagen de test", type="primary", disabled=not (uploaded and prompt))

if generate and uploaded and prompt:

    # Traducir prompt al inglés con instrucción explícita para Kontext
    if is_panorama:
        target_size = {"width": 1080, "height": 1920}
        scene_hint = "vertical portrait format, 9:16 aspect ratio"
    else:
        target_size = {"width": 1080, "height": 350}
        scene_hint = "horizontal banner format, wide panoramic"

    # Construir prompt en inglés para Kontext
    # Kontext necesita instrucciones sobre QUÉ mantener y QUÉ cambiar
    english_prompt = f"""Keep the product from the reference image exactly as it appears —
preserve all packaging, labels, colors, logo and branding.
Place this product in the following scene: {prompt}.
{scene_hint}.
Ample empty space for text overlay.
Commercial pharmacy advertisement, professional product photography, 4K, clean lighting."""

    with st.spinner("📤 Subiendo imagen de referencia a fal.ai..."):
        try:
            uploaded.seek(0)
            img_bytes = uploaded.read()

            # Convertir a base64 data URL (no requiere upload externo)
            import base64
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            image_url = f"data:image/jpeg;base64,{b64}"
            st.success("✅ Imagen preparada correctamente")
        except Exception as e:
            st.error(f"Error preparando imagen: {e}")
            st.stop()

    with st.spinner(f"🎨 Generando con {model_id}... (20-40 segundos)"):
        try:
            result = fal_client.run(
                model_id,
                arguments={
                    "prompt": english_prompt,
                    "image_url": image_url,
                    "guidance_scale": 3.5,
                    "num_inference_steps": 28,
                    "output_format": "jpeg",
                },
            )
            result_url = result["images"][0]["url"]
        except Exception as e:
            st.error(f"Error generando imagen: {e}")
            st.stop()

    with st.spinner("📥 Descargando resultado..."):
        resp = requests.get(result_url, timeout=60)
        result_bytes = resp.content

    # ── Resultado ──────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("## ✅ Resultado del test")

    r1, r2 = st.columns(2)
    with r1:
        st.markdown("**Referencia original:**")
        st.image(img_bytes, use_container_width=True)
    with r2:
        st.markdown("**Imagen generada:**")
        st.image(result_bytes, use_container_width=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_kontext_{ts}.jpg"
    st.download_button(
        label="⬇️ Descargar resultado",
        data=result_bytes,
        file_name=filename,
        mime="image/jpeg",
    )

    # ── Valoración ─────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📊 Evalúa el resultado")
    st.markdown("Responde estas preguntas para decidir si lo integramos en la app:")

    c1, c2, c3 = st.columns(3)
    with c1:
        product_ok = st.radio("¿Se reconoce bien el producto/marca?", ["✅ Sí", "⚠️ Regular", "❌ No"])
    with c2:
        scene_ok = st.radio("¿La escena encaja con lo pedido?", ["✅ Sí", "⚠️ Regular", "❌ No"])
    with c3:
        quality_ok = st.radio("¿Calidad suficiente para BD ROWA?", ["✅ Sí", "⚠️ Regular", "❌ No"])

    if st.button("📝 Ver recomendación"):
        all_ok = all(v.startswith("✅") for v in [product_ok, scene_ok, quality_ok])
        partial = any(v.startswith("✅") for v in [product_ok, scene_ok, quality_ok])
        if all_ok:
            st.success("🎉 **Listo para integrar en la app principal.** Los tres criterios son satisfactorios.")
        elif partial:
            st.warning("⚠️ **Resultado parcial.** Prueba ajustando el slider de fidelidad o reformulando el prompt. Si con ajustes mejora, integramos.")
        else:
            st.error("❌ **No satisfactorio.** Exploraremos alternativas (Redux, composición manual con rembg).")

    st.divider()
    st.caption(f"Modelo: `{model_id}` · Fidelidad: `{strength}` · Prompt usado en inglés:")
    with st.expander("Ver prompt exacto enviado a Flux Kontext"):
        st.code(english_prompt)
