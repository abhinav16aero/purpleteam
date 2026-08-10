"""
Setup configuration for deeptempo-mcp-servers.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="deeptempo-mcp-servers",
    version="1.0.0",
    description="MCP servers for DeepTempo AI SOC",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="DeepTempo",
    author_email="info@deeptempo.ai",
    url="https://github.com/deeptempo/deeptempo-mcp-servers",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "deeptempo-core>=1.0.0",
        "mcp>=0.1.0",
        "fastmcp>=0.1.0",
        "numpy>=1.26.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "ruff>=0.1.0",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)

