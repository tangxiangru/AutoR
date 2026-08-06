"""Method illustration diagram generator for AutoR.

Adapts the PaperBanana multi-agent pipeline (Planner → Stylist → Visualizer → Critic)
into a self-contained module that generates method illustration diagrams using the
Gemini API and inserts them into the LaTeX paper.

API keys are read from environment variables or a config file that is gitignored.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Lazy imports – these are only needed when diagram generation is active
# ---------------------------------------------------------------------------

_gemini_client = None


def _get_gemini_client():
    """Return a cached Gemini client, initialising on first call."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    from google import genai

    api_key = _resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Gemini API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY "
            "in environment, or create configs/diagram_config.yaml (see template)."
        )
    _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _resolve_api_key() -> str | None:
    """Resolve Gemini API key from env vars or config file (never hardcoded).

    Delegates to :func:`src.web_search.resolve_gemini_api_key` so diagram generation and
    web search cannot disagree about where a Gemini key lives.
    """
    from .web_search import resolve_gemini_api_key

    return resolve_gemini_api_key()


# ---------------------------------------------------------------------------
# Style guide (embedded subset of PaperBanana NeurIPS 2025 diagram guide)
# ---------------------------------------------------------------------------

NEURIPS_STYLE_GUIDE = r"""\
### 1. The "NeurIPS Look"
The prevailing aesthetic for 2025 is **"Soft Tech & Scientific Pastels."**
Gone are the days of harsh primary colors and sharp black boxes. The modern NeurIPS diagram feels approachable yet precise. It utilizes high-value (light) backgrounds to organize complexity, reserving saturation for the most critical active elements. The vibe balances **clean modularity** (clear separation of parts) with **narrative flow** (clear left-to-right progression).

---

### 2. Detailed Style Options

#### **A. Color Palettes**
*Design Philosophy: Use color to group logic, not just to decorate. Avoid fully saturated backgrounds.*

**Background Fills (The "Zone" Strategy)**
*Used to encapsulate stages (e.g., "Pre-training phase") or environments.*
*   **Most papers use:** Very light, desaturated pastels (Opacity ~10–15%).
*   **Aesthetically pleasing options include:**
    *   🍦 **Cream / Beige** (e.g., `#F5F5DC`) – *Warm, academic feel.*
    *   ☁️ **Pale Blue / Ice** (e.g., `#E6F3FF`) – *Clean, technical feel.*
    *   🌿 **Mint / Sage** (e.g., `#E0F2F1`) – *Soft, organic feel.*
    *   🌸 **Pale Lavender** (e.g., `#F3E5F5`) – *distinctive, modern feel.*
*   **Alternative (~20%):** White backgrounds with colored *dashed borders* for a high-contrast, minimalist look (common in theoretical papers).

**Functional Element Colors**
*   **For "Active" Modules (Encoders, MLP, Attention):** Medium saturation is preferred.
    *   *Common pairings:* Blue/Orange, Green/Purple, or Teal/Pink.
    *   *Observation:* Colors are often used to distinguish **status** rather than component type:
        *   **Trainable Elements:** Often Warm tones (Red, Orange, Deep Pink).
        *   **Frozen/Static Elements:** Often Cool tones (Grey, Ice Blue, Cyan).
*   **For Highlights/Results:** High saturation (Primary Red, Bright Gold) is strictly reserved for "Error/Loss," "Ground Truth," or the final output.

#### **B. Shapes & Containers**
*Design Philosophy: "Softened Geometry." Sharp corners are for data; rounded corners are for processes.*

**Core Components**
*   **Process Nodes (The Standard):** Rounded Rectangles (Corner radius 5–10px). This is the dominant shape (~80%) for generic layers or steps.
*   **Tensors & Data:**
    *   **3D Stacks/Cuboids:** Used to imply depth/volume (e.g., $B \times H \times W$).
    *   **Flat Squares/Grids:** Used for matrices, tokens, or attention maps.
    *   **Cylinders:** Exclusively reserved for Databases, Buffers, or Memory.

**Grouping & Hierarchy**
*   **The "Macro-Micro" Pattern:** A solid, light-colored container represents the global view, with a specific module (e.g., "Attention Block") connected via lines to a "zoomed-in" detailed breakout box.
*   **Borders:**
    *   **Solid:** For physical components.
    *   **Dashed:** Highly prevalent for indicating "Logical Stages," "Optional Paths," or "Scopes."

#### **C. Lines & Arrows**
*Design Philosophy: Line style dictates flow type.*

**Connector Styles**
*   **Orthogonal / Elbow (Right Angles):** Most papers use this for **Network Architectures** (implies precision, matrices, and tensors).
*   **Curved / Bezier:** Common choices include this for **System Logic, Feedback Loops, or High-Level Data Flow** (implies narrative and connection).

**Line Semantics**
*   **Solid Black/Grey:** Standard data flow (Forward pass).
*   **Dashed Lines:** Universally recognized as "Auxiliary Flow."
    *   *Used for:* Gradient updates, Skip connections, or Loss calculations.
*   **Integrated Math:** Standard operators ($\oplus$ for Add, $\otimes$ for Concat/Multiply) are frequently placed *directly* on the line or intersection.

#### **D. Typography & Icons**
*Design Philosophy: Strict separation between "Labeling" and "Math."*

**Typography**
*   **Labels (Module Names):** **Sans-Serif** (Arial, Roboto, Helvetica).
    *   *Style:* Bold for headers, Regular for details.
*   **Variables (Math):** **Serif** (Times New Roman, LaTeX default).
    *   *Rule:* If it is a variable in your equation (e.g., $x, \theta, \mathcal{L}$), it **must** be Serif and Italicized in the diagram.

**Iconography Options**
*   **For Model State:**
    *   *Trainable:* 🔥 Fire, ⚡ Lightning.
    *   *Frozen:* ❄️ Snowflake, 🔒 Padlock, 🛑 Stop Sign (Greyed out).
*   **For Operations:**
    *   *Inspection:* 🔍 Magnifying Glass.
    *   *Processing/Computation:* ⚙️ Gear, 🖥️ Monitor.
*   **For Content:**
    *   *Text/Prompt:* 📄 Document, 💬 Chat Bubble.
    *   *Image:* 🖼️ Actual thumbnail of an image (not just a square).

---

### 3. Common Pitfalls (How to look "Amateur")
*   ❌ **The "PowerPoint Default" Look:** Using standard Blue/Orange presets with heavy black outlines.
*   ❌ **Font Mixing:** Using Times New Roman for "Encoder" labels (makes the paper look dated to the 1990s).
*   ❌ **Inconsistent Dimension:** Mixing flat 2D boxes and 3D isometric cubes without a clear reason (e.g., 2D for logic, 3D for tensors is fine; random mixing is not).
*   ❌ **Primary Backgrounds:** Using saturated Yellow or Blue backgrounds for grouping (distracts from the content).
*   ❌ **Ambiguous Arrows:** Using the same line style for "Data Flow" and "Gradient Flow."

---

### 4. Domain-Specific Styles

**If you are writing an AGENT / LLM Paper:**
*   **Vibe:** Illustrative, Narrative, "Friendly.", Cartoony.
*   **Key Elements:** Use "User Interface" aesthetics. Chat bubbles for prompts, document icons for retrieval.
*   **Characters:** It is common to use cute 2D vector robots, human avatars, or emojis to humanize the agent's reasoning steps.

**If you are writing a COMPUTER VISION / 3D Paper:**
*   **Vibe:** Spatial, Dense, Geometric.
*   **Key Elements:** Frustums (camera cones), Ray lines, and Point Clouds.
*   **Color:** Often uses RGB color coding to denote axes or channel correspondence. Use heatmaps (Rainbow/Viridis) to show activation.

**If you are writing a THEORETICAL / OPTIMIZATION Paper:**
*   **Vibe:** Minimalist, Abstract, "Textbook."
*   **Key Elements:** Focus on graph nodes (circles) and manifolds (planes/surfaces).
*   **Color:** Restrained. mostly Grayscale/Black/White with one highlight color (e.g., Gold or Blue). Avoid "cartoony" elements.
"""


# ---------------------------------------------------------------------------
# Agent prompts (adapted from PaperBanana)
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are an expert at describing scientific diagrams for AI papers.

Given the methodology section of a paper and a figure caption, produce a VERY DETAILED
textual description of an illustrative diagram. Include:
- Every component (boxes, arrows, labels, icons).
- Layout and spatial arrangement (left-to-right, top-to-bottom).
- Background style (typically pure white or very light pastel).
- Colours (specific hex codes), line thickness, icon styles.
- Connections and data flow between components.

Be as specific as possible. Vague descriptions produce poor figures.
Do NOT include figure titles or captions inside the diagram itself.
Output ONLY the description text.
"""

STYLIST_SYSTEM_PROMPT = """\
You are a Lead Visual Designer for NeurIPS 2025.

Refine and enrich the preliminary diagram description to meet publication-ready
NeurIPS 2025 aesthetic standards. Follow the provided style guidelines.

Rules:
1. Preserve semantic content and logic — only refine aesthetics.
2. If description already looks high-quality, preserve it.
3. Enrich plain descriptions with specific visual attributes (hex colours, fonts, line widths).
4. Handle icons carefully — preserve semantic meaning (snowflake=frozen, fire=trainable).
5. Do NOT rewrite from scratch; enhance what exists.

Output ONLY the final polished description. No explanations.
"""

VISUALIZER_SYSTEM_PROMPT = (
    "You are an expert scientific diagram illustrator. "
    "Generate high-quality scientific diagrams based on user requests."
)

CRITIC_SYSTEM_PROMPT = """\
You are a Lead Visual Designer for NeurIPS 2025.

Critique the diagram based on content fidelity and presentation quality.
Check:
1. Content: alignment with methodology, text accuracy, no hallucinated content, no caption in image.
2. Presentation: clarity, readability, no redundant legends.

Output strictly in this JSON format:
```json
{
    "critic_suggestions": "Your critique or 'No changes needed.'",
    "revised_description": "Revised description or 'No changes needed.'"
}
```
"""


# ---------------------------------------------------------------------------
# Core pipeline functions
# ---------------------------------------------------------------------------

async def _call_gemini_text(
    prompt_parts: list[dict[str, Any]],
    system_prompt: str,
    model_name: str = "gemini-2.5-flash",
) -> str:
    """Call Gemini text generation with retry."""
    from google.genai import types

    client = _get_gemini_client()
    gemini_parts = []
    for item in prompt_parts:
        if item.get("type") == "text":
            gemini_parts.append(types.Part.from_text(text=item["text"]))
        elif item.get("type") == "image_bytes":
            gemini_parts.append(
                types.Part.from_bytes(
                    data=base64.b64decode(item["data"]),
                    mime_type=item.get("mime_type", "image/jpeg"),
                )
            )

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=1.0,
        candidate_count=1,
        max_output_tokens=50000,
    )

    for attempt in range(5):
        try:
            response = await client.aio.models.generate_content(
                model=model_name, contents=gemini_parts, config=config,
            )
            text = response.candidates[0].content.parts[0].text
            if text and text.strip():
                return text.strip()
        except Exception as exc:
            delay = min(5 * (2 ** attempt), 30)
            print(f"[diagram_gen] text attempt {attempt+1} failed: {exc}, retrying in {delay}s")
            await asyncio.sleep(delay)
    return ""


async def _call_gemini_image(
    prompt_text: str,
    system_prompt: str = "",
    model_name: str = "gemini-3.1-flash-image-preview",
) -> str | None:
    """Call Gemini image generation, return base64 JPEG or None.

    Supports both Imagen 4 (generate_images API) and Gemini native image
    generation (generate_content with response_modalities=IMAGE).
    """
    from google.genai import types

    client = _get_gemini_client()
    is_imagen = "imagen" in model_name

    for attempt in range(5):
        try:
            if is_imagen:
                response = await client.aio.models.generate_images(
                    model=model_name,
                    prompt=prompt_text,
                    config=types.GenerateImagesConfig(number_of_images=1),
                )
                if response.generated_images:
                    raw = base64.b64encode(
                        response.generated_images[0].image.image_bytes
                    ).decode("utf-8")
                    return _convert_to_jpeg_b64(raw)
            else:
                parts = [types.Part.from_text(text=prompt_text)]
                config = types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                )
                response = await client.aio.models.generate_content(
                    model=model_name, contents=parts, config=config,
                )
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data:
                            raw = base64.b64encode(part.inline_data.data).decode("utf-8")
                            return _convert_to_jpeg_b64(raw)
        except Exception as exc:
            delay = min(5 * (2 ** attempt), 30)
            print(f"[diagram_gen] image attempt {attempt+1} failed: {exc}, retrying in {delay}s")
            await asyncio.sleep(delay)
    return None


def _convert_to_jpeg_b64(b64_data: str) -> str:
    """Convert any image format to JPEG base64."""
    try:
        from PIL import Image
        raw = base64.b64decode(b64_data)
        img = Image.open(BytesIO(raw))
        if img.mode in ("RGBA", "P", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return b64_data


# ---------------------------------------------------------------------------
# High-level pipeline
# ---------------------------------------------------------------------------

async def generate_method_diagram(
    method_text: str,
    figure_caption: str,
    output_path: Path,
    model_name: str = "gemini-2.5-flash",
    image_model_name: str = "gemini-3.1-flash-image-preview",
    max_critic_rounds: int = 2,
) -> Path | None:
    """Run the full Planner → Stylist → Visualizer → Critic pipeline.

    Parameters
    ----------
    method_text : str
        The methodology section of the paper.
    figure_caption : str
        Caption for the method illustration figure.
    output_path : Path
        Where to save the final JPEG image.
    model_name : str
        Gemini model to use for text reasoning.
    image_model_name : str
        Gemini model to use for image generation.
    max_critic_rounds : int
        Maximum critic-visualiser iteration rounds.

    Returns
    -------
    Path or None
        Path to the saved image, or None on failure.
    """
    # The figure caption is only used at LaTeX-injection time. It must NOT be
    # passed into the Planner / Stylist / Visualizer / Critic prompts, otherwise
    # the model treats it as content to render and the resulting image ends up
    # with caption text baked into the diagram alongside the method content.
    print("[diagram_gen] Step 1/4: Planner — generating diagram description...")
    planner_prompt = [
        {"type": "text", "text": (
            f"Methodology Section:\n{method_text}\n\n"
            "Provide a detailed description of the target diagram (do not include "
            "figure titles, captions, or any verbatim sentences from the methodology "
            "as text labels in the diagram):"
        )}
    ]
    description = await _call_gemini_text(planner_prompt, PLANNER_SYSTEM_PROMPT, model_name)
    if not description:
        print("[diagram_gen] Planner failed to produce description.")
        return None

    print("[diagram_gen] Step 2/4: Stylist — refining aesthetics...")
    stylist_prompt = [
        {"type": "text", "text": (
            f"Detailed Description:\n{description}\n\n"
            f"Style Guidelines:\n{NEURIPS_STYLE_GUIDE}\n\n"
            f"Methodology Section:\n{method_text}\n\n"
            "Your Output:"
        )}
    ]
    styled_desc = await _call_gemini_text(stylist_prompt, STYLIST_SYSTEM_PROMPT, model_name)
    if not styled_desc:
        styled_desc = description  # fallback to planner output

    print("[diagram_gen] Step 3/4: Visualiser — generating image...")
    vis_prompt = (
        f"Render an image based on the following detailed description: {styled_desc}\n"
        "Note that do not include figure titles in the image. Diagram:"
    )
    image_b64 = await _call_gemini_image(
        vis_prompt, VISUALIZER_SYSTEM_PROMPT, image_model_name,
    )
    if not image_b64:
        print("[diagram_gen] Visualiser failed to generate image.")
        return None

    # Critic loop
    current_desc = styled_desc
    current_image = image_b64
    for round_idx in range(max_critic_rounds):
        print(f"[diagram_gen] Step 4/4: Critic — round {round_idx + 1}/{max_critic_rounds}...")
        critic_parts = [
            {"type": "text", "text": "Target Diagram for Critique:"},
            {"type": "image_bytes", "data": current_image, "mime_type": "image/jpeg"},
            {"type": "text", "text": (
                f"Detailed Description:\n{current_desc}\n\n"
                f"Methodology Section:\n{method_text}\n\n"
                "Your Output:"
            )},
        ]
        critic_raw = await _call_gemini_text(critic_parts, CRITIC_SYSTEM_PROMPT, model_name)

        # Parse JSON response
        cleaned = critic_raw.replace("```json", "").replace("```", "").strip()
        try:
            import json_repair
            result = json_repair.loads(cleaned)
        except Exception:
            try:
                result = json.loads(cleaned)
            except Exception:
                result = {}

        suggestions = result.get("critic_suggestions", "No changes needed.")
        revised = result.get("revised_description", "No changes needed.")

        if suggestions.strip() == "No changes needed." or revised.strip() == "No changes needed.":
            print(f"[diagram_gen] Critic round {round_idx + 1}: no changes needed.")
            break

        # Re-visualise with revised description
        current_desc = revised
        new_prompt = (
            f"Render an image based on the following detailed description: {current_desc}\n"
            "Note that do not include figure titles in the image. Diagram:"
        )
        new_image = await _call_gemini_image(
            new_prompt, VISUALIZER_SYSTEM_PROMPT, image_model_name,
        )
        if new_image:
            current_image = new_image
            print(f"[diagram_gen] Critic round {round_idx + 1}: re-visualised successfully.")
        else:
            print(f"[diagram_gen] Critic round {round_idx + 1}: re-visualisation failed, keeping previous.")
            break

    # Save final image
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = base64.b64decode(current_image)
    output_path.write_bytes(raw_bytes)
    print(f"[diagram_gen] Saved method illustration to {output_path}")
    return output_path


def generate_method_diagram_sync(
    method_text: str,
    figure_caption: str,
    output_path: Path,
    model_name: str = "gemini-2.5-flash",
    image_model_name: str = "gemini-3.1-flash-image-preview",
    max_critic_rounds: int = 2,
) -> Path | None:
    """Synchronous wrapper for generate_method_diagram."""
    return asyncio.run(generate_method_diagram(
        method_text=method_text,
        figure_caption=figure_caption,
        output_path=output_path,
        model_name=model_name,
        image_model_name=image_model_name,
        max_critic_rounds=max_critic_rounds,
    ))


# ---------------------------------------------------------------------------
# LaTeX integration helpers
# ---------------------------------------------------------------------------

METHOD_FIGURE_LATEX = r"""
\begin{{figure*}}[t]
    \centering
    \includegraphics[width=0.95\textwidth]{{{image_path}}}
    \caption{{{caption}}}
    \label{{fig:method_overview}}
\end{{figure*}}
"""


def inject_diagram_into_latex(
    method_tex_path: Path,
    image_rel_path: str,
    caption: str,
) -> bool:
    """Insert a method illustration figure at the top of method.tex.

    Returns True if the figure was inserted, False if it already exists or the
    file could not be read.
    """
    if not method_tex_path.exists():
        return False

    content = method_tex_path.read_text(encoding="utf-8")

    # Don't insert twice. Only treat the figure as "already present" if there is
    # a non-comment occurrence of the label — comments like
    # "% Figure~\ref{fig:method_overview} will be inserted ..." must not block
    # injection.
    def _has_real_label(text: str) -> bool:
        for raw_line in text.splitlines():
            stripped = raw_line.lstrip()
            if stripped.startswith("%"):
                continue
            # Strip trailing inline comments (unescaped %)
            code = re.sub(r"(?<!\\)%.*$", "", raw_line)
            if "\\label{fig:method_overview}" in code:
                return True
        return False

    if _has_real_label(content):
        return False

    figure_block = METHOD_FIGURE_LATEX.format(
        image_path=image_rel_path,
        caption=caption,
    ).strip()

    # Drop any stale comment lines or dangling \ref{fig:method_overview} the
    # writing stage may have left behind so the new figure is the single source
    # of truth for the label.
    cleaned_lines: list[str] = []
    for raw_line in content.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith("%") and "fig:method_overview" in raw_line:
            continue
        if stripped.startswith("%") and "METHOD_DIAGRAM_PLACEHOLDER" in raw_line:
            continue
        cleaned_lines.append(raw_line)
    content = "\n".join(cleaned_lines)

    # Insert after the first \section (and optional \label) or at the top.
    # Use a brace-depth-aware match to handle nested braces like \section{The \DSV{} Pipeline}
    def _find_section_end(text: str) -> int | None:
        m = re.search(r"\\section\{", text)
        if not m:
            return None
        depth = 1
        i = m.end()
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        # Skip optional \label{...} after section
        label_match = re.match(r"\s*\\label\{[^}]*\}\s*", text[i:])
        if label_match:
            i += label_match.end()
        return i

    section_end = _find_section_end(content)
    if section_end is not None:
        insert_pos = section_end
        new_content = content[:insert_pos] + "\n\n" + figure_block + "\n\n" + content[insert_pos:]
    else:
        new_content = figure_block + "\n\n" + content

    method_tex_path.write_text(new_content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Markdown integration helpers
# ---------------------------------------------------------------------------

#: Explicit insertion point a markdown report may leave for the generated diagram.
METHOD_DIAGRAM_PLACEHOLDER = "<!-- METHOD_DIAGRAM_PLACEHOLDER -->"
#: Marker written alongside the figure so a second run does not insert it twice.
METHOD_DIAGRAM_MARKER = "<!-- autor:method_overview -->"

_METHOD_HEADING_RE = re.compile(r"^#{2,4}\s+.*\bmethod", flags=re.IGNORECASE)


def inject_diagram_into_markdown(
    report_path: Path,
    image_rel_path: str,
    caption: str,
) -> bool:
    """Insert a method illustration into a markdown report.

    Placement, in order of preference: an explicit ``METHOD_DIAGRAM_PLACEHOLDER`` comment, the
    first heading that names the method, or the end of the report. Returns True when the figure
    was inserted, False when it is already present or the report is missing.
    """
    if not report_path.exists():
        return False

    content = report_path.read_text(encoding="utf-8")
    if METHOD_DIAGRAM_MARKER in content or image_rel_path in content:
        return False

    figure_block = f"{METHOD_DIAGRAM_MARKER}\n![{caption}]({image_rel_path})"

    if METHOD_DIAGRAM_PLACEHOLDER in content:
        new_content = content.replace(METHOD_DIAGRAM_PLACEHOLDER, figure_block, 1)
        report_path.write_text(new_content, encoding="utf-8")
        return True

    lines = content.splitlines()
    for index, line in enumerate(lines):
        if _METHOD_HEADING_RE.match(line):
            insert_at = index + 1
            # Keep one blank line between the heading and the figure.
            block = ["", figure_block, ""]
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            new_lines = lines[:insert_at] + block + lines[insert_at:]
            report_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
            return True

    report_path.write_text(content.rstrip() + "\n\n" + figure_block + "\n", encoding="utf-8")
    return True


def _convert_to_png(path: Path) -> Path:
    """Re-encode a generated diagram as PNG, or return it unchanged when that is not possible.

    The image backend returns JPEG bytes whatever the filename says. Benchmark harnesses ask for
    PNG, and a ``.png`` file holding JPEG bytes is a worse outcome than an honest ``.jpg``, so the
    conversion is real rather than a rename.
    """
    if path.suffix.lower() == ".png":
        return path
    try:
        from PIL import Image
    except ImportError:
        return path

    png_path = path.with_suffix(".png")
    try:
        with Image.open(path) as image:
            image.convert("RGB").save(png_path, format="PNG")
    except Exception as exc:  # noqa: BLE001 - a failed conversion must not lose the figure
        print(f"[diagram_gen] PNG conversion failed ({exc}); keeping {path.name}.")
        return path

    path.unlink(missing_ok=True)
    return png_path


# ---------------------------------------------------------------------------
# Post-writing hook: extract method text and generate diagram
# ---------------------------------------------------------------------------

def _read_memory_context(run_root: Path) -> str:
    """Pull the earlier-stage sections that give the diagram planner real context."""
    memory_path = run_root / "memory.md"
    if not memory_path.exists():
        return ""

    full_memory = memory_path.read_text(encoding="utf-8")
    snippet = ""
    for section_name in ["Hypothesis Generation", "Study Design", "Implementation"]:
        idx = full_memory.find(section_name)
        if idx >= 0:
            end_idx = full_memory.find("\n# Stage", idx + 1)
            if end_idx < 0:
                end_idx = min(idx + 3000, len(full_memory))
            snippet += full_memory[idx:end_idx] + "\n\n"
    return snippet


def _extract_markdown_method_section(report_text: str) -> str:
    """Return the methodology section of a markdown report, or the whole report as a fallback."""
    lines = report_text.splitlines()
    start: int | None = None
    heading_level = 0
    for index, line in enumerate(lines):
        if _METHOD_HEADING_RE.match(line):
            start = index
            heading_level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        return report_text

    for index in range(start + 1, len(lines)):
        stripped = lines[index].lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= heading_level:
                return "\n".join(lines[start:index])
    return "\n".join(lines[start:])


def _markdown_diagram_hook(run_root: Path, model_name: str) -> Path | None:
    """Generate a method illustration for a markdown report and embed it."""
    report_path = run_root / "workspace" / "report" / "report.md"
    images_dir = run_root / "workspace" / "report" / "images"

    if not report_path.exists():
        print("[diagram_gen] report.md not found, skipping diagram generation.")
        return None

    report_text = report_path.read_text(encoding="utf-8")
    method_text = _extract_markdown_method_section(report_text)
    if len(method_text.strip()) < 100:
        print("[diagram_gen] method section too short, skipping diagram generation.")
        return None

    memory_snippet = _read_memory_context(run_root)
    combined_method = method_text
    if memory_snippet:
        combined_method = (
            "## Context from earlier research stages:\n"
            + memory_snippet[:4000]
            + "\n\n## Method section:\n"
            + method_text
        )

    caption = (
        "Overview of the proposed method. "
        "The diagram illustrates the key components and data flow of our approach."
    )

    result = generate_method_diagram_sync(
        method_text=combined_method,
        figure_caption=caption,
        output_path=images_dir / "method_overview.jpg",
        model_name=model_name,
    )
    if result is None:
        return None

    result = _convert_to_png(result)

    # The judge resolves figure paths relative to report.md, so the reference must be
    # `images/<name>` and the file must live under report/images/.
    injected = inject_diagram_into_markdown(report_path, f"images/{result.name}", caption)
    if injected:
        print("[diagram_gen] Injected figure reference into report.md")
    else:
        print("[diagram_gen] Figure reference already exists or could not be injected.")

    return result


def post_writing_diagram_hook(
    run_root: Path,
    model_name: str = "gemini-2.5-flash",
    output_format: str | None = None,
) -> Path | None:
    """After Stage 07 writing, extract the method text and generate a diagram.

    In ``latex`` mode this reads ``writing/sections/method.tex`` and injects a ``figure*`` block.
    In ``markdown`` mode it reads ``report/report.md`` and injects a markdown image whose path is
    relative to the report, which is the only form a benchmark judge can resolve.
    """
    if output_format is None:
        from .utils import build_run_paths, selected_output_format

        output_format = selected_output_format(build_run_paths(run_root))

    if output_format == "markdown":
        return _markdown_diagram_hook(run_root, model_name=model_name)

    workspace = run_root / "workspace"
    method_tex = workspace / "writing" / "sections" / "method.tex"
    figures_dir = workspace / "figures"
    output_image = figures_dir / "method_overview.jpg"

    # Read method section text
    if not method_tex.exists():
        print("[diagram_gen] method.tex not found, skipping diagram generation.")
        return None

    method_text = method_tex.read_text(encoding="utf-8")
    if len(method_text.strip()) < 100:
        print("[diagram_gen] method.tex too short, skipping diagram generation.")
        return None

    # Also try to read the memory for a richer understanding
    memory_path = run_root / "memory.md"
    memory_snippet = ""
    if memory_path.exists():
        full_memory = memory_path.read_text(encoding="utf-8")
        # Extract the hypothesis and study design sections for context
        for section_name in ["Hypothesis Generation", "Study Design", "Implementation"]:
            idx = full_memory.find(section_name)
            if idx >= 0:
                end_idx = full_memory.find("\n# Stage", idx + 1)
                if end_idx < 0:
                    end_idx = min(idx + 3000, len(full_memory))
                memory_snippet += full_memory[idx:end_idx] + "\n\n"

    combined_method = method_text
    if memory_snippet:
        combined_method = (
            "## Context from earlier research stages:\n"
            + memory_snippet[:4000]
            + "\n\n## LaTeX method section:\n"
            + method_text
        )

    caption = (
        "Overview of the proposed method. "
        "The diagram illustrates the key components and data flow of our approach."
    )

    result = generate_method_diagram_sync(
        method_text=combined_method,
        figure_caption=caption,
        output_path=output_image,
        model_name=model_name,
    )

    if result is None:
        return None

    # Inject into method.tex.
    # pdflatex resolves \includegraphics relative to the *main* .tex file's
    # directory (workspace/writing/main.tex), not the included section file
    # (workspace/writing/sections/method.tex). The figure lives at
    # workspace/figures/method_overview.jpg, so the correct relative path from
    # the main-tex perspective is `../figures/method_overview.jpg`.
    image_rel = "../figures/method_overview.jpg"
    injected = inject_diagram_into_latex(method_tex, image_rel, caption)
    if injected:
        print("[diagram_gen] Injected figure reference into method.tex")
    else:
        print("[diagram_gen] Figure reference already exists or could not be injected.")

    return result
