"""Atalho de compatibilidade: python gerar_site.py  ==  python -m cupons"""
import sys

from cupons.pipeline import main

if __name__ == "__main__":
    main(sys.argv[1:])
