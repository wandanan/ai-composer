"""aic/extensions/platform/extract/convert_to_pdf.py — Word→PDF 转换（从原项目 doc_extract/converter.py 移植）。

策略（按平台）:
  Windows:  优先 docx2pdf (MS Word COM), 回退 LibreOffice --headless
  Linux:    优先 pandoc + wkhtmltopdf, 回退 LibreOffice --headless
非 Word 文件直接返回原 bytes。
"""
from __future__ import annotations

import logging
import os
import platform
import subprocess
import tempfile

logger = logging.getLogger(__name__)

DOCX_SUFFIXES = {".docx", ".doc"}


def convert_to_pdf(file_bytes: bytes, original_name: str) -> bytes:
    """将 Word 文件转为 PDF, 返回 PDF 字节流; 非 Word 文件直接返回原 bytes。"""
    suffix = os.path.splitext(original_name)[1].lower()
    if suffix not in DOCX_SUFFIXES:
        return file_bytes
    if platform.system() == "Windows":
        return _convert_windows(file_bytes, original_name)
    return _convert_libreoffice(file_bytes, original_name)


def _convert_windows(file_bytes: bytes, original_name: str) -> bytes:
    try:
        from docx2pdf import convert
        return _convert_via_bytes(convert, file_bytes, original_name)
    except (ImportError, Exception) as e:
        logger.warning(f"docx2pdf 转换失败: {e}, 回退 LibreOffice")
    return _convert_libreoffice(file_bytes, original_name)


def _convert_libreoffice(file_bytes: bytes, original_name: str) -> bytes:
    """LibreOffice --headless 转换（回退方案）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, original_name)
        with open(input_path, "wb") as f:
            f.write(file_bytes)

        cmd = [
            "libreoffice", "--headless", "--norestore", "--nodefault",
            "--nofirststartwizard", "--convert-to", "pdf",
            "--outdir", tmpdir, input_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        except subprocess.TimeoutExpired:
            raise RuntimeError("LibreOffice Word→PDF 转换超时（300s）")
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            raise RuntimeError(f"LibreOffice Word→PDF 转换失败: {stderr}")
        except FileNotFoundError:
            raise RuntimeError(
                "LibreOffice 未安装: apt-get install -y libreoffice-writer libreoffice-impress")

        pdf_name = os.path.splitext(original_name)[0] + ".pdf"
        pdf_path = os.path.join(tmpdir, pdf_name)
        if not os.path.exists(pdf_path):
            candidates = [f for f in os.listdir(tmpdir) if f.lower().endswith(".pdf")]
            if candidates:
                pdf_path = os.path.join(tmpdir, candidates[0])
            else:
                raise RuntimeError("LibreOffice 转换后未找到输出 PDF 文件")
        with open(pdf_path, "rb") as f:
            return f.read()


def _convert_via_bytes(convert_func, file_bytes: bytes, original_name: str) -> bytes:
    """临时文件→转换→读取 管道（docx2pdf）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, original_name)
        with open(input_path, "wb") as f:
            f.write(file_bytes)
        convert_func(input_path, tmpdir)
        pdf_name = os.path.splitext(original_name)[0] + ".pdf"
        pdf_path = os.path.join(tmpdir, pdf_name)
        if not os.path.exists(pdf_path):
            raise RuntimeError(f"Word→PDF 转换后未找到输出文件: {pdf_path}")
        with open(pdf_path, "rb") as f:
            return f.read()
