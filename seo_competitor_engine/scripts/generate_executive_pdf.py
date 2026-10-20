"""Generate the management investigation report from validated local evidence."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from analysis.final_report import generate_report

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--keyword',required=True); p.add_argument('--input',type=Path); p.add_argument('--output-dir',type=Path); a=p.parse_args(argv)
    root=Path(__file__).resolve().parents[1]; out=a.output_dir or root/'output/results'/a.keyword; src=a.input or out/f'{a.keyword}_comparison.json'; data=json.loads(src.read_text(encoding='utf-8')); ex=json.loads((out/'llm_outputs/executive_validated.json').read_text(encoding='utf-8')) if (out/'llm_outputs/executive_validated.json').exists() else {}
    appendix=out/f'{a.keyword}_technical_appendix.md'; appendix.write_text(generate_report(data,source_name=src.name),encoding='utf-8')
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
        from reportlab.lib import colors
    except ImportError as exc: raise SystemExit('reportlab is required') from exc
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name='Mgmt',parent=styles['BodyText'],fontSize=10,leading=14,spaceAfter=7)); styles.add(ParagraphStyle(name='Callout',parent=styles['BodyText'],fontSize=11,leading=15,backColor=colors.HexColor('#f3effb'),borderColor=colors.HexColor('#6d28d9'),borderWidth=1,borderPadding=8,spaceAfter=10)); story=[]
    def para(text,style='Mgmt'): story.extend([Paragraph(str(text).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('**',''),styles[style]),Spacer(1,3)])
    def heading(text): story.append(Paragraph(text,styles['Heading1']))
    rank=data.get('ranking_summary',{}).get('google',{}); ours=rank.get('our_position'); bench=rank.get('benchmark_position');
    heading(f"SEO Competitive Intelligence — {a.keyword.title()}"); para('Management investigation report | Hollywoodbets versus Betway | South Africa','Callout'); para(ex.get('executive_summary','The saved evidence shows a one-position gap in the captured Google SERP.'))
    para('Purpose: explain where the competitive difference may come from, what remains uncertain, and which actions management should prioritize. This report uses observed evidence and qualified hypotheses, not claims about Google’s private ranking system.')
    story.append(PageBreak()); heading('Evidence-backed findings')
    for i, x in enumerate(ex.get('key_findings', []), 1):
        para(f"{i}. {x.get('statement','')}", 'Callout')
        para(f"What it means: {x.get('interpretation','')}")
        para(f"Why it matters: {x.get('why_it_matters','')}")
        para(f"Next check: {x.get('next_check','')}")
        para(f"Evidence: {', '.join(x.get('evidence_ids',[]))}. Limitation: {x.get('limitation','')}")
    story.append(PageBreak()); heading('Management recommendations')
    for i, d in enumerate(ex.get('proposed_decisions', []), 1):
        para(f"{i}. {d.get('title','')}", 'Callout')
        para(f"Team: {d.get('owner','')}. Action: {d.get('action','')}")
        para(f"How to check the result: {d.get('success_check','')}")
        para(f"Evidence: {', '.join(d.get('evidence_ids',[]))}. Limitation: {d.get('limitation','')}")
    para('Sequence: verify the exact ranking pages and current implementation, approve evidence-supported changes, then repeat comparable measurements.')
    story.append(PageBreak()); heading('Measurement and limitations'); para('Monitor the exact Aviator ranking URLs, title/search appearance, page-specific referring domains, related-query landing pages, and repeatable mobile performance measurements. Where field data is available, review it separately from Lighthouse lab results.')
    for x in ex.get('limitations',[]): para('• '+x)
    para('The technical appendix contains the exact URLs, measurements, evidence paths, diagnostic details and source limitations.')
    pdf=out/f'{a.keyword}_executive_report.pdf'
    def footer(canvas,doc): canvas.saveState(); canvas.setFont('Helvetica',8); canvas.drawString(18*mm,12*mm,'SEO Competitive Intelligence — Management investigation'); canvas.drawRightString(192*mm,12*mm,str(doc.page)); canvas.restoreState()
    SimpleDocTemplate(str(pdf),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=16*mm,bottomMargin=18*mm).build(story,onFirstPage=footer,onLaterPages=footer); print(pdf); print(appendix)
if __name__=='__main__': main()
