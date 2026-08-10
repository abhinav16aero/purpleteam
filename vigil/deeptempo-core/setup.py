"""
Setup configuration for deeptempo-core shared library.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="deeptempo-core",
    version="1.0.0",
    description="Shared core library for DeepTempo AI SOC projects",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="DeepTempo",
    author_email="info@deeptempo.ai",
    url="https://github.com/deeptempo/deeptempo-core",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "sqlalchemy>=2.0.0",
        "psycopg2-binary>=2.9.9",
        "numpy>=1.26.0",
        "requests>=2.31.0",
        "aiohttp>=3.9.0",
        "fastapi>=0.109.0",
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

