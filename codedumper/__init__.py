"""CodeDumper - Export your repository to a single Markdown file for AI coding assistants."""

__version__ = "1.0.0"
__author__ = "Farhad Akhtar"

from codedumper.models import ScanConfig, ScanResult, FileItem, OmissionRecord
from codedumper.cli import main

__all__ = [
    "__version__",
    "ScanConfig",
    "ScanResult",
    "FileItem",
    "OmissionRecord",
    "main",
]
