"""Run from the SEO project root: python -m scripts.build_llm_foundation --keyword aviator"""
import argparse
from pathlib import Path
from llm_foundation.foundation import build

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--keyword',default='aviator')
    parser.add_argument('--input',default=None)
    parser.add_argument('--output',default=None)
    args=parser.parse_args()
    src=Path(args.input or f'output/results/{args.keyword}/{args.keyword}_comparison.json')
    out=Path(args.output or f'output/results/{args.keyword}/llm_foundation')
    if not src.is_file():
        parser.error(f'Comparison JSON not found: {src}')
    canonical,packets=build(src,out)
    print('Foundation schema:',canonical['schema_version'])
    print('Keyword:',canonical['investigation']['keyword'])
    print('Specialist packets:',', '.join(packets))
    print('Saved to:',out)
    print('No LLM or API requests were made.')
if __name__=='__main__':
    main()
