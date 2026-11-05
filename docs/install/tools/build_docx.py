"""Build the Word review copy of docs/install/README.md (pandoc + post-processing)."""
import re, subprocess, shutil, zipfile, os, sys
# Usage: build_docx.sh (it prepares the build folder and calls this script).
# argv[1] = output .docx, argv[2] = build folder holding ref/ (unzipped pandoc reference.docx) and img/ (schematic PNGs)
OUT = sys.argv[1]
SP = os.path.abspath(sys.argv[2])
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))

# ---- reference.docx styles ----
st = open(f'{SP}/ref/word/styles.xml').read()
st = st.replace('<w:rFonts w:asciiTheme="minorHAnsi" w:eastAsiaTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi" w:cstheme="minorBidi" />\n        <w:sz w:val="24" />\n        <w:szCs w:val="24" />',
                '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial" />\n        <w:sz w:val="20" />\n        <w:szCs w:val="20" />')
st = st.replace('w:asciiTheme="majorHAnsi" w:eastAsiaTheme="majorEastAsia" w:hAnsiTheme="majorHAnsi" w:cstheme="majorBidi"',
                'w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"')
st = re.sub(r'<w:color w:val="[0-9A-F]{6}" w:themeColor="accent1"( w:themeShade="[0-9A-F]+")? />', '<w:color w:val="000000" />', st)
def patch_style(sid, fn):
    global st
    m = re.search(r'(<w:style [^>]*w:styleId="%s">)(.*?)(</w:style>)' % sid, st, re.S)
    st = st[:m.start()] + fn(m.group(0)) + st[m.end():]
# heading sizes
for sid, sz, before, after in [('Heading1', 30, 360, 120), ('Heading2', 26, 280, 100), ('Heading3', 22, 220, 80), ('Heading4', 20, 200, 60)]:
    def f(x, sz=sz, before=before, after=after):
        x = re.sub(r'<w:spacing [^/]*/>', f'<w:spacing w:before="{before}" w:after="{after}" />', x)
        x = re.sub(r'<w:sz w:val="\d+" />', f'<w:sz w:val="{sz}" />', x)
        x = re.sub(r'<w:szCs w:val="\d+" />', f'<w:szCs w:val="{sz}" />', x)
        if '<w:sz ' not in x:
            x = x.replace('</w:rPr>', f'<w:sz w:val="{sz}" /><w:szCs w:val="{sz}" /></w:rPr>')
        return x.replace('<w:i />', '').replace('<w:iCs />', '')
    patch_style(sid, f)
patch_style('Heading1', lambda x: x.replace('<w:keepLines />', '<w:keepLines /><w:pageBreakBefore />'))
patch_style('BodyText', lambda x: x.replace('<w:spacing w:before="180" w:after="180" />', '<w:spacing w:before="60" w:after="100" />'))
patch_style('Compact', lambda x: x.replace('<w:spacing w:before="36" w:after="36" />', '<w:spacing w:before="20" w:after="20" />').replace('</w:pPr>', '</w:pPr><w:rPr><w:sz w:val="17" /><w:szCs w:val="17" /></w:rPr>'))
patch_style('BlockText', lambda x: x.replace('<w:ind w:firstLine="0" w:left="480" w:right="480" />', '<w:ind w:firstLine="0" w:left="240" w:right="240" />').replace('<w:pPr>', '<w:pPr><w:pBdr><w:left w:val="single" w:sz="24" w:space="8" w:color="000000" /></w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2" />', 1))
def tbl(x):
    x = x.replace('<w:tblInd w:w="0" w:type="dxa" />\n      <w:tblCellMar>',
      '<w:tblInd w:w="0" w:type="dxa" />\n      <w:tblBorders><w:top w:val="single" w:sz="4" w:color="000000"/><w:left w:val="single" w:sz="4" w:color="000000"/><w:bottom w:val="single" w:sz="4" w:color="000000"/><w:right w:val="single" w:sz="4" w:color="000000"/><w:insideH w:val="single" w:sz="4" w:color="000000"/><w:insideV w:val="single" w:sz="4" w:color="000000"/></w:tblBorders>\n      <w:tblCellMar>')
    x = x.replace('<w:top w:w="0" w:type="dxa" />', '<w:top w:w="30" w:type="dxa" />').replace('<w:bottom w:w="0" w:type="dxa" />', '<w:bottom w:w="30" w:type="dxa" />')
    x = x.replace('<w:left w:w="108" w:type="dxa" />', '<w:left w:w="70" w:type="dxa" />').replace('<w:right w:w="108" w:type="dxa" />', '<w:right w:w="70" w:type="dxa" />')
    x = re.sub(r'<w:tcPr>.*?</w:tcPr>', '<w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="8" w:color="000000"/></w:tcBorders><w:shd w:val="clear" w:color="auto" w:fill="D9D9D9"/><w:vAlign w:val="bottom"/></w:tcPr>', x, flags=re.S)
    x = x.replace('<w:tblStylePr w:type="firstRow">', '<w:tblStylePr w:type="firstRow"><w:rPr><w:b /><w:bCs /></w:rPr>')
    return x
patch_style('Table', tbl)
patch_style('VerbatimChar', lambda x: x.replace('<w:sz w:val="22" />', '<w:sz w:val="17" /><w:szCs w:val="17" />'))
open(f'{SP}/ref/word/styles.xml', 'w').write(st)
if os.path.exists(f'{SP}/reference.docx'): os.remove(f'{SP}/reference.docx')
subprocess.run(['zip', '-qXr', f'{SP}/reference.docx', '.'], cwd=f'{SP}/ref', check=True)

# ---- markdown preparation ----
md = open(f'{REPO}/docs/install/README.md').read()
# title block from the first heading
md = md.split('\n', 1)[1]
md = re.sub(r'!\[([^\]]*)\]\(schematics/([a-f]-[^)]+)\.svg\)', lambda m: f'![{m.group(1)}]({SP}/img/{m.group(2)}.png){{width=17cm}}', md)
# links to repo files: keep the path as text
md = re.sub(r'\[`([^`]+)`\]\((?!http)[^)]+\)', r'`\1`', md)
md = re.sub(r'\[([^\]]+)\]\(#[^)]+\)', r'\1', md)  # internal anchors: plain text
# drop the hand-written contents list (Word TOC replaces it)
md = re.sub(r'## Contents\n.*?\n---\n', '', md, flags=re.S)
md = md.replace('\n---\n', '\n')
header = '''---
title: "Installing the Adab energy and environment logger"
subtitle: "A practical for engineering students. DRAFT for review, version 0.1"
date: "5 November 2026"
---

'''
open(f'{SP}/manual.md', 'w').write(header + md)
subprocess.run(['pandoc', f'{SP}/manual.md', '-f', 'markdown-auto_identifiers+pipe_tables', '-o', f'{SP}/raw.docx',
                '--reference-doc', f'{SP}/reference.docx', '--toc', '--toc-depth=2', '--shift-heading-level-by=-1',
                '--metadata', 'toc-title=Contents'], check=True)

# ---- post-process: page setup, header/footer ----
w = f'{SP}/raw_x'
shutil.rmtree(w, ignore_errors=True)
with zipfile.ZipFile(f'{SP}/raw.docx') as z: z.extractall(w)
doc = open(f'{w}/word/document.xml').read()
sect = ('<w:sectPr><w:headerReference w:type="default" r:id="rIdHdr1"/><w:footerReference w:type="default" r:id="rIdFtr1"/>'
        '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1021" w:bottom="1134" w:left="1021" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')
doc = re.sub(r'<w:sectPr\b.*?</w:sectPr>', '', doc, flags=re.S)
# static TOC entries so viewers that do not update fields still show the contents
from xml.sax.saxutils import escape
entries = []
incode = False
for line in open(f'{SP}/manual.md').read().split('\n'):
    if line.startswith('```'): incode = not incode
    if incode: continue
    m = re.match(r'^(##|###) (.+)$', line)
    if m:
        lvl = 1 if m.group(1) == '##' else 2
        t = re.sub(r'[`*]', '', m.group(2))
        ind = 0 if lvl == 1 else 400
        b = '<w:b/>' if lvl == 1 else ''
        entries.append(f'<w:p><w:pPr><w:spacing w:before="{40 if lvl==1 else 0}" w:after="0"/><w:ind w:left="{ind}"/></w:pPr><w:r><w:rPr>{b}<w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">{escape(t)}</w:t></w:r></w:p>')
old = '<w:fldChar w:fldCharType="separate" /><w:fldChar w:fldCharType="end" /></w:r></w:p>'
assert old in doc
doc = doc.replace(old, '<w:fldChar w:fldCharType="separate" /></w:r></w:p>' + ''.join(entries) + '<w:p><w:r><w:fldChar w:fldCharType="end" /></w:r></w:p>', 1)
doc = doc.replace('</w:body>', sect + '</w:body>')
open(f'{w}/word/document.xml', 'w').write(doc)
NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
open(f'{w}/word/header1.xml', 'w').write(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {NS}><w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">Adab logger installation practical. DRAFT v0.1 for review, 5 November 2026</w:t></w:r></w:p></w:hdr>')
open(f'{w}/word/footer1.xml', 'w').write(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">Page </w:t></w:r><w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:t>1</w:t></w:r><w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')
rels = open(f'{w}/word/_rels/document.xml.rels').read()
rels = rels.replace('</Relationships>', '<Relationship Id="rIdHdr1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/><Relationship Id="rIdFtr1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>')
open(f'{w}/word/_rels/document.xml.rels', 'w').write(rels)
ct = open(f'{w}/[Content_Types].xml').read()
if 'Extension="png"' not in ct: ct = ct.replace('<Default ', '<Default Extension="png" ContentType="image/png"/><Default ', 1)
ct = ct.replace('</Types>', '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>')
open(f'{w}/[Content_Types].xml', 'w').write(ct)
se = open(f'{w}/word/settings.xml').read()
open(f'{w}/word/settings.xml', 'w').write(se)
if os.path.exists(OUT): os.remove(OUT)
subprocess.run(['zip', '-qXr', os.path.abspath(OUT), '.'], cwd=w, check=True)
print('wrote', OUT)
