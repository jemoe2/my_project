from __future__ import annotations

import argparse
import fnmatch
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from queue import Queue
from subprocess import CompletedProcess, run
from threading import Timer
from typing import Any, cast

# Third-party libraries
import requests
import yaml
from bs4 import BeautifulSoup, NavigableString
from PIL import Image
from retrying import retry

# Windows-specific handling
if sys.platform == "win32":
    try:
        import psutil
        import win32api
    except ImportError:
        logging.warning("Install pywin32 and psutil for enhanced Windows support")
        psutil = None
        win32api = None


# Sample data and functions (adjust according to your needs)
def get_data() -> dict:
    return {}


data = get_data()
data = cast(dict[str, Any], data)


def my_func(path: str | Path) -> None:
    # Add function logic here
    pass


def get_issues() -> dict[str, list[Any]]:
    return {"error": []}


# Example YAML loading
with open("config.yaml") as file:
    config = cast(dict[str, Any], yaml.safe_load(file))

# Example subprocess usage
result: CompletedProcess[str] = run(
    ["ls", "-l"],
    text=True,
    capture_output=True,
    check=False,
)


class HTMLtoTeXConverter:
    """Main converter class handling HTML to LaTeX/PDF conversion.

    Attributes:
        html_file: Path to input HTML file
        tex_file: Path to output TeX file
        memory_limit: Maximum memory allocation for compilation

    """

    def __init__(self, html_file: str, tex_file: str) -> None:
        self.html_file = Path(html_file)
        self.tex_file = Path(tex_file)
        self.memory_limit = 1024 * 1024 * 1024  # Default 1GB
        self.setup_logging()
        self.list_depth = 0
        self.table_column_widths: dict[str, int] = {}
        self.image_paths: list[Path] = []
        self.image_cache: dict[str, Path] = {}
        self.required_packages = {
            "listings": False,
            "soul": False,
            "emoji": False,
            "amiri": False,
            "hyper": True,
            "polyglossia": True,
            "amsmath": False,
            "tikz": False,
            "mdframed": False,
        }
        self.image_compression = 85
        self.processing_queue: Queue[str] = Queue()
        self.max_workers = 4
        self.temp_dir = Path(tempfile.mkdtemp())
        self.max_compile_time = 300  # 5 minutes timeout
        self.max_retries = 3
        self.intermediate_cleanup = True

        # Windows-specific initialization
        if sys.platform == "win32":
            self._set_windows_memory_limit()

    def setup_logging(self) -> None:
        """Enhanced logging setup with both file and console output."""
        log_file = self.tex_file.with_suffix(".conversion.log")
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )
        self.logger = logging.getLogger(__name__)

    def read_html_file(self) -> BeautifulSoup:
        """Read and parse the HTML file."""
        with open(self.html_file, encoding="utf-8") as f:
            html_content = f.read()
        return BeautifulSoup(html_content, "html.parser")

    def process_content(self, soup: BeautifulSoup) -> str:
        """Process the HTML content and convert to LaTeX."""
        header = self.create_tex_header()
        body_content = self.convert_tag_to_tex(soup)
        footer = r"\end{document}"
        return header + "\n" + body_content + "\n" + footer

    def save_tex_file(self, content: str) -> None:
        """Save the LaTeX content to the output file."""
        self.tex_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.tex_file, "w", encoding="utf-8") as f:
            f.write(content)
        self.logger.info(f"TeX file saved to {self.tex_file}")

    def sanitize_for_pdf(self, text: str) -> str:
        """Sanitize text for PDF bookmarks."""
        return re.sub(r"\\[{}]|[^A-Za-z0-9 ]+", "", text)

    def check_system_requirements(self) -> bool:
        """Verify system requirements for Windows."""
        try:
            if not shutil.which("xelatex"):
                self.logger.error("xelatex not found. Install MiKTeX.")
                return False

            font_paths = [
                os.path.join(os.environ["WINDIR"], "Fonts"),
                os.path.join(
                    os.environ["LOCALAPPDATA"],
                    "Microsoft",
                    "Windows",
                    "Fonts",
                ),
                os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Fonts"),
            ]

            amiri_patterns = ["amiri-regular.ttf", "amiri*.ttf"]
            noto_patterns = ["notosansarabic-regular.ttf", "notosansarabic*.ttf"]

            def font_exists(patterns, paths) -> bool:
                for path in paths:
                    if not os.path.exists(path):
                        continue
                    for f in os.listdir(path):
                        if any(fnmatch.fnmatch(f.lower(), p) for p in patterns):
                            return True
                return False

            amiri_found = font_exists(amiri_patterns, font_paths)
            noto_found = font_exists(noto_patterns, font_paths)

            if not amiri_found:
                self.logger.error(
                    "Amiri font missing. Download from https://fonts.google.com/specimen/Amiri",
                )
            if not noto_found:
                self.logger.error(
                    "Noto Arabic font missing. Download from https://fonts.google.com/noto/fonts",
                )
            if not amiri_found or not noto_found:
                return False

            required_packages = [
                "polyglossia",
                "fontspec",
                "bidi",
                "auxhook",
                "xkeyval",
            ]
            for package in required_packages:
                result = subprocess.run(
                    ["kpsewhich", f"{package}.sty"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    self.logger.error(f"Missing LaTeX package: {package}")
                    return False

            return True

        except Exception as e:
            self.logger.exception(f"System check failed: {e}")
            return False

    def create_tex_header(self) -> str:
        """Create LaTeX header with proper document class and packages."""
        header = [
            r"\listfiles",
            r"\documentclass[12pt]{article}",
            r"\usepackage[a4paper,margin=2.5cm]{geometry}",
            r"\usepackage{fontspec}",
            r"\usepackage{graphicx}",
            r"\usepackage{float}",
            r"\usepackage{longtable}",
            r"\usepackage{titlesec}",
            r"\usepackage{enumitem}",
            r"\usepackage{multirow}",
            r"\usepackage{booktabs}",
            r"\usepackage{hyperref}",
            r"\usepackage{etoolbox}",
            r"\usepackage{polyglossia}",
            r"\setmainlanguage[numerals=maghrib]{arabic}",
            r"\setotherlanguage{english}",
            r"\setmainfont[Script=Arabic]{Amiri}",
            r"\newfontfamily\arabicfont[Script=Arabic]{Amiri}",
            r"\titleformat{\section}{\Large\bfseries}{\thesection}{1em}{}",
            r"\titleformat{\subsection}{\large\bfseries}{\thesubsection}{1em}{}",
            r"\XeTeXlinebreak 0",
            r"\setlength{\parindent}{0pt}",
            r"\setlength{\parskip}{1em}",
            r"\begin{document}",
            r"\begin{arabic}",
        ]

        if self.required_packages.get("listings", False):
            header.insert(-5, r"\usepackage{listings}")
        if self.required_packages.get("soul", False):
            header.insert(-5, r"\usepackage{soul}")
        if self.required_packages.get("mdframed", False):
            header.insert(-5, r"\usepackage{mdframed}")

        return "\n".join(header)

    def sanitize_tex(self, text: str) -> str:
        """Enhanced text sanitization with emoji handling."""
        if not isinstance(text, str):
            return ""

        try:
            emoji_pattern = re.compile(
                r"[" "\U0001f300-\U0001f9ff" "\U0001fa00-\U0001fa6f" "\u2600-\u26ff" "\u2700-\u27bf" "]",
                flags=re.UNICODE,
            )

            def replace_emoji(match) -> str:
                emj = match.group()
                code_points = "-".join(f"{ord(char):04X}" for char in emj)
                emj_image_path = self.cache_emoji_image(code_points)
                return f"\\includegraphics{{images/{emj_image_path}}}"

            text = emoji_pattern.sub(replace_emoji, text)

            special_chars = {
                "&": r"\&",
                "%": r"\%",
                "$": r"\$",
                "#": r"\#",
                "_": r"\_",
                "{": r"\{",
                "}": r"\}",
                "~": r"\textasciitilde{}",
                "^": r"\^{}",
                "\\": r"\textbackslash{}",
                "|": r"\textbar{}",
                "<": r"\textless{}",
                ">": r"\textgreater{}",
                "[": r"{[}",
                "]": r"{]}",
                '"': r"\textquotedbl{}",
                "'": r"'",
            }

            for char, replacement in special_chars.items():
                text = text.replace(char, replacement)

            if any("\u0600" <= c <= "\u06ff" for c in text):
                self.required_packages["amiri"] = True

            return text

        except Exception as e:
            self.logger.exception(f"Sanitization error: {e}")
            return ""

    TWEMOJI_VERSION = "14.0.2"
    EMOJI_CDN_URL = f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/{TWEMOJI_VERSION}/72x72/{{code_points}}.png"
    PLACEHOLDER_IMAGE = "missing.png"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def cache_emoji_image(self, code_points: str) -> str:
        """Download and cache the emoji image."""
        cache_dir = self.tex_file.parent / "images"
        cache_dir.mkdir(exist_ok=True)
        code_points_clean = "-".join(cp.lstrip("0") for cp in code_points.split("-")).lower()
        image_name = f"{code_points_clean}.png"
        image_path = cache_dir / image_name

        if not image_path.exists():
            emj_url = f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{code_points_clean}.png"
            try:
                response = requests.get(emj_url, timeout=10)
                response.raise_for_status()
                image_path.write_bytes(response.content)
            except requests.exceptions.RequestException as e:
                self.logger.exception(f"Emoji download failed: {e}. Using placeholder.")
                return "missing.png"

        return image_name

    def verify_rtl_content(self, content: str) -> bool:
        """Enhanced RTL content verification."""
        try:
            arabic_chars = re.findall(
                r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+",
                content,
            )

            if not arabic_chars:
                self.logger.warning("No Arabic text detected")
                return True

            required_patterns = [
                r"\\usepackage{polyglossia}",
                r"\\setmainlanguage\[numerals=maghrib\]{arabic}",
                r"\\setmainfont\[Script=Arabic\]{Amiri}",
            ]

            for pattern in required_patterns:
                if not re.search(pattern, content):
                    self.logger.error(f"Missing RTL config: {pattern}")
                    return False

            return True

        except Exception as e:
            self.logger.exception(f"RTL verification failed: {e}")
            return False

    def _convert_list(self, tag) -> str
        """Convert HTML lists to LaTeX lists."""
        try:
            self.list_depth += 1
            is_ordered = tag.name == "ol"
            list_env = "enumerate" if is_ordered else "itemize"
            indent = "    " * (self.list_depth - 1)
            tex = [f"{indent}\\begin{{{list_env}}}"]

            for item in tag.find_all("li", recursive=False):
                item_content = "".join(self.convert_tag_to_tex(child) for child in item.children)
                tex.append(f"{indent}\\item {item_content.strip()}")

            tex.append(f"{indent}\\end{{{list_env}}}")
            self.list_depth -= 1

            return "\n".join(tex) + "\n\n"

        except Exception as e:
            self.logger.exception(f"List conversion error: {e}")
            return ""

    def _convert_paragraph(self, tag) -> str:
        """Convert HTML paragraphs to LaTeX paragraphs."""
        try:
            content = "".join(self.convert_tag_to_tex(child) for child in tag.children)
            content = content.strip()

            if not content:
                return ""

            classes = tag.get("class", [])
            style = ""

            if "text-center" in classes:
                style = "\\begin{center}"
            elif "text-right" in classes:
                style = "\\begin{flushright}"
            elif "highlighted" in classes:
                style = "\\begin{mdframed}"
                self.required_packages["mdframed"] = True

            if style:
                return f"{style}\n{content}\n\\end{{{style.split()[1]}}}\n\n"
            return f"{content}\n\n"

        except Exception as e:
            self.logger.exception(f"Paragraph conversion error: {e}")
            return ""

    def _convert_image(self, tag) -> str:
        """Convert HTML images to LaTeX graphics."""
        try:
            src = tag.get("src", "")
            if not src:
                return ""

            if src in self.image_cache:
                image_path = self.image_cache[src]
            else:
                images_dir = self.tex_file.parent / "images"
                images_dir.mkdir(exist_ok=True)

                if src.startswith(("http://", "https://")):
                    response = requests.get(src)
                    if response.status_code != 200:
                        self.logger.error(f"Failed to download image: {src}")
                        return ""

                    image_path = images_dir / Path(src).name
                    image_path.write_bytes(response.content)
                else:
                    image_path = Path(src)
                    if not image_path.is_absolute():
                        image_path = self.html_file.parent / image_path

                    new_path = images_dir / image_path.name
                    shutil.copy2(image_path, new_path)
                    image_path = new_path

                self.image_cache[src] = image_path
                self.image_paths.append(image_path)

            alt = tag.get("alt", "")
            width = tag.get("width", "")
            height = tag.get("height", "")

            options = []
            if width:
                options.append(f"width={width}px")
            if height:
                options.append(f"height={height}px")

            options_str = f"[{', '.join(options)}]" if options else ""

            if alt:
                return f"\\begin{{figure}}[H]\n\\centering\n\\includegraphics{options_str}{{{image_path.name}}}\n\\caption{{{alt}}}\n\\end{{figure}}\n\n"
            return f"\\includegraphics{options_str}{{{image_path.name}}}\n\n"

        except Exception as e:
            self.logger.exception(f"Image conversion error: {e}")
            return ""

    def _convert_pre(self, tag) -> str:
        """Convert preformatted text with listings package."""
        self.required_packages["listings"] = True

        try:
            code = tag.get_text()
            code_tag = tag.find("code")
            language = ""
            if code_tag and "class" in code_tag.attrs:
                classes = code_tag["class"]
                for cls in classes:
                    if cls.startswith("language-"):
                        language = cls.replace("language-", "")
                        break

            if language:
                return f"\\begin{{lstlisting}}[language={language}]\n{code}\n\\end{{lstlisting}}\n\n"
            return f"\\begin{{lstlisting}}\n{code}\n\\end{{lstlisting}}\n\n"

        except Exception as e:
            self.logger.exception(f"Preformatted text error: {e}")
            return ""

    def _convert_link(self, tag) -> str:
        """Convert HTML links to LaTeX hyperlinks."""
        try:
            href = tag.get("href", "")
            text = "".join(self.convert_tag_to_tex(child) for child in tag.children)

            if not href or not text:
                return text

            self.required_packages["hyperref"] = True
            return f"\\href{{{href}}}{{{text}}}"

        except Exception as e:
            self.logger.exception(f"Link conversion error: {e}")
            return ""

    def compile_pdf(self) -> bool:
        """Enhanced PDF compilation with cross-platform timeout."""
        try:
            output_dir = self.tex_file.parent
            env = os.environ.copy()
            env["TEXMFVAR"] = str(output_dir)

            base_command = [
                "xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={output_dir}",
                "-shell-escape",
            ]

            proc = None
            timeout_occurred = [False]

            def timeout_handler() -> None:
                timeout_occurred[0] = True
                if proc:
                    proc.terminate()

            for attempt in range(self.max_retries):
                proc = subprocess.Popen(
                    [*base_command, str(self.tex_file)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True,
                    encoding="utf-8",
                )

                timer = Timer(self.max_compile_time, timeout_handler)
                timer.start()

                stdout, stderr = proc.communicate()
                timer.cancel()

                if timeout_occurred[0]:
                    msg = "Compilation timed out"
                    raise TimeoutError(msg)

                if proc.returncode != 0:
                    self._analyze_compilation_errors(stderr)
                    if attempt < self.max_retries - 1:
                        self.logger.warning(
                            f"Retrying ({attempt+1}/{self.max_retries})",
                        )
                        self._fix_common_errors()
                        continue
                    return False

                return True

        except Exception as e:
            self.logger.exception(f"PDF compilation error: {e!s}")
            return False

    def _create_custom_format(self, format_file: Path) -> None:
        """Create custom XeLaTeX format."""
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".ini") as f:
                f.write(
                    r"""
\input{fontspec.sty}
\input{polyglossia.sty}
\input{bidi.sty}
\input{xetex.def}
\dump
""",
                )
                f.flush()
                subprocess.run(
                    ["xelatex", "-ini", "-jobname=custom", f.name],
                    check=True,
                )
        except Exception as e:
            self.logger.warning(f"Custom format creation failed: {e}")

    def _fix_common_errors(self) -> None:
        """Attempt automatic fixes for common errors."""
        try:
            with open(self.tex_file, encoding="utf-8") as f:
                content = f.read()

            if "\\usepackage{fontspec}" not in content:
                content = content.replace(
                    "\\documentclass",
                    "\\documentclass[12pt]{article}\n\\usepackage{fontspec}",
                )

            if "\\begin{document}" not in content:
                content = content.replace(
                    "\\usepackage{fontspec}",
                    "\\usepackage{fontspec}\n\\begin{document}",
                )

            if "\\end{document}" not in content:
                content += "\n\\end{document}"

            with open(self.tex_file, "w", encoding="utf-8") as f:
                f.write(content)

        except Exception as e:
            self.logger.exception(f"Error fixing issues: {e}")

    def optimize_images(self, image_path: Path) -> None:
        """Optimize images for PDF."""
        try:
            with Image.open(image_path) as img:
                if img.mode == "RGBA":
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background

                max_dimension = 2000
                if max(img.size) > max_dimension:
                    ratio = max_dimension / max(img.size)
                    new_size = tuple(int(dim * ratio) for dim in img.size)
                    img = img.resize(new_size, Image.Resampling.LANCZOS)

                img.save(
                    image_path,
                    optimize=True,
                    quality=self.image_compression,
                    progressive=True,
                )

        except Exception as e:
            self.logger.exception(f"Image optimization failed: {e}")

    def validate_tex_file(self) -> bool:
        """Validate generated TeX file."""
        try:
            with open(self.tex_file, encoding="utf-8") as f:
                content = f.read()

            required_elements = [
                "\\documentclass",
                "\\usepackage{fontspec}",
                "\\usepackage{polyglossia}",
                "\\begin{document}",
                "\\end{document}",
            ]

            missing = [elem for elem in required_elements if elem not in content]
            if missing:
                self.logger.error(f"Missing elements: {missing}")
                return False

            if content.count("\\begin{document}") != 1 or content.count("\\end{document}") != 1:
                self.logger.error("Invalid document structure")
                return False

            return True

        except Exception as e:
            self.logger.exception(f"Validation error: {e}")
            return False

    def _set_windows_memory_limit(self) -> None:
        """Set memory limit for Windows processes."""
        if sys.platform == "win32" and psutil and win32api:
            try:
                process = psutil.Process()
                process.memory_limit(self.memory_limit)
            except Exception as e:
                self.logger.warning(f"Memory limit setting failed: {e}")

    def _convert_table(self, tag) -> str:
        """Convert HTML tables to LaTeX tables (Implementation needed)."""
        self.logger.warning("Table conversion not yet implemented")
        return "\\textbf{[TABLE NOT CONVERTED]}\n\n"

    def process_large_document(self) -> str:
        """Process large HTML documents in chunks."""
        self.logger.warning("Chunked processing not implemented")
        return self.process_content(self.read_html_file())

    def validate_output(self) -> bool:
        """Validate generated PDF output (Implementation needed)."""
        self.logger.warning("PDF validation not implemented")
        return True

    def _analyze_compilation_errors(self, stderr: str) -> None:
        """Analyze compilation errors."""
        error_patterns = {
            r"LaTeX Error: File `(.+?)' not found": lambda m: f"Missing package: {m.group(1)}",
            r"Font (.+?) not found": lambda m: f"Missing font: {m.group(1)}",
            r"Undefined control sequence.*?\\(.+?)": lambda m: f"Undefined command: \\{m.group(1)}",
            r"Missing number, treated as zero": lambda _: "Invalid numeric value",
            r"Emergency stop": lambda _: "Critical error",
        }

        for pattern, handler in error_patterns.items():
            matches = re.finditer(pattern, stderr)
            for match in matches:
                self.logger.error(handler(match))

    def cleanup_tex_files(self) -> None:
        """Clean temporary files."""
        extensions = [".aux", ".log", ".toc", ".out", ".bbl", ".blg"]
        for ext in extensions:
            file_path = self.tex_file.with_suffix(ext)
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    self.logger.warning(f"Cleanup failed: {file_path} - {e}")

    def _analyze_log_file(self, log_file: Path) -> None:
        """Analyze LaTeX log file."""
        try:
            if not log_file.exists():
                self.logger.error("No log file found")
                return

            with open(log_file, encoding="utf-8", errors="ignore") as f:
                log_content = f.read()

            if "Package bidi Error" in log_content:
                error_msg = re.search(
                    r"Package polyglossia Error: (.*?)\.",
                    log_content,
                )
                if error_msg:
                    self.logger.error(f"Polyglossia error: {error_msg.group(1)}")

            missing_package = re.search(
                r"! LaTeX Error: File `(.*?)\.sty\' not found",
                log_content,
            )
            if missing_package:
                self.logger.error(f"Missing package: {missing_package.group(1)}")

        except Exception as e:
            self.logger.exception(f"Log analysis failed: {e}")

    def convert_tag_to_tex(self, tag) -> str:
        """Main tag conversion dispatcher."""
        try:
            if tag is None:
                return ""

            if isinstance(tag, NavigableString):
                return self.sanitize_tex(tag.string or "")

            tag_type = tag.name if hasattr(tag, "name") else ""

            converters = {
                "h1": lambda t: self._convert_heading(t),
                "h2": lambda t: self._convert_heading(t),
                "h3": lambda t: self._convert_heading(t),
                "h4": lambda t: self._convert_heading(t),
                "h5": lambda t: self._convert_heading(t),
                "h6": lambda t: self._convert_heading(t),
                "table": lambda t: self._convert_table(t),
                "ul": lambda t: self._convert_list(t),
                "ol": lambda t: self._convert_list(t),
                "img": lambda t: self._convert_image(t),
                "pre": lambda t: self._convert_pre(t),
                "p": lambda t: self._convert_paragraph(t),
                "a": lambda t: self._convert_link(t),
                "strong": lambda t: f"\\textbf{{{self.convert_tag_to_tex(t.string)}}}",
                "em": lambda t: f"\\emph{{{self.convert_tag_to_tex(t.string)}}}",
                "blockquote": lambda t: f"\\begin{{quote}}\n{self.convert_tag_to_tex(t.string)}\n\\end{{quote}}\n",
                "mark": lambda t: self._convert_custom_tag(t),
            }

            if tag_type in converters:
                return converters[tag_type](tag)
            return "".join(self.convert_tag_to_tex(child) for child in tag.children)

        except Exception as e:
            self.logger.exception(f"Tag conversion error: {e}")
            return ""

    def _convert_custom_tag(self, tag) -> str:
        """Handle custom tags."""
        self.required_packages["soul"] = True
        return f"\\hl{{{self.convert_tag_to_tex(tag)}}}"

    def _convert_heading(self, tag) -> str:
        """Convert headings with RTL support."""
        try:
            level_map = {
                1: "section",
                2: "subsection",
                3: "subsubsection",
                4: "paragraph",
                5: "subparagraph",
                6: "subparagraph*",
            }

            level = int(tag.name[1])
            command = level_map.get(level, "paragraph")

            content = "".join(self.convert_tag_to_tex(child) for child in tag.children)
            content = content.strip()

            if any("\u0600" <= c <= "\u06ff" for c in content):
                return f"\\{command}{{{content}}}\n\n"
            return f"\\begin{{latin}}\\{command}{{{content}}}\\end{{latin}}\n\n"

        except Exception as e:
            self.logger.exception(f"Heading conversion error: {e}")
            return ""

    def convert(self) -> bool:
        try:
            self.logger.info(f"Starting conversion: {self.html_file}")

            if not self.check_system_requirements():
                return False

            if sys.platform == "win32":
                self._set_windows_memory_limit()

            if os.path.getsize(self.html_file) > 10 * 1024 * 1024:
                self.logger.info("Processing large file in chunks")
                content = self.process_large_document()
            else:
                soup = self.read_html_file()
                content = self.process_content(soup)

            if not self.verify_rtl_content(content):
                return False

            self.save_tex_file(content)

            for image_path in self.image_paths:
                self.optimize_images(image_path)

            if not self.compile_pdf():
                return False

            if not self.validate_output():
                return False

            self.cleanup_tex_files()

            return True

        except Exception as e:
            self.logger.exception(f"Conversion failed: {e}")
            return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert HTML to LaTeX/PDF with Arabic support",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-i", "--input", required=True, help="Input HTML file")
    parser.add_argument("-o", "--output", help="Output TEX file")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--memory-limit",
        type=int,
        default=1024,
        help="Memory limit in MB",
    )
    parser.add_argument(
        "--image-quality",
        type=int,
        default=85,
        help="JPEG image quality (1-100)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Maximum worker threads",
    )

    args = parser.parse_args()

    try:
        input_path = Path(args.input).resolve(strict=True)
        output_path = Path(args.output or input_path.with_suffix(".tex"))

        converter = HTMLtoTeXConverter(input_path, output_path)
        converter.memory_limit = args.memory_limit * 1024 * 1024
        converter.image_compression = args.image_quality
        converter.max_workers = args.max_workers

        if converter.convert():
            pass
        else:
            sys.exit(1)

    except Exception as e:
        logging.exception(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
