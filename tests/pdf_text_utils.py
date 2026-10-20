"""Canonicalize equivalent CJK glyph codes returned by CoreText-backed PDFs."""
import unicodedata


def normalize_pdf_text(text):
    # Kangxi radicals have NFKC decompositions. These visually identical CJK
    # Supplement glyphs do not, but CoreText also emits them for common Hanzi.
    return unicodedata.normalize('NFKC', text).translate({
        0x2EC4: '西', 0x2EC5: '见', 0x2ED3: '长', 0x2ED4: '门', 0x2EDA: '页'})
