import os
import re
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak, KeepTogether
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute and print total page count:
    'Page X of Y', along with headers, watermarks, and status banners.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, total_pages):
        self.saveState()
        
        # 1. Top Watermark / Status Bar
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#B91C1C"))  # Crimson / Dark Red
        watermark_text = "DRAFT — PENDING LEGAL APPROVAL"
        self.drawCentredString(letter[0] / 2.0, letter[1] - 25, watermark_text)

        # 2. Header Line & Details
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#1E293B"))  # Slate-800
        self.drawString(54, letter[1] - 40, "Docintake — Official Documentation")
        
        self.setFont("Helvetica-Oblique", 7.5)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawRightString(letter[0] - 54, letter[1] - 40, "Document Status: DRAFT — PENDING LEGAL APPROVAL")
        
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.75)
        self.line(54, letter[1] - 44, letter[0] - 54, letter[1] - 44)

        # 3. Footer Line & Details
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.75)
        self.line(54, 45, letter[0] - 54, 45)

        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(54, 32, "Docintake | UAE Regulatory Compliance & Policy v1.1")
        
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(letter[0] - 54, 32, page_str)

        self.restoreState()


def build_pdf_from_markdown(md_file_path, pdf_file_path, doc_title):
    with open(md_file_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    doc = SimpleDocTemplate(
        pdf_file_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
        title=doc_title,
        author="Docintake"
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6
    )

    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )

    h3_style = ParagraphStyle(
        'SectionH3',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#334155"),
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=6
    )

    bullet_style = ParagraphStyle(
        'BulletDark',
        parent=body_style,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=3
    )

    alert_style = ParagraphStyle(
        'AlertBox',
        parent=body_style,
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#991B1B"),
        spaceBefore=4,
        spaceAfter=4
    )

    toc_title_style = ParagraphStyle(
        'TOCTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=10,
        spaceAfter=8
    )

    toc_item_style = ParagraphStyle(
        'TOCItem',
        fontName='Helvetica',
        fontSize=8.5,
        leading=13,
        textColor=colors.HexColor("#2563EB")
    )

    story = []

    # First pass: parse sections for Table of Contents
    lines = md_text.splitlines()
    toc_entries = []
    section_h1_regex = re.compile(r'^##\s+(\d+\.\s+.*)')
    for line in lines:
        m = section_h1_regex.match(line.strip())
        if m:
            toc_entries.append(m.group(1))

    # Document Header / Title
    story.append(Paragraph(doc_title, title_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2563EB"), spaceBefore=2, spaceAfter=8))
    
    # Metadata badge block
    meta_text = (
        "<b>Document Status:</b> <font color='#B91C1C'>DRAFT — PENDING LEGAL APPROVAL</font> &nbsp;|&nbsp; "
        "<b>Version:</b> v1.1 &nbsp;|&nbsp; <b>Jurisdiction:</b> UAE (Verification Pending)"
    )
    story.append(Paragraph(meta_text, body_style))
    story.append(Spacer(1, 6))

    # Table of Contents
    if toc_entries:
        story.append(Paragraph("Table of Contents", toc_title_style))
        toc_data = []
        for entry in toc_entries:
            toc_data.append([Paragraph(entry, toc_item_style)])
        
        toc_table = Table(toc_data, colWidths=[doc.width])
        toc_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#F1F5F9")),
            ('TOPPADDING', (0,0), (-1,-1), 2.5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(toc_table)
        story.append(Spacer(1, 14))

    # Parsing the markdown text into flowables
    i = 0
    in_table = False
    table_lines = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Handle tables
        if stripped.startswith('|') and stripped.endswith('|'):
            table_lines.append(stripped)
            i += 1
            continue
        elif table_lines:
            # Process accumulated markdown table
            headers = [h.strip() for h in table_lines[0].strip('|').split('|')]
            data_rows = []
            for r in table_lines[2:]:  # skip header separator
                cells = [c.strip() for c in r.strip('|').split('|')]
                data_rows.append(cells)
            
            table_flowable_data = []
            # Header row
            header_row = [Paragraph(f"<b>{h}</b>", body_style) for h in headers]
            table_flowable_data.append(header_row)
            for row in data_rows:
                row_flowables = [Paragraph(c, body_style) for c in row]
                table_flowable_data.append(row_flowables)
            
            num_cols = len(headers)
            col_width = doc.width / max(num_cols, 1)
            t = Table(table_flowable_data, colWidths=[col_width]*num_cols)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(Spacer(1, 4))
            story.append(t)
            story.append(Spacer(1, 6))
            table_lines = []

        if not stripped:
            i += 1
            continue

        if stripped.startswith('# '):
            # Already handled main title
            i += 1
            continue
        elif stripped.startswith('## '):
            heading_text = stripped[3:].strip()
            story.append(Paragraph(heading_text, h1_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceBefore=2, spaceAfter=4))
        elif stripped.startswith('### '):
            heading_text = stripped[4:].strip()
            story.append(Paragraph(heading_text, h2_style))
        elif stripped.startswith('#### '):
            heading_text = stripped[5:].strip()
            story.append(Paragraph(heading_text, h3_style))
        elif stripped.startswith('> '):
            alert_text = stripped[2:].strip()
            # Wrap in box table
            alert_p = Paragraph(f"<b>NOTICE:</b> {alert_text}", alert_style)
            alert_t = Table([[alert_p]], colWidths=[doc.width])
            alert_t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#FEF2F2")),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#F87171")),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ]))
            story.append(Spacer(1, 4))
            story.append(alert_t)
            story.append(Spacer(1, 6))
        elif stripped.startswith('- ') or stripped.startswith('* '):
            bullet_text = "&bull;&nbsp; " + stripped[2:].strip()
            # Clean markdown bold
            bullet_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', bullet_text)
            story.append(Paragraph(bullet_text, bullet_style))
        elif re.match(r'^\d+\.\s+', stripped):
            item_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', stripped)
            story.append(Paragraph(item_text, bullet_style))
        elif stripped == '---':
            story.append(Spacer(1, 4))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceBefore=2, spaceAfter=6))
        else:
            para_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', stripped)
            para_text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', para_text)
            story.append(Paragraph(para_text, body_style))

        i += 1

    # If any pending table left at EOF
    if table_lines:
        headers = [h.strip() for h in table_lines[0].strip('|').split('|')]
        data_rows = []
        for r in table_lines[2:]:
            cells = [c.strip() for c in r.strip('|').split('|')]
            data_rows.append(cells)
        
        table_flowable_data = []
        header_row = [Paragraph(f"<b>{h}</b>", body_style) for h in headers]
        table_flowable_data.append(header_row)
        for row in data_rows:
            row_flowables = [Paragraph(c, body_style) for c in row]
            table_flowable_data.append(row_flowables)
        
        num_cols = len(headers)
        col_width = doc.width / max(num_cols, 1)
        t = Table(table_flowable_data, colWidths=[col_width]*num_cols)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(Spacer(1, 4))
        story.append(t)
        story.append(Spacer(1, 6))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Generated: {pdf_file_path} (size: {os.path.getsize(pdf_file_path):,} bytes)")


if __name__ == "__main__":
    docs_dir = os.path.dirname(os.path.abspath(__file__))
    
    tc_md = os.path.join(docs_dir, "Docintake_Terms_and_Conditions_v1.1_DRAFT.md")
    tc_pdf = os.path.join(docs_dir, "Docintake_Terms_and_Conditions_v1.1_DRAFT.pdf")
    
    pp_md = os.path.join(docs_dir, "Docintake_Privacy_Policy_v1.1_DRAFT.md")
    pp_pdf = os.path.join(docs_dir, "Docintake_Privacy_Policy_v1.1_DRAFT.pdf")
    
    print("Building Terms and Conditions PDF...")
    build_pdf_from_markdown(tc_md, tc_pdf, "DocIntake T&C — Terms & Conditions")
    
    print("Building Privacy Policy PDF...")
    build_pdf_from_markdown(pp_md, pp_pdf, "DocIntake Privacy Policy")
