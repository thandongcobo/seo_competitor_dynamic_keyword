from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

ROOT = Path(r'C:/Users/NgcoboT/Downloads/seo_competitor_engine_dynamic_keywords/seo_competitor_engine')
OUT = ROOT / 'output' / 'architecture_explainer.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)
purple = colors.HexColor('#32145f'); violet = colors.HexColor('#6b35c8'); ink = colors.HexColor('#15213b'); muted = colors.HexColor('#58657d'); light = colors.HexColor('#f6f4fa'); line = colors.HexColor('#ddd8e8')
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='Title2', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=ink, alignment=TA_CENTER, spaceAfter=5))
styles.add(ParagraphStyle(name='Subtitle', parent=styles['Normal'], fontSize=9.5, leading=13, textColor=muted, alignment=TA_CENTER, spaceAfter=12))
styles.add(ParagraphStyle(name='H2x', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=purple, spaceBefore=8, spaceAfter=6))
styles.add(ParagraphStyle(name='Bodyx', parent=styles['BodyText'], fontSize=8.5, leading=11.5, textColor=ink, spaceAfter=4))
styles.add(ParagraphStyle(name='Small', parent=styles['BodyText'], fontSize=7.5, leading=9.5, textColor=ink))
styles.add(ParagraphStyle(name='CellHead', parent=styles['BodyText'], fontName='Helvetica-Bold', fontSize=7.8, leading=9.5, textColor=colors.white))
styles.add(ParagraphStyle(name='Flow', parent=styles['BodyText'], fontName='Helvetica-Bold', fontSize=7.2, leading=9, textColor=purple, alignment=TA_CENTER))
def P(text, style='Bodyx'): return Paragraph(text, styles[style])
def flow(items):
    label = '   →   '.join(items)
    t=Table([[P(label,'Flow')]], colWidths=[174*mm], hAlign='CENTER')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),light),('BOX',(0,0),(-1,-1),.6,line),('INNERGRID',(0,0),(-1,-1),.4,line),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    return t
def data_table(rows):
    data=[[P('Data source','CellHead'),P('What it captures','CellHead'),P('Why it matters','CellHead')]]
    data += [[P(a,'Small'),P(b,'Small'),P(c,'Small')] for a,b,c in rows]
    t=Table(data,colWidths=[34*mm,62*mm,78*mm],repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),purple),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,light]),('GRID',(0,0),(-1,-1),.35,line),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    return t
def footer(canvas,doc):
    canvas.saveState(); canvas.setStrokeColor(line); canvas.line(18*mm,13*mm,192*mm,13*mm); canvas.setFont('Helvetica',7); canvas.setFillColor(muted); canvas.drawString(18*mm,8.5*mm,'SEO Competitor Intelligence Engine'); canvas.drawRightString(192*mm,8.5*mm,f'Page {doc.page}'); canvas.restoreState()
story=[P('SEO Competitor Intelligence Engine','Title2'),P('Simple architecture guide — what the engine collects, why it matters, and how the outputs are produced','Subtitle'),P('1. Competitor analysis engine','H2x'),P('This part answers: <b>Why might a competitor rank ahead?</b> It compares the exact pages ranking for the same keyword, then separates measured facts from interpretation.')]
story += [flow(['Keyword','Google SERP','Confirmed pages','Collect evidence','Validate','Compare','Interpret','Dashboard / PDF']),Spacer(1,7)]
rows=[('Google SERP / Playwright','Actual ranking positions, ranking URLs and search-result context.','Confirms who really ranks and identifies the exact pages that should be analysed.'),('Playwright page extraction','Titles, metadata, headings, content, links and structured data.','Shows how each ranking page is presented and what it appears to target.'),('DataForSEO backlinks','Page-level and domain-level backlink metrics.','Measures authority differences while keeping page evidence separate from domain evidence.'),('DataForSEO Labs','Related keyword rankings, shared queries and search intent signals.','Shows broader competition and related search coverage.'),('Lighthouse','LCP, TBT, performance scores and diagnostics.','Finds technical differences worth investigating.'),('Python engine','Verified calculations, ranking gaps and evidence quality.','Prevents incorrect numbers and unsupported conclusions.'),('Local Gemma','Evidence-based interpretations and hypotheses.','Explains what differences might mean; it does not calculate the facts.'),('Dashboard / PDF','Findings, limitations, priorities and actions.','Turns technical evidence into decisions the team can discuss and test.')]
story += [data_table(rows),Spacer(1,8),P('How a finding becomes an action','H2x'),flow(['Observed difference','Possible explanation','Evidence','Counterevidence','Action','Validation']),Spacer(1,5),P('Important: the engine identifies evidence and plausible explanations. It must not claim that one factor caused Google’s ranking decision unless that claim is independently proven.')]
story += [PageBreak(),P('SEO Competitor Intelligence Engine','Title2'),P('Simple architecture guide — how competitor changes are captured and analysed over time','Subtitle'),P('2. Competitor change analysis','H2x'),P('This part answers: <b>What changed on a competitor’s page?</b> It captures verified pages repeatedly, stores each successful version, and compares versions without confusing a failed capture with a real change.'),flow(['Confirmed URL','Register','Capture','Validate','Store history','Compare','Dashboard','Interpret']),Spacer(1,8)]
rows2=[('Registration','Confirmed URL, keyword and evidence reference.','Ensures that only verified SERP pages are monitored.'),('Playwright capture','The current rendered webpage state.','Captures what a user and search crawler can see on the page.'),('SQLite history','Every successful capture with its timestamp.','Makes earlier versions retrievable and auditable.'),('Snapshot artifacts','An immutable copy of captured page evidence.','Preserves the page state used for the analysis.'),('Change detector','Differences between successful snapshots.','Finds additions, removals and modifications.'),('Content hash','A stable fingerprint of page content.','Recognises identical captures and avoids false changes.'),('Validation','Rendering quality, final URL and extraction status.','Stops failed or partial captures becoming misleading alerts.'),('Scheduler','Periodic capture runs.','Keeps monitoring continuous instead of relying on manual checks.'),('Gemma change analysis','Possible SEO or marketing significance.','Explains which changes may deserve human attention.')]
story += [data_table(rows2),Spacer(1,8),P('Fields compared','H2x'),P('Page title  •  Meta description  •  Canonical URL  •  Headings  •  Main content  •  FAQs  •  Internal links  •  External links  •  Structured data  •  Promotional messages  •  Calls to action')]
example=[[P('Previous','CellHead'),P('Current','CellHead'),P('Detected change','CellHead'),P('Possible response','CellHead')],[P('Play Aviator Online','Small'),P('Play Aviator Online — Get 10 Free Flights','Small'),P('Modified page title','Small'),P('Review title and snippet clarity, then recapture and monitor the target query.','Small')]]
t=Table(example,colWidths=[38*mm,48*mm,38*mm,50*mm]); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),violet),('BACKGROUND',(0,1),(-1,1),light),('GRID',(0,0),(-1,-1),.35,line),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)])); story += [t]
doc=SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=14*mm,bottomMargin=18*mm); doc.build(story,onFirstPage=footer,onLaterPages=footer); print(OUT)
